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

logger = logging.getLogger("ssubb.task_manager")


class TaskManager:
    """任务生命周期管理"""

    def __init__(self, config: CoordinatorConfig):
        self.config = config
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
        self.worker = WorkerClient(config.worker.url) if config.worker.url else None
        self.scheduler = None  # 由 main.py 设置

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
        asyncio.create_task(self._process_task(task.id))

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

        asyncio.create_task(self._process_task(task_id))
        return self.store.get_task(task_id)

    # =========================================================================
    # 任务处理流程
    # =========================================================================

    async def _process_task(self, task_id: str):
        """完整的任务处理流程"""
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

            # Step 2: 提取音频
            self.store.update_status(task_id, TaskStatus.EXTRACTING, progress=10)
            t0 = time.time()

            audio_path = extract_audio(
                task.media_path,
                self.config.audio.temp_dir,
                audio_format=self.config.audio.format,
                sample_rate=self.config.audio.sample_rate,
                channels=self.config.audio.channels,
            )

            self.store.update_stage_time(task_id, "extracting", time.time() - t0)

            if audio_path is None:
                self._fail_task(
                    task_id, "音频提取失败",
                    ErrorCode.AUDIO_EXTRACT_ERROR, TaskStatus.EXTRACTING,
                )
                return

            self.store.update_audio_path(task_id, audio_path)

            # Step 3: 分发到 Worker
            if self.worker is None:
                self._fail_task(
                    task_id, "Worker 未配置",
                    ErrorCode.CONFIG_ERROR, TaskStatus.UPLOADING,
                )
                return

            self.store.update_status(task_id, TaskStatus.UPLOADING, progress=20)
            t0 = time.time()

            task_config = TaskConfig(
                source_lang=task.source_lang,
                target_lang=task.target_lang,
            )
            self.store.update_config(task_id, task_config)

            success = await self.worker.submit_task(
                task_id=task_id,
                audio_path=audio_path,
                config=task_config,
                source_lang=task.source_lang,
                target_lang=task.target_lang,
            )

            self.store.update_stage_time(task_id, "uploading", time.time() - t0)

            if success:
                self.store.update_status(
                    task_id, TaskStatus.TRANSCRIBING, progress=30,
                    worker_id=self.config.worker.url,
                )
                logger.info(f"[{task_id}] 已分发到 Worker")
            else:
                self._fail_task(
                    task_id, "Worker 提交失败",
                    ErrorCode.UPLOAD_ERROR, TaskStatus.UPLOADING,
                )

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

    # =========================================================================
    # 后台巡检
    # =========================================================================

    def start_watcher(self):
        """启动后台巡检任务"""
        if not hasattr(self, "_watcher_task") or self._watcher_task is None:
            self._watcher_task = asyncio.create_task(self._watch_loop())
            logger.info("后台自愈环境巡检已启动")

    async def _watch_loop(self):
        """定期检查 Worker 状态并处理挂起 / 超时任务"""
        check_interval = self.config.worker.heartbeat_interval

        while True:
            await asyncio.sleep(check_interval)
            try:
                # 1. 检查 Worker 连通性
                is_online = False
                if self.worker:
                    is_online = await self.worker.check_health()

                # 2. 检查超时任务
                stage_timeouts = dict(STAGE_TIMEOUTS)
                # 用配置覆盖默认超时
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
                        asyncio.create_task(self._process_task(task.id))
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

                # 3. 若 Worker 在线，恢复堆积的 pending 任务
                if is_online:
                    stuck_tasks = self.store.get_tasks(status=TaskStatus.PENDING)
                    for task in stuck_tasks:
                        try:
                            logger.info(
                                f"[{task.id}] 发现堆积/挂起任务，"
                                f"尝试断线自愈重推 (Worker 已上线)"
                            )
                            asyncio.create_task(self._process_task(task.id))
                        except Exception as e:
                            logger.error(f"恢复任务 {task.id} 故障: {e}")
                else:
                    logger.debug("巡检: Worker 处于脱机状态，等待网络恢复...")

            except Exception as e:
                logger.error(f"后台巡检异常: {e}")

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
            # 写入字幕
            self.store.update_status(task_id, TaskStatus.WRITING_SUBTITLE, progress=90)
            t0 = time.time()

            subtitle_path = self.writer.write_subtitle(
                video_path=task.media_path,
                subtitle_content=result.subtitle_srt,
                target_lang=task.target_lang,
                subtitle_format="srt",
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

                # 记录 Worker 侧阶段耗时
                if result.transcribe_duration:
                    self.store.update_stage_time(task_id, "transcribing", result.transcribe_duration)
                if result.translate_duration:
                    self.store.update_stage_time(task_id, "translating", result.translate_duration)

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
                    asyncio.create_task(self._trigger_webhook(task, result))

                # 预热下一集
                if self.scheduler:
                    asyncio.create_task(
                        self.scheduler.preheat_next_episode(task.media_path, task.target_lang)
                    )

                return True
            else:
                self._fail_task(
                    task_id, "字幕写入失败",
                    ErrorCode.SUBTITLE_WRITE_ERROR, TaskStatus.WRITING_SUBTITLE,
                )
                if task.callback_url:
                    asyncio.create_task(self._trigger_webhook(task, result))
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
                asyncio.create_task(self._trigger_webhook(task, result))
            return False

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
