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
            translated_srt = await self._translate(
                srt_content, task_config, detected_lang
            )
            translate_time = time.time() - t0
            logger.info(f"[{task_id}] 翻译完成, 耗时={translate_time:.1f}s")

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

    async def _transcribe(
        self, audio_path: str, config: TaskConfig
    ) -> Optional[tuple[str, str, int]]:
        """调用 faster-whisper 转写

        Returns:
            (srt_content, detected_language, segment_count) 或 None
        """
        try:
            import stable_whisper

            model_path = self.config.transcribe.model
            model_dir = self.config.transcribe.model_dir
            device = self.config.transcribe.device
            compute_type = self.config.transcribe.compute_type

            logger.info(f"加载模型: {model_path} (device={device}, compute={compute_type})")

            model = stable_whisper.load_faster_whisper(
                model_path,
                device=device,
                compute_type=compute_type,
                download_root=model_dir,
            )

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
        if not config.optimize_enabled or not self.config.llm.api_key:
            return srt_content
            
        from .llm_client import LLMClient
        from .optimizer import SubtitleOptimizer
        
        llm = LLMClient(self.config.llm)
        optimizer = SubtitleOptimizer(llm)
        return await optimizer.optimize(srt_content, config)

    # =========================================================================
    # 翻译 
    # =========================================================================

    async def _translate(
        self, srt_content: str, config: TaskConfig, source_lang: str
    ) -> Optional[str]:
        """翻译字幕"""
        if source_lang == config.target_lang:
            logger.info("源语言与目标语言相同，跳过翻译")
            return srt_content

        if config.translate_service != "llm" or not self.config.llm.api_key:
            logger.warning("未启用 LLM 翻译服务或缺少 API_KEY，跳过翻译")
            return srt_content
            
        from .llm_client import LLMClient
        from .translator import SubtitleTranslator
        
        # 组合 LLM Config (支持复写)
        llm_config = self.config.llm
        
        llm = LLMClient(llm_config)
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
