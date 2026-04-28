"""SSUBB Worker - LLM 翻译器

将 SRT 文本内容按批次翻译为目标语言。
"""

import asyncio
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
    ) -> Optional[str]:
        """将 SRT 内容翻译为目标语言"""
        if source_lang == config.target_lang:
            logger.info("源语言与目标语言相同，跳过翻译")
            return srt_content

        target_lang_name = self._get_language_name(config.target_lang)
        logger.info(f"开始翻译: {source_lang} -> {target_lang_name}")

        # 1. 解析 SRT
        segments = SRTParser.parse(srt_content)
        if not segments:
            logger.warning("未能从 SRT 解析出分段")
            return srt_content

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

        # 4. 组装结果
        final_segments = []
        for i, batch_result in enumerate(results):
            if isinstance(batch_result, Exception):
                logger.error(f"批次 {i+1} 翻译异常: {batch_result}，保留原文")
                final_segments.extend(batches[i])
            else:
                final_segments.extend(batch_result)

        # 5. 重建 SRT
        return SRTParser.build(final_segments)

    async def _translate_chunk(
        self, chunk: List[SubtitleSegment], target_lang: str
    ) -> List[SubtitleSegment]:
        """翻译单批次"""
        if not chunk:
            return chunk

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
        if result_dict:
            for seg in chunk:
                key = str(seg.index)
                if key in result_dict:
                    seg.text = result_dict[key]
        else:
            logger.warning(f"批次翻译失败，保留原文 (keys: {list(expected_keys)[0]}...)")

        return chunk

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
        }
        return lang_map.get(code, code)
