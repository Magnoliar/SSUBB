"""SSUBB Coordinator - 任务管理器

编排整个任务生命周期: 创建 → 检查 → 提取 → 分发 → 回收 → 写入。
"""

import asyncio
import logging
import time
from typing import Optional

from shared.constants import TaskStatus, ErrorCode, STAGE_TIMEOUTS
from shared.models import TaskConfig, TaskCreate, TaskInfo, WorkerTaskResult

from .audio_extractor import cleanup_audio, extract_audio, get_video_duration
from .config import CoordinatorConfig
from .subtitle_checker import SubtitleChecker
from .subtitle_writer import SubtitleWriter
from .task_store import TaskStore
from .worker_client import WorkerClient
from .worker_registry import WorkerRegistry

logger = logging.getLogger("ssubb.task_manager")


def _safe_background_task(coro, label: str = "background"):
    """包装 fire-and-forget 任务，确保异常被记录而非静默吞没"""
    async def _wrapper():
        try:
            await coro
        except Exception as e:
            logger.error(f"[{label}] 后台任务异常: {e}", exc_info=True)
    return asyncio.create_task(_wrapper())


class TaskManager:
    """任务生命周期管理"""

    def __init__(self, config: CoordinatorConfig, worker_registry: WorkerRegistry):
        self.config = config
        self.registry = worker_registry
        self.store = TaskStore(config.db_path)
        self.checker = SubtitleChecker(
            min_coverage=config.checker.min_coverage,
            min_density=config.checker.min_density,
            check_language=config.checker.check_language,
        )
        self.writer = SubtitleWriter(
            emby_server=config.emby.server,
            emby_api_key=config.emby.api_key,
            backup_existing=config.subtitle.backup_existing,
            output_mode=config.subtitle.output_mode,
            output_format=config.subtitle.output_format,
        )
        self.scheduler = None  # 由 main.py 设置
        self._extract_semaphore = asyncio.Semaphore(2)  # 最大并发提取数

    # =========================================================================
    # 任务创建
    # =========================================================================

    async def create_task(self, req: TaskCreate) -> TaskInfo:
        """创建新任务

        流程: 去重检查 → 字幕质量检查 → 创建任务 → 启动处理
        """
        # 1. 去重: 检查是否已有活跃任务
        existing = self.store.find_existing_task(req.media_path, req.target_lang)
        if existing and not req.force:
            logger.info(f"任务已存在 ({existing.status}): {req.media_path}")
            return existing

        # 2. 创建任务
        task = self.store.create_task(req)
        logger.info(f"[{task.id}] 创建任务: {req.media_title or req.media_path}")

        # 3. 异步启动处理流程
        _safe_background_task(self._process_task(task.id), f"create-{task.id}")

        return task

    async def force_regenerate(self, media_path: str, target_lang: str = "zh") -> TaskInfo:
        """强制重新生成字幕 (绕过所有检查)"""
        req = TaskCreate(
            media_path=media_path,
            target_lang=target_lang,
            force=True,
        )
        return await self.create_task(req)

    async def retry_task(self, task_id: str) -> Optional[TaskInfo]:
        """手动重试失败的任务"""
        task = self.store.get_task(task_id)
        if task is None:
            return None

        if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            logger.warning(f"[{task_id}] 任务状态 {task.status} 不允许重试")
            return task

        if task.retry_count >= self.config.retry.max_retries:
            logger.warning(f"[{task_id}] 已达最大重试次数 ({task.retry_count})")
            # 仍然允许手动重试，但记录警告
            pass

        self.store.reset_for_retry(task_id)
        logger.info(f"[{task_id}] 手动重试 (第 {task.retry_count + 1} 次)")

        _safe_background_task(self._process_task(task_id), f"retry-{task_id}")
        return self.store.get_task(task_id)

    # =========================================================================
    # 任务处理流程
    # =========================================================================

    async def _process_task(self, task_id: str):
        """任务处理流程: 字幕检查 → 提取音频 → 标记 EXTRACTED (分发由 _dispatch_loop 负责)"""
        task = self.store.get_task(task_id)
        if task is None:
            return

        try:
            # Step 1: 字幕检查 (非强制模式)
            if not task.force_mode:
                self.store.update_status(task_id, TaskStatus.SUBTITLE_CHECKING, progress=5)
                t0 = time.time()

                video_duration = get_video_duration(task.media_path)
                should_process, reason = self.checker.should_process(
                    task.media_path,
                    task.target_lang,
                    force=False,
                    video_duration=video_duration,
                )

                self.store.update_stage_time(task_id, "subtitle_checking", time.time() - t0)

                if not should_process:
                    self.store.update_status(
                        task_id, TaskStatus.SKIPPED,
                        skip_reason=reason,
                    )
                    logger.info(f"[{task_id}] 跳过: {reason}")
                    return

            # Step 2: 提取音频 (并发受限)
            async with self._extract_semaphore:
                self.store.update_status(task_id, TaskStatus.EXTRACTING, progress=10)
                t0 = time.time()

                loop = asyncio.get_event_loop()
                audio_path = await loop.run_in_executor(
                    None,
                    lambda: extract_audio(
                        task.media_path,
                        self.config.audio.temp_dir,
                        audio_format=self.config.audio.format,
                        sample_rate=self.config.audio.sample_rate,
                        channels=self.config.audio.channels,
                    ),
                )

                self.store.update_stage_time(task_id, "extracting", time.time() - t0)

            if audio_path is None:
                self._fail_task(
                    task_id, "音频提取失败",
                    ErrorCode.AUDIO_EXTRACT_ERROR, TaskStatus.EXTRACTING,
                )
                return

            self.store.update_audio_path(task_id, audio_path)

            # Step 3: 标记为 EXTRACTED，等待 dispatch_loop 分发
            self.store.update_status(task_id, TaskStatus.EXTRACTED, progress=15)
            logger.info(f"[{task_id}] 音频已提取，等待分发到 Worker")

        except Exception as e:
            logger.exception(f"[{task_id}] 处理异常: {e}")
            self._fail_task(
                task_id, str(e),
                ErrorCode.UNKNOWN_ERROR, None,
            )

    def _fail_task(
        self,
        task_id: str,
        error_msg: str,
        error_code: str,
        failed_stage: Optional[str],
    ):
        """统一设置任务失败"""
        self.store.update_status(
            task_id, TaskStatus.FAILED,
            error_msg=error_msg,
            error_code=error_code,
            failed_stage=failed_stage,
        )
        logger.error(f"[{task_id}] ❌ 失败 [{error_code}]: {error_msg}")

    async def _dispatch_to_worker(
        self,
        task_id: str,
        audio_path: str,
        config: TaskConfig,
        source_lang: str,
        target_lang: str,
    ) -> Optional[str]:
        """选择最佳可用 Worker 并提交任务

        算法: 加权最少连接
        1. 筛选: 仅在线 Worker
        2. 排序: (queue_length ASC, -weight DESC)
        3. 提交到首选候选，失败则 fallback

        Returns:
            worker_url 成功, None 无可用 Worker 或全部失败
        """
        candidates = self.registry.get_online_workers()
        if not candidates:
            logger.warning(f"[{task_id}] 无在线 Worker")
            return None

        # 评分: (queue_length, -adaptive_weight) — 越低越好
        def score(item):
            _client, status, config_weight = item
            ql = status.heartbeat.queue_length if status.heartbeat else 999
            adaptive_w = self.registry.get_adaptive_weight(status.url)
            return (ql, -adaptive_w)

        candidates.sort(key=score)

        for client, status, config_weight in candidates:
            try:
                success = await client.submit_task(
                    task_id=task_id,
                    audio_path=audio_path,
                    config=config,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
                if success:
                    ql = status.heartbeat.queue_length if status.heartbeat else '?'
                    adaptive_w = self.registry.get_adaptive_weight(status.url)
                    logger.info(
                        f"[{task_id}] 分发到 {status.worker_id} "
                        f"({status.url}, weight={adaptive_w}, queue={ql})"
                    )
                    return status.url
            except Exception as e:
                logger.warning(f"[{task_id}] 提交到 {status.url} 失败: {e}")
                continue

        logger.error(f"[{task_id}] 所有 Worker 提交失败")
        return None

    # =========================================================================
    # 后台巡检
    # =========================================================================

    def start_watcher(self):
        """启动后台巡检任务和分发循环"""
        if not hasattr(self, "_watcher_task") or self._watcher_task is None:
            self._watcher_task = asyncio.create_task(self._watch_loop())
            self._dispatch_task = asyncio.create_task(self._dispatch_loop())
            logger.info("后台巡检 + 分发循环已启动")

    async def _watch_loop(self):
        """定期检查 Worker 状态并处理超时任务 (不含批量重推 pending)"""
        check_interval = self.config.worker.heartbeat_interval

        while True:
            await asyncio.sleep(check_interval)
            try:
                # 1. 故障迁移: 将分配给离线 Worker 的活跃任务迁回队列
                await self._migrate_offline_tasks()

                # 2. 检查超时任务
                stage_timeouts = dict(STAGE_TIMEOUTS)
                cfg_timeout = self.config.stage_timeout
                stage_timeouts[TaskStatus.EXTRACTING] = cfg_timeout.extracting
                stage_timeouts[TaskStatus.UPLOADING] = cfg_timeout.uploading
                stage_timeouts[TaskStatus.TRANSCRIBING] = cfg_timeout.transcribing
                stage_timeouts[TaskStatus.TRANSLATING] = cfg_timeout.translating
                stage_timeouts["_default"] = cfg_timeout.default

                timed_out_tasks = self.store.find_timed_out_tasks(stage_timeouts)
                for task in timed_out_tasks:
                    if task.retry_count < self.config.retry.max_retries:
                        logger.warning(
                            f"[{task.id}] 任务在 {task.status} 阶段超时，"
                            f"尝试自动重试 ({task.retry_count + 1}/{self.config.retry.max_retries})"
                        )
                        self.store.reset_for_retry(task.id)
                        _safe_background_task(self._process_task(task.id), f"timeout-retry-{task.id}")
                    else:
                        logger.error(
                            f"[{task.id}] 任务在 {task.status} 阶段超时且已耗尽重试次数"
                        )
                        self._fail_task(
                            task.id,
                            f"阶段 {task.status} 超时，已重试 {task.retry_count} 次",
                            ErrorCode.TIMEOUT_ERROR,
                            task.status,
                        )

            except Exception as e:
                logger.error(f"后台巡检异常: {e}")

    async def _dispatch_loop(self):
        """后台分发循环: 拾取 EXTRACTED 任务并分发到可用 Worker"""
        while True:
            await asyncio.sleep(5)  # 每 5 秒检查一次
            try:
                if not self.registry.is_any_worker_online():
                    continue

                extracted_tasks = self.store.get_tasks(
                    status=TaskStatus.EXTRACTED, limit=10
                )
                if not extracted_tasks:
                    continue

                for task in extracted_tasks:
                    if not task.audio_path:
                        logger.warning(f"[{task.id}] EXTRACTED 但无 audio_path，跳过")
                        continue

                    task_config = task.config or TaskConfig(
                        source_lang=task.source_lang,
                        target_lang=task.target_lang,
                    )
                    if not task.config:
                        self.store.update_config(task.id, task_config)

                    self.store.update_status(task.id, TaskStatus.UPLOADING, progress=20)
                    t0 = time.time()

                    worker_url = await self._dispatch_to_worker(
                        task.id, task.audio_path, task_config,
                        task.source_lang, task.target_lang,
                    )

                    self.store.update_stage_time(task.id, "uploading", time.time() - t0)

                    if worker_url:
                        self.store.update_status(
                            task.id, TaskStatus.TRANSCRIBING,
                            progress=30, worker_id=worker_url,
                        )
                        logger.info(f"[{task.id}] 已分发到 {worker_url}")
                    else:
                        # 放回 EXTRACTED 等待下次重试
                        self.store.update_status(task.id, TaskStatus.EXTRACTED, progress=15)
                        logger.warning(f"[{task.id}] 分发失败，等待重试")

            except Exception as e:
                logger.error(f"分发循环异常: {e}")

    # =========================================================================
    # 故障迁移
    # =========================================================================

    async def _migrate_offline_tasks(self):
        """将分配给离线 Worker 的活跃任务迁移回队列"""
        online_urls = {s.url for s in self.registry.get_all_statuses() if s.online}
        if not online_urls:
            return  # 没有在线 Worker，无法迁移

        tasks_to_migrate = self.store.get_active_tasks_with_worker()
        for task in tasks_to_migrate:
            if task.worker_id and task.worker_id not in online_urls:
                logger.warning(
                    f"[{task.id}] Worker {task.worker_id} 离线，"
                    f"迁移任务 (状态: {task.status}) → 重新排队"
                )
                self.store.reset_for_retry(task.id)
                _safe_background_task(self._process_task(task.id), f"migrate-{task.id}")

    # =========================================================================
    # 结果回收
    # =========================================================================

    async def handle_result(self, result: WorkerTaskResult) -> bool:
        """处理 Worker 回调的任务结果"""
        task_id = result.task_id
        task = self.store.get_task(task_id)
        if task is None:
            logger.warning(f"收到未知任务结果: {task_id}")
            return False

        if result.status == "completed" and result.subtitle_srt:
            # 保存字幕到数据库（供预览/编辑）
            self.store.save_subtitle(task_id, result.subtitle_srt, result.original_srt or "")

            # 写入字幕
            self.store.update_status(task_id, TaskStatus.WRITING_SUBTITLE, progress=90)
            t0 = time.time()

            subtitle_path = self.writer.write_subtitle(
                video_path=task.media_path,
                subtitle_content=result.subtitle_srt,
                target_lang=task.target_lang,
                original_srt=result.original_srt or "",
            )

            self.store.update_stage_time(task_id, "writing_subtitle", time.time() - t0)

            if subtitle_path:
                # 刷新 Emby
                self.store.update_status(task_id, TaskStatus.REFRESHING_EMBY, progress=95)
                t0 = time.time()
                await self.writer.refresh_emby(task.media_path)
                self.store.update_stage_time(task_id, "refreshing_emby", time.time() - t0)

                # 记录结果摘要
                summary = {
                    "detected_language": result.detected_language,
                    "segment_count": result.segment_count,
                    "transcribe_duration": result.transcribe_duration,
                    "translate_duration": result.translate_duration,
                    "total_duration": result.total_duration,
                    "subtitle_path": subtitle_path,
                }
                self.store.update_result_summary(task_id, summary)

                # 记录 Worker 性能 (用于自适应权重)
                if result.total_duration and result.total_duration > 0 and task.worker_id:
                    try:
                        from .audio_extractor import get_video_duration
                        vid_dur = get_video_duration(task.media_path)
                        if vid_dur and vid_dur > 0:
                            self.registry.record_performance(
                                task.worker_id, vid_dur / 60, result.total_duration
                            )
                    except Exception:
                        pass  # 性能记录失败不影响主流程

                # 记录 Worker 侧阶段耗时
                if result.transcribe_duration:
                    self.store.update_stage_time(task_id, "transcribing", result.transcribe_duration)
                if result.translate_duration:
                    self.store.update_stage_time(task_id, "translating", result.translate_duration)

                # 字幕质量评分
                try:
                    from .audio_extractor import get_video_duration
                    vid_dur = get_video_duration(task.media_path)
                    quality = self.checker.score_subtitle(result.subtitle_srt, vid_dur)
                    summary["quality_score"] = quality["score"]
                    summary["quality_grade"] = quality["grade"]
                    summary["quality_details"] = quality["details"]
                    self.store.update_result_summary(task_id, summary)
                    logger.info(
                        f"[{task_id}] 质量评分: {quality['score']}/100 ({quality['grade']})"
                        + (f" — {'; '.join(quality['issues'])}" if quality["issues"] else "")
                    )

                    # C 级以下 (score < 60)：自动段落级修复
                    if quality["score"] < 60:
                        logger.info(f"[{task_id}] 质量较低，尝试自动段落修复...")
                        repaired = await self._auto_repair_subtitles(
                            task_id, result.subtitle_srt, result.original_srt or ""
                        )
                        if repaired and repaired != result.subtitle_srt:
                            self.store.save_subtitle(task_id, repaired, result.original_srt or "")
                            self.writer.write_subtitle(
                                video_path=task.media_path,
                                subtitle_content=repaired,
                                target_lang=task.target_lang,
                                original_srt=result.original_srt or "",
                            )
                            logger.info(f"[{task_id}] 自动修复完成，字幕已更新")

                    # 极低分 (score < 40)：自动重试
                    if quality["score"] < 40 and task.retry_count < self.config.retry.max_retries:
                        logger.warning(
                            f"[{task_id}] 质量评分过低 ({quality['score']}/100)，自动重试"
                        )
                        self.store.reset_for_retry(task_id)
                        _safe_background_task(self._process_task(task_id), f"quality-retry-{task_id}")
                        return False

                except TypeError as e:
                    # 评分返回 None（LLM 全部不可用）→ 不保存字幕，标记待重试
                    logger.warning(f"[{task_id}] 质量评分服务不可用，跳过保存: {e}")
                    self.store.update_status(task_id, TaskStatus.PENDING, progress=0, error_msg="评分服务不可用")
                    return False
                except Exception as e:
                    logger.warning(f"[{task_id}] 质量评分失败 (不影响完成): {e}")

                # 更新状态
                self.store.update_status(task_id, TaskStatus.COMPLETED, progress=100)
                
                # 清理临时音频
                if task.audio_path:
                    cleanup_audio(task.audio_path)
                
                logger.info(
                    f"[{task_id}] ✅ 完成: {task.media_title or task.media_path} "
                    f"({result.detected_language}→{task.target_lang}, "
                    f"{result.segment_count}条, {result.total_duration:.0f}s)"
                )
                
                if task.callback_url:
                    _safe_background_task(self._trigger_webhook(task, result), f"webhook-{task_id}")

                # 预热下一集
                if self.scheduler:
                    _safe_background_task(
                        self.scheduler.preheat_next_episode(task.media_path, task.target_lang),
                        f"preheat-{task_id}",
                    )

                return True
            else:
                self._fail_task(
                    task_id, "字幕写入失败",
                    ErrorCode.SUBTITLE_WRITE_ERROR, TaskStatus.WRITING_SUBTITLE,
                )
                if task.callback_url:
                    _safe_background_task(self._trigger_webhook(task, result), f"webhook-{task_id}")
                return False
        else:
            # 处理失败
            error_code = result.error_code or ErrorCode.UNKNOWN_ERROR
            self._fail_task(
                task_id,
                result.error or "Worker 处理失败",
                error_code, None,
            )
            if task.callback_url:
                _safe_background_task(self._trigger_webhook(task, result), f"webhook-{task_id}")
            return False

    async def _auto_repair_subtitles(
        self, task_id: str, srt_content: str, original_srt: str
    ) -> Optional[str]:
        """自动段落级修复：扫描异常段落，带上下文重新优化"""
        import re

        def _parse_srt_entries(text: str) -> list[dict]:
            entries = []
            blocks = re.split(r"\n\s*\n", text.strip())
            time_pattern = re.compile(
                r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}"
            )
            for block in blocks:
                lines = block.strip().split("\n")
                timecode = None
                text_start = 0
                for i, line in enumerate(lines):
                    if time_pattern.search(line):
                        timecode = line.strip()
                        text_start = i + 1
                        break
                if timecode:
                    text_val = "\n".join(lines[text_start:]).strip()
                    if text_val:
                        entries.append({"timecode": timecode, "text": text_val})
            return entries

        def _is_segment_bad(entry: dict) -> bool:
            text = entry["text"]
            # 过短或过长
            if len(text) < 2:
                return True
            if len(text) > 200:
                return True
            # 包含明显的 LLM 错误标记
            if any(marker in text.lower() for marker in ["[error", "failed", "null", "undefined"]):
                return True
            return False

        entries = _parse_srt_entries(srt_content)
        if not entries:
            return srt_content

        bad_indices = [i for i, e in enumerate(entries) if _is_segment_bad(e)]
        if not bad_indices:
            return srt_content

        logger.info(f"[{task_id}] 发现 {len(bad_indices)} 个异常段落，开始定点修复...")

        # 使用滑动上下文窗口（前后各 5 条）
        window = 5
        for idx in bad_indices[:10]:  # 最多修复 10 个
            ctx_start = max(0, idx - window)
            ctx_end = min(len(entries), idx + window + 1)
            ctx_entries = entries[ctx_start:ctx_end]

            try:
                from .worker_client import WorkerClient
                # 选取分配的 Worker 进行修复
                worker_client = None
                if task_id:
                    task = self.store.get_task(task_id)
                    if task and task.worker_id:
                        worker_client = self.registry.get_client_by_url(task.worker_id)

                if worker_client:
                    repaired = await worker_client.reoptimize_segments(
                        ctx_entries, [idx - ctx_start]
                    )
                    if repaired:
                        entries[idx] = repaired[0]
            except Exception as e:
                logger.debug(f"段落 {idx} 修复失败: {e}")

        # 重建 SRT
        lines = []
        for i, entry in enumerate(entries):
            lines.append(str(i + 1))
            lines.append(entry["timecode"])
            lines.append(entry["text"])
            lines.append("")
        return "\n".join(lines)

    async def _trigger_webhook(self, task, result: WorkerTaskResult):
        """异步触发状态回调以投递系统消息"""
        import httpx
        from pathlib import Path
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload = {
                    "task_id": task.id,
                    "media_title": task.media_title or Path(task.media_path).name,
                    "status": task.status,
                    "message": task.error_msg if getattr(task, 'error_msg', None) else "成功",
                    "time_cost": round(result.total_duration or 0, 1),
                    "target_lang": task.target_lang
                }
                res = await client.post(task.callback_url, json=payload)
                if res.status_code == 200:
                    logger.info(f"[{task.id}] Webhook 投递成功")
                else:
                    logger.warning(f"[{task.id}] Webhook 投递失败，状态码: {res.status_code}")
        except Exception as e:
            logger.error(f"[{task.id}] Webhook 网络异常: {e}")

    # =========================================================================
    # 进度更新
    # =========================================================================

    def update_progress(self, task_id: str, status: str, progress: int):
        """更新任务进度 (来自 Worker 的进度回调)"""
        self.store.update_status(task_id, status, progress=progress)

    # =========================================================================
    # 查询
    # =========================================================================

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self.store.get_task(task_id)

    def get_tasks(self, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[TaskInfo]:
        return self.store.get_tasks(status=status, limit=limit, offset=offset)

    def get_task_count(self, status: Optional[str] = None) -> int:
        return self.store.count_tasks(status=status)

    def get_stats(self) -> dict:
        return self.store.count_by_status()
