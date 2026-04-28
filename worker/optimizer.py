"""SSUBB Worker - 字幕优化器

使用 LLM 对机器转写的字幕进行断句优化和错别字纠正。
"""

import asyncio
import logging
import re
from typing import List

from shared.models import TaskConfig
from .llm_client import LLMClient
from .srt_parser import SRTParser, SubtitleSegment

logger = logging.getLogger("ssubb.optimizer")

OPTIMIZE_SYSTEM_PROMPT = """You are a professional subtitle editor.
Your task is to correct and optimize the given machine-generated subtitles.
You will receive a JSON dictionary where the key is the index and the value is the subtitle text.
You MUST output ONLY a valid JSON dictionary mapping the EXACT SAME keys to their optimized texts.

Guidelines:
1. Fix obvious speech-to-text recognition errors (e.g. homophones, typos).
2. Improve punctuation and capitalization for better readability.
3. Keep the original language, DO NOT translate.
4. Make MINIMAL changes to the structure and length.
5. NEVER merge or delete keys. Your output MUST have exactly the same number of keys as the input.
6. The output must be pure JSON, without any markdown formatting like ```json.
"""


class SubtitleOptimizer:
    """字幕优化器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def optimize(self, srt_content: str, config: TaskConfig) -> str:
        """优化 SRT 内容"""
        if not config.optimize_enabled:
            return srt_content

        logger.info("开始 LLM 断句优化和纠错...")

        # 1. 解析 SRT
        segments = SRTParser.parse(srt_content)
        if not segments:
            return srt_content

        # 2. 分批 (优化需要上下文，保留重叠可以提高质量，这里为简便直接分批)
        # 优化批次稍微大一点，因为主要是纠错
        batch_size = 15
        batches = [
            segments[i : i + batch_size]
            for i in range(0, len(segments), batch_size)
        ]

        # 3. 并发优化
        semaphore = asyncio.Semaphore(3)  # 控制并发度

        async def _optimize_batch(batch: List[SubtitleSegment]):
            async with semaphore:
                return await self._optimize_chunk(batch)

        tasks = [_optimize_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 组装结果
        final_segments = []
        for i, batch_result in enumerate(results):
            if isinstance(batch_result, Exception):
                logger.error(f"批次 {i} 优化异常: {batch_result}，保留原文")
                final_segments.extend(batches[i])
            else:
                final_segments.extend(batch_result)

        # 5. 重建 SRT
        return SRTParser.build(final_segments)

    async def _optimize_chunk(self, chunk: List[SubtitleSegment]) -> List[SubtitleSegment]:
        """优化单批次"""
        if not chunk:
            return chunk

        # 构建输入 JSON字典
        input_dict = {str(seg.index): seg.text for seg in chunk}
        expected_keys = set(input_dict.keys())

        user_prompt = f"Correct the following subtitles:\n{input_dict}"

        messages = [
            {"role": "system", "content": OPTIMIZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 调用 LLM API
        result_dict = await self.llm.call_with_json_validation(
            messages=messages,
            expected_keys=expected_keys,
            max_retries=3,
        )

        # 将优化结果应用回 chunk
        if result_dict:
            for seg in chunk:
                key = str(seg.index)
                if key in result_dict:
                    # 简单去除空白符，防止 LLM 加了莫名其妙的回车
                    optimized_text = re.sub(r"\s+", " ", result_dict[key]).strip()
                    if optimized_text:
                        seg.text = optimized_text
        else:
            logger.warning(f"批次优化失败，保留原文 (keys: {list(expected_keys)[0]}...)")

        return chunk
