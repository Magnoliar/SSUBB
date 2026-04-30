"""SSUBB Worker - LLM 翻译器

将 SRT 文本内容按批次翻译为目标语言。
"""

import asyncio
import json
import logging
from typing import List, Optional

from shared.models import TaskConfig
from .llm_client import LLMClient
from .srt_parser import SRTParser, SubtitleSegment

logger = logging.getLogger("ssubb.translator")

# 翻译 System Prompt
TRANSLATE_SYSTEM_PROMPT = """You are a professional subtitle translator.
Your task is to translate the given subtitle texts into the target language.
You will receive a JSON dictionary where the key is the index and the value is the subtitle text.
You MUST output ONLY a valid JSON dictionary mapping the exact same keys to their translated texts.

Guidelines:
1. Translate accurately and natively, keeping the context in mind.
2. If a subtitle is very short (e.g. "Oh", "Wait"), translate it contextually.
3. Keep the translation concise, suitable for on-screen reading.
4. Do NOT translate proper nouns unless they have well-established translations.
5. NEVER merge or delete keys. Your output MUST have exactly the same keys as the input.
6. The output must be pure JSON, without any markdown formatting like ```json.
"""


class SubtitleTranslator:
    """字幕翻译器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def translate(
        self,
        srt_content: str,
        config: TaskConfig,
        source_lang: str,
    ) -> tuple[Optional[str], dict]:
        """将 SRT 内容翻译为目标语言

        Returns:
            (translated_srt, stats) 元组，stats 包含 translated_count / total_count / partial 标记
        """
        stats = {"translated_count": 0, "total_count": 0, "partial": False}

        if source_lang == config.target_lang:
            logger.info("源语言与目标语言相同，跳过翻译")
            return srt_content, stats

        target_lang_name = self._get_language_name(config.target_lang)
        logger.info(f"开始翻译: {source_lang} -> {target_lang_name}")

        # 1. 解析 SRT
        segments = SRTParser.parse(srt_content)
        if not segments:
            logger.warning("未能从 SRT 解析出分段")
            return srt_content, stats

        stats["total_count"] = len(segments)

        # 2. 分批
        batch_size = config.translate_batch_size
        batches = [
            segments[i : i + batch_size]
            for i in range(0, len(segments), batch_size)
        ]

        # 3. 并发翻译
        semaphore = asyncio.Semaphore(config.translate_thread_num)

        async def _translate_batch(batch: List[SubtitleSegment]):
            async with semaphore:
                return await self._translate_chunk(batch, target_lang_name)

        tasks = [_translate_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 组装结果，统计翻译成功数
        final_segments = []
        for i, batch_result in enumerate(results):
            if isinstance(batch_result, Exception):
                logger.error(f"批次 {i+1} 翻译异常: {batch_result}，保留原文")
                final_segments.extend(batches[i])
            else:
                segs, count = batch_result
                final_segments.extend(segs)
                stats["translated_count"] += count

        # 5. 检查是否全部翻译失败
        if stats["translated_count"] == 0 and stats["total_count"] > 0:
            logger.error("所有批次翻译均失败，返回原文")
            return None, stats

        # 部分失败标记
        if stats["translated_count"] < stats["total_count"]:
            stats["partial"] = True
            logger.warning(
                f"部分翻译失败: {stats['translated_count']}/{stats['total_count']} 条成功"
            )

        # 6. 反思翻译 (可选)
        if config.need_reflect and stats["translated_count"] > 0:
            logger.info("开始反思翻译 (二次审校)...")
            final_segments = await self._reflect_batch(
                segments, final_segments, target_lang_name
            )

        # 7. 重建 SRT
        return SRTParser.build(final_segments), stats

    async def _translate_chunk(
        self, chunk: List[SubtitleSegment], target_lang: str
    ) -> tuple[List[SubtitleSegment], int]:
        """翻译单批次

        Returns:
            (segments, translated_count) 元组
        """
        if not chunk:
            return chunk, 0

        # 构建输入 JSON字典
        input_dict = {str(seg.index): seg.text for seg in chunk}
        expected_keys = set(input_dict.keys())

        user_prompt = f"Target Language: {target_lang}\n\nSubtitles to translate:\n{input_dict}"

        messages = [
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 调用 LLM API
        result_dict = await self.llm.call_with_json_validation(
            messages=messages,
            expected_keys=expected_keys,
            max_retries=3,
        )

        # 将翻译结果应用回 chunk
        translated_count = 0
        if result_dict:
            for seg in chunk:
                key = str(seg.index)
                if key in result_dict:
                    seg.text = result_dict[key]
                    translated_count += 1
        else:
            logger.warning(f"批次翻译失败，保留原文 (keys: {list(expected_keys)[0]}...)")

        return chunk, translated_count

    async def _reflect_batch(
        self,
        originals: list,
        translated: list,
        target_lang: str,
    ) -> list:
        """反思翻译：将原文和译文送回 LLM 做二次审校"""
        from .srt_parser import SubtitleSegment

        REFLECT_SYSTEM_PROMPT = """You are a professional translation reviewer.
Compare the original subtitles with the translated subtitles and improve the translation.
Check for: 1) omissions or additions, 2) terminology consistency, 3) natural fluency, 4) accuracy per time slot.
Output ONLY a valid JSON dictionary mapping each index to the improved translation.
Keep the EXACT same keys as the translated subtitles input."""

        # 按批次审校（每批 10 条）
        batch_size = 10
        for i in range(0, len(translated), batch_size):
            orig_batch = originals[i : i + batch_size]
            trans_batch = translated[i : i + batch_size]

            input_lines = {}
            for orig_seg, trans_seg in zip(orig_batch, trans_batch):
                idx = str(orig_seg.index)
                input_lines[idx] = {
                    "original": orig_seg.text,
                    "translated": trans_seg.text,
                }

            expected_keys = set(input_lines.keys())
            user_prompt = (
                f"Target Language: {target_lang}\n\n"
                f"Review and improve these translations:\n"
                f"{json.dumps(input_lines, ensure_ascii=False, indent=2)}"
            )

            messages = [
                {"role": "system", "content": REFLECT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            result_dict = await self.llm.call_with_json_validation(
                messages=messages,
                expected_keys=expected_keys,
                max_retries=2,
            )

            if result_dict:
                for seg in trans_batch:
                    key = str(seg.index)
                    if key in result_dict:
                        seg.text = result_dict[key]

        return translated

    @staticmethod
    def _get_language_name(code: str) -> str:
        lang_map = {
            "zh": "Simplified Chinese",
            "en": "English",
            "ja": "Japanese",
            "fr": "French",
            "de": "German",
            "ko": "Korean",
            "es": "Spanish",
            "ru": "Russian",
            "pt": "Portuguese",
            "it": "Italian",
            "ar": "Arabic",
            "th": "Thai",
            "vi": "Vietnamese",
        }
        return lang_map.get(code, code)
