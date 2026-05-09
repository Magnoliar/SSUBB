"""SSUBB Worker - 任务执行流水线

编排: 转写 → 优化 → 翻译 → 对轴 → 回调。
"""

import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from shared.constants import TaskStatus
from shared.models import TaskConfig, WorkerProgressUpdate, WorkerTaskResult

from worker.config import WorkerConfig

logger = logging.getLogger("ssubb.executor")


class TaskExecutor:
    """任务流水线执行器"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.current_task_id: Optional[str] = None
        self.current_progress: int = 0
        self._http: Optional[httpx.AsyncClient] = None
        self._llm_client = None  # 共享 LLM 客户端 (惰性创建)

    def _get_llm(self):
        """获取或创建共享的 LLMClient 实例"""
        if self._llm_client is None:
            from worker.llm_client import LLMClient
            self._llm_client = LLMClient(self.config.llm_providers)
        return self._llm_client

    async def close(self):
        """关闭 httpx 客户端和 LLM 客户端"""
        if self._llm_client:
            await self._llm_client.close()
            self._llm_client = None
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def execute(
        self,
        task_id: str,
        audio_path: str,
        task_config: TaskConfig,
    ) -> WorkerTaskResult:
        """执行完整的字幕处理流水线

        Args:
            task_id: 任务 ID
            audio_path: 音频文件路径
            task_config: 处理配置

        Returns:
            处理结果
        """
        self.current_task_id = task_id
        self.current_progress = 0
        start_time = time.time()
        transcribe_time = 0.0
        translate_time = 0.0

        try:
            # =================================================================
            # Step 1: 语音转写
            # =================================================================
            await self._report_progress(task_id, TaskStatus.TRANSCRIBING, 10)
            logger.info(f"[{task_id}] 开始转写...")

            t0 = time.time()
            asr_result = await self._transcribe(audio_path, task_config)
            transcribe_time = time.time() - t0

            if asr_result is None:
                return WorkerTaskResult(
                    task_id=task_id,
                    status="failed",
                    error="转写失败",
                )

            srt_content, detected_lang, segment_count = asr_result
            logger.info(
                f"[{task_id}] 转写完成: {segment_count} 条, "
                f"语言={detected_lang}, 耗时={transcribe_time:.1f}s"
            )

            # =================================================================
            # Step 2: LLM 断句优化 (可选)
            # =================================================================
            if task_config.optimize_enabled:
                await self._report_progress(task_id, TaskStatus.OPTIMIZING, 50)
                logger.info(f"[{task_id}] LLM 断句优化...")
                srt_content = await self._optimize(srt_content, task_config)

            # =================================================================
            # Step 3: 术语提取 + 翻译
            # =================================================================
            await self._report_progress(task_id, TaskStatus.TRANSLATING, 60)

            # 术语提取（自动或使用传入的术语表）
            glossary = task_config.glossary
            if task_config.terminology_enabled and not glossary:
                logger.info(f"[{task_id}] 自动提取术语...")
                try:
                    from worker.terminology_extractor import TerminologyExtractor
                    extractor = TerminologyExtractor(self._get_llm())
                    glossary = await extractor.extract(
                        srt_content, task_config.target_lang, task_config.media_title
                    )
                    if glossary:
                        logger.info(f"[{task_id}] 术语表: {len(glossary)} 个术语")
                    else:
                        glossary = None
                except Exception as e:
                    logger.warning(f"[{task_id}] 术语提取失败 (不影响翻译): {e}")
                    glossary = None

            logger.info(f"[{task_id}] 翻译 → {task_config.target_lang}...")
            t0 = time.time()
            translated_srt, translate_stats = await self._translate(
                srt_content, task_config, detected_lang, glossary
            )
            translate_time = time.time() - t0
            logger.info(f"[{task_id}] 翻译完成, 耗时={translate_time:.1f}s")

            # 后处理：去重 + 去结尾标点 + 去段内换行
            translated_srt = self._clean_subtitle(translated_srt)

            # 翻译完全失败 → 任务失败，触发重试
            if translated_srt is None:
                return WorkerTaskResult(
                    task_id=task_id,
                    status="failed",
                    error="翻译 API 调用失败，所有批次均未返回有效结果",
                    transcribe_duration=transcribe_time,
                    translate_duration=translate_time,
                    total_duration=time.time() - start_time,
                    segment_count=segment_count,
                )

            # =================================================================
            # Step 3.5: 字幕注释 (可选)
            # =================================================================
            annotations = None
            cultural_density = translate_stats.get("cultural_density")
            annotation_mode = task_config.annotation

            should_annotate = (
                annotation_mode == "on"
                or (annotation_mode == "auto" and cultural_density in ("high", "medium"))
            )

            if should_annotate:
                await self._report_progress(task_id, TaskStatus.ANNOTATING, 85)
                logger.info(f"[{task_id}] 生成字幕注释 (mode={annotation_mode}, density={cultural_density})...")
                try:
                    from worker.annotator import SubtitleAnnotator
                    from worker.srt_parser import SRTParser as _SRTParser

                    annotator = SubtitleAnnotator(self._get_llm())
                    orig_segments = _SRTParser.parse(srt_content)
                    trans_segments = _SRTParser.parse(translated_srt)

                    annotations = await annotator.generate_annotations(
                        original_segments=orig_segments,
                        translated_segments=trans_segments,
                        cultural_density=cultural_density or "low",
                        video_duration=0,  # Worker 无视频时长信息，由 max_notes 默认值决定
                        max_notes=0,       # 0 = 自动计算（但无 duration 时默认 3）
                    )
                    if annotations:
                        logger.info(f"[{task_id}] 生成 {len(annotations)} 条注释")
                except Exception as e:
                    logger.warning(f"[{task_id}] 注释生成失败（不影响主流程）: {e}")
                    annotations = None

            # =================================================================
            # Step 4: 后处理
            # =================================================================
            await self._report_progress(task_id, TaskStatus.ALIGNING, 90)
            final_srt = translated_srt or srt_content

            # VRAM 清理
            if self.config.vram.clear_on_complete:
                self._cleanup_vram()

            total_time = time.time() - start_time

            return WorkerTaskResult(
                task_id=task_id,
                status="completed",
                subtitle_srt=final_srt,
                detected_language=detected_lang,
                transcribe_duration=transcribe_time,
                translate_duration=translate_time,
                total_duration=total_time,
                segment_count=segment_count,
                partial_translation=translate_stats.get("partial", False),
                original_srt=srt_content,
                annotations=annotations,
                cultural_density=cultural_density,
            )

        except Exception as e:
            logger.exception(f"[{task_id}] 流水线异常: {e}")
            if self.config.vram.clear_on_complete:
                self._cleanup_vram()
            return WorkerTaskResult(
                task_id=task_id,
                status="failed",
                error=str(e),
            )
        finally:
            self.current_task_id = None
            self.current_progress = 0

    # =========================================================================
    # 转写 (faster-whisper-xxl 二进制)
    # =========================================================================

    async def _transcribe(
        self, audio_path: str, config: TaskConfig
    ) -> Optional[tuple[str, str, int]]:
        """调用 faster-whisper-xxl 二进制转写

        Returns:
            (srt_content, detected_language, segment_count) 或 None
        """
        try:
            from worker.whisper_runner import (
                ensure_whisper_binary, run_whisper, filter_hallucinations,
            )

            # 查找或自动下载二进制
            binary = ensure_whisper_binary(self.config.transcribe.whisper_binary)
            if not binary:
                return None

            # 语言设置
            language = ""
            if config.source_lang and config.source_lang != "auto":
                language = config.source_lang

            # 进度回调
            async def _progress(pct: int, msg: str):
                await self._report_progress(
                    self.current_task_id, TaskStatus.TRANSCRIBING, pct
                )

            # 用 run_in_executor 包装同步进度回调
            def sync_progress(pct: int, msg: str):
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(_progress(pct, msg))
                except RuntimeError:
                    pass

            # 输出目录（临时）
            output_dir = str(Path(self.config.temp_dir) / f"{self.current_task_id}_srt")

            # 执行转写
            srt_content, segment_count, whisper_lang = await run_whisper(
                binary=binary,
                audio_path=audio_path,
                output_dir=output_dir,
                model=self.config.transcribe.model,
                model_dir=self.config.transcribe.model_dir,
                device=self.config.transcribe.device,
                language=language,
                vad_filter=self.config.transcribe.vad_filter,
                vad_threshold=self.config.transcribe.vad_threshold,
                vad_method=self.config.transcribe.vad_method,
                compute_type=self.config.transcribe.compute_type,
                progress_callback=sync_progress,
            )

            # 幻觉过滤
            from worker.srt_parser import SRTParser
            segments = SRTParser.parse(srt_content)
            original_count = len(segments)
            segments = filter_hallucinations(segments)
            if len(segments) < original_count:
                logger.info(f"幻觉过滤: {original_count} → {len(segments)} 段")
                srt_content = SRTParser.build(segments)
                segment_count = len(segments)

            # 语言检测：优先使用 Whisper 检测结果，其次配置值
            detected_lang = whisper_lang or config.source_lang or "unknown"

            logger.info(f"转写完成: {segment_count} 段, 语言={detected_lang}")

            # 清理临时 SRT 目录
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

            return srt_content, detected_lang, segment_count

        except Exception as e:
            logger.exception(f"转写失败: {e}")
            return None

    # =========================================================================
    # 后处理
    # =========================================================================

    @staticmethod
    def _clean_subtitle(srt_content: str) -> str:
        """字幕清洗：去重 + 去结尾标点 + 去段内换行"""
        from worker.srt_parser import SRTParser

        segments = SRTParser.parse(srt_content)
        if not segments:
            return srt_content

        # 1. 去段内换行 + 去结尾标点
        punct = set("。，、；：！？,.;:!?…。")
        for seg in segments:
            text = seg.text.replace("\n", " ").strip()
            while text and text[-1] in punct:
                text = text[:-1].strip()
            # 保留纯标点文本，避免清空
            seg.text = text if text else seg.text.replace("\n", " ").strip()

        # 2. 去重（合并相同文本的段，保留最早的时间戳）
        seen = {}
        merged = []
        for seg in segments:
            if seg.text in seen:
                # 延长时间轴到最晚的结束时间
                seen[seg.text].end_time = max(seen[seg.text].end_time, seg.end_time)
            else:
                seen[seg.text] = seg
                merged.append(seg)

        # 3. 重新编号
        for i, seg in enumerate(merged, 1):
            seg.index = i

        result = SRTParser.build(merged)
        if len(merged) < len(segments):
            logger.info(f"字幕清洗: {len(segments)} → {len(merged)} 段")
        return result

    # =========================================================================
    # 优化
    # =========================================================================

    async def _optimize(self, srt_content: str, config: TaskConfig) -> str:
        """LLM 断句优化"""
        if not config.optimize_enabled or not self.config.llm_providers:
            return srt_content

        from worker.optimizer import SubtitleOptimizer

        llm = self._get_llm()
        optimizer = SubtitleOptimizer(llm)
        return await optimizer.optimize(srt_content, config, self.config.optimize)

    # =========================================================================
    # 翻译 
    # =========================================================================

    async def _translate(
        self, srt_content: str, config: TaskConfig, source_lang: str,
        glossary: Optional[dict[str, str]] = None,
    ) -> tuple[Optional[str], dict]:
        """翻译字幕

        Args:
            srt_content: SRT 字幕内容
            config: 任务配置
            source_lang: 源语言代码
            glossary: 术语表 {原文: 译文}

        Returns:
            (translated_srt, stats) 元组
        """
        empty_stats = {"translated_count": 0, "total_count": 0, "partial": False}

        if source_lang == config.target_lang:
            logger.info("源语言与目标语言相同，跳过翻译")
            return srt_content, empty_stats

        if config.translate_service != "llm" or not self.config.llm_providers:
            logger.warning("未启用 LLM 翻译服务或缺少 LLM 提供商，跳过翻译")
            return srt_content, empty_stats

        from worker.translator import SubtitleTranslator

        llm = self._get_llm()
        translator = SubtitleTranslator(llm)
        return await translator.translate(srt_content, config, source_lang, glossary)

    # =========================================================================
    # VRAM 管理
    # =========================================================================

    def _cleanup_vram(self):
        """清理资源（faster-whisper-xxl 二进制自行管理 VRAM）"""
        import gc
        gc.collect()
        logger.debug("资源已清理")

    # =========================================================================
    # 进度回报
    # =========================================================================

    async def _report_progress(self, task_id: str, status: str, progress: int):
        """向 Coordinator 报告进度"""
        self.current_progress = progress

        if not self.config.coordinator_url:
            return

        try:
            update = WorkerProgressUpdate(
                task_id=task_id,
                status=status,
                progress=progress,
            )
            if self._http is None or self._http.is_closed:
                self._http = httpx.AsyncClient(timeout=5)
            await self._http.post(
                f"{self.config.coordinator_url}/api/progress",
                json=update.model_dump(),
            )
        except Exception:
            pass  # 进度报告失败不影响主流程
