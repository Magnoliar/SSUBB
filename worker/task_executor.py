"""SSUBB Worker - 任务执行流水线

编排: 转写 → 优化 → 翻译 → 对轴 → 回调。
"""

import gc
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from shared.constants import TaskStatus
from shared.models import TaskConfig, WorkerProgressUpdate, WorkerTaskResult

from .config import WorkerConfig

logger = logging.getLogger("ssubb.executor")


class TaskExecutor:
    """任务流水线执行器"""

    # 模块级 Whisper 模型缓存 (避免每个任务重新加载)
    _cached_model = None
    _cached_model_key: str = ""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.current_task_id: Optional[str] = None
        self.current_progress: int = 0

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
            # Step 3: 翻译
            # =================================================================
            await self._report_progress(task_id, TaskStatus.TRANSLATING, 60)
            logger.info(f"[{task_id}] 翻译 → {task_config.target_lang}...")

            t0 = time.time()
            translated_srt, translate_stats = await self._translate(
                srt_content, task_config, detected_lang
            )
            translate_time = time.time() - t0
            logger.info(f"[{task_id}] 翻译完成, 耗时={translate_time:.1f}s")

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
    # 转写
    # =========================================================================

    def _get_whisper_model(self):
        """获取或创建缓存的 Whisper 模型 (单例)"""
        import stable_whisper

        model_path = self.config.transcribe.model
        device = self.config.transcribe.device
        compute_type = self.config.transcribe.compute_type
        model_dir = self.config.transcribe.model_dir

        # 缓存 key: 模型名 + 设备 + 精度
        model_key = f"{model_path}|{device}|{compute_type}"

        if TaskExecutor._cached_model is not None and TaskExecutor._cached_model_key == model_key:
            logger.debug("复用缓存的 Whisper 模型")
            return TaskExecutor._cached_model

        logger.info(f"加载 Whisper 模型: {model_path} (device={device}, compute={compute_type})")
        model = stable_whisper.load_faster_whisper(
            model_path,
            device=device,
            compute_type=compute_type,
            download_root=model_dir,
        )
        TaskExecutor._cached_model = model
        TaskExecutor._cached_model_key = model_key
        logger.info("Whisper 模型已缓存，后续任务将复用")
        return model

    async def _transcribe(
        self, audio_path: str, config: TaskConfig
    ) -> Optional[tuple[str, str, int]]:
        """调用 faster-whisper 转写

        Returns:
            (srt_content, detected_language, segment_count) 或 None
        """
        try:
            model = self._get_whisper_model()

            # 构建转写参数
            transcribe_args = {
                "audio": audio_path,
                "verbose": None,
            }

            # 语言设置
            if config.source_lang and config.source_lang != "auto":
                transcribe_args["language"] = config.source_lang

            # VAD
            if self.config.transcribe.vad_filter:
                transcribe_args["vad_filter"] = True

            # 自定义 regroup
            regroup = self.config.transcribe.custom_regroup
            if regroup and regroup.lower() != "default":
                transcribe_args["regroup"] = regroup

            # 转写
            result = model.transcribe(**transcribe_args)

            # 获取检测到的语言
            detected_lang = getattr(result, "language", config.source_lang or "unknown")

            # 导出为 SRT
            srt_content = result.to_srt_vtt(filepath=None)

            # 统计段数
            segment_count = len(result.segments) if hasattr(result, "segments") else 0

            return srt_content, detected_lang, segment_count

        except Exception as e:
            logger.exception(f"转写失败: {e}")
            return None

    # =========================================================================
    # 优化 
    # =========================================================================

    async def _optimize(self, srt_content: str, config: TaskConfig) -> str:
        """LLM 断句优化"""
        if not config.optimize_enabled or not self.config.llm_providers:
            return srt_content

        from .llm_client import LLMClient
        from .optimizer import SubtitleOptimizer

        llm = LLMClient(self.config.llm_providers)
        optimizer = SubtitleOptimizer(llm)
        return await optimizer.optimize(srt_content, config, self.config.optimize)

    # =========================================================================
    # 翻译 
    # =========================================================================

    async def _translate(
        self, srt_content: str, config: TaskConfig, source_lang: str
    ) -> tuple[Optional[str], dict]:
        """翻译字幕

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

        from .llm_client import LLMClient
        from .translator import SubtitleTranslator

        llm = LLMClient(self.config.llm_providers)
        translator = SubtitleTranslator(llm)
        return await translator.translate(srt_content, config, source_lang)

    # =========================================================================
    # VRAM 管理
    # =========================================================================

    def _cleanup_vram(self):
        """清理 GPU VRAM"""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            logger.debug("VRAM 已清理")
        except ImportError:
            gc.collect()

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
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{self.config.coordinator_url}/api/progress",
                    json=update.model_dump(),
                )
        except Exception:
            pass  # 进度报告失败不影响主流程
