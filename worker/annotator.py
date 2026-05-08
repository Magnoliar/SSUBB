"""SSUBB Worker - 字幕注释生成器

基于翻译内容识别需要文化注释的片段，生成类似字幕组的翻译备注。
"""

import json
import logging
from typing import List, Optional

from worker.llm_client import LLMClient
from worker.srt_parser import SubtitleSegment

logger = logging.getLogger("ssubb.annotator")

ANNOTATE_SYSTEM_PROMPT = """You are a cultural annotation expert for subtitle translation.
Given original subtitles and their translations, identify segments that contain culturally-specific
references requiring explanation for a Chinese-speaking audience.

You MUST output ONLY a valid JSON list of annotation objects, each with:
- "index": the subtitle index number (matching the input)
- "text": concise annotation in Chinese (max 30 characters)

Only annotate when ABSOLUTELY NECESSARY:
1. Wordplay, puns, or double meanings that are lost in translation
2. Cultural references/historical context needed to understand the scene
3. Untranslated proper nouns that need explanation for Chinese viewers

DO NOT annotate:
- Things the audience can infer from context
- Obvious cultural differences (bowing, honorifics, etc.)
- Trivial facts or "fun facts" that don't enhance understanding
- Anything already clear from the translation

Be RUTHLESSLY selective. Quality over quantity.
If no annotations are truly needed, output an empty list [].

Max annotations allowed: {max_notes}
Each annotation text must be ≤30 Chinese characters."""


class SubtitleAnnotator:
    """字幕注释生成器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def generate_annotations(
        self,
        original_segments: List[SubtitleSegment],
        translated_segments: List[SubtitleSegment],
        cultural_density: str,
        video_duration: float,
        max_notes: int,
    ) -> Optional[list[dict]]:
        """生成注释列表

        Args:
            original_segments: 原始字幕段（翻译前）
            translated_segments: 翻译后字幕段
            cultural_density: 文化密度信号 (high/medium/low)
            video_duration: 视频时长（秒）
            max_notes: 最大注释数

        Returns:
            注释列表 [{index, text, start_time, end_time}] 或 None
        """
        if not original_segments or not translated_segments:
            return None

        if max_notes <= 0:
            max_notes = self._calculate_max_notes(video_duration)

        # 构建输入：每段的原文 + 译文
        input_data = []
        for orig, trans in zip(original_segments, translated_segments):
            input_data.append({
                "index": orig.index,
                "original": orig.text,
                "translated": trans.text,
            })

        system_prompt = ANNOTATE_SYSTEM_PROMPT.format(max_notes=max_notes)
        user_prompt = (
            f"Cultural density: {cultural_density}\n"
            f"Max annotations: {max_notes}\n\n"
            f"Subtitle pairs (original → translated):\n"
            f"{json.dumps(input_data, ensure_ascii=False, indent=1)}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            # 单次 LLM 调用：生成 + 自筛选
            result = await self.llm.call_with_json_validation(
                messages=messages,
                max_retries=2,
            )

            if not result or not isinstance(result, list):
                logger.info("LLM 未返回有效注释列表")
                return None

            # 后处理：过滤、限数、补全时间码
            annotations = self._process_annotations(
                result, translated_segments, max_notes
            )

            if annotations:
                logger.info(f"生成 {len(annotations)} 条注释")
            else:
                logger.info("经筛选后无有效注释")

            return annotations if annotations else None

        except Exception as e:
            logger.warning(f"注释生成失败（不影响主流程）: {e}")
            return None

    def _calculate_max_notes(self, video_duration: float) -> int:
        """根据视频时长计算最大注释数"""
        if video_duration <= 1800:      # ≤30 分钟
            return 2
        elif video_duration <= 5400:    # 30-90 分钟
            return 5
        elif video_duration <= 9000:    # 90-150 分钟
            return 8
        else:                           # >150 分钟
            return 10

    def _process_annotations(
        self,
        raw_annotations: list,
        segments: List[SubtitleSegment],
        max_notes: int,
    ) -> Optional[list[dict]]:
        """后处理注释列表

        - 验证 index 有效性
        - 截断超长文本
        - 补全时间码
        - 限制数量
        - 保证不重叠（间隔 ≥2s）
        """
        # 建立 index → segment 映射
        seg_map = {seg.index: seg for seg in segments}

        valid = []
        for ann in raw_annotations:
            if not isinstance(ann, dict):
                continue

            idx = ann.get("index")
            text = ann.get("text", "").strip()

            if not idx or not text:
                continue
            if idx not in seg_map:
                continue

            # 截断超长文本
            if len(text) > 30:
                text = text[:30]

            seg = seg_map[idx]
            valid.append({
                "index": idx,
                "text": text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
            })

        if not valid:
            return None

        # 按 index 排序
        valid.sort(key=lambda a: a["index"])

        # 限制数量（取前 max_notes 条）
        if len(valid) > max_notes:
            valid = valid[:max_notes]

        # 保证不重叠：相邻注释间隔 ≥2 秒
        filtered = [valid[0]]
        for ann in valid[1:]:
            prev_end = self._time_to_seconds(filtered[-1]["end_time"])
            curr_start = self._time_to_seconds(ann["start_time"])
            if curr_start - prev_end >= 2.0:
                filtered.append(ann)
            # 如果间隔太短，跳过这条（宁缺毋滥）

        return filtered if filtered else None

    @staticmethod
    def _time_to_seconds(time_str: str) -> float:
        """SRT 时间码转秒数 (HH:MM:SS,mmm)"""
        try:
            time_str = time_str.replace(",", ".")
            parts = time_str.split(":")
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        except (ValueError, IndexError):
            return 0.0
