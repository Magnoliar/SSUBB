"""SSUBB Worker - 字幕解析器

简单的 SRT 解析和重构工具。
"""

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SubtitleSegment:
    index: int
    start_time: str
    end_time: str
    text: str


class SRTParser:
    """SRT 文件解析器"""

    @staticmethod
    def parse(srt_content: str) -> List[SubtitleSegment]:
        """将 SRT 文本解析为 Segment 列表"""
        blocks = re.split(r"\n\s*\n", srt_content.strip())
        
        # 支持点和逗号作为毫秒分隔符
        time_pattern = re.compile(
            r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
        )

        segments = []
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # 寻找时间行
            time_match = None
            text_start = 1
            for i, line in enumerate(lines):
                m = time_pattern.search(line)
                if m:
                    time_match = m
                    # 通常前一行是索引
                    index_str = lines[i-1].strip() if i > 0 else str(len(segments) + 1)
                    index = int(index_str) if index_str.isdigit() else len(segments) + 1
                    text_start = i + 1
                    break

            if not time_match:
                continue

            start_time, end_time = time_match.groups()
            # 强制统一为逗号分隔
            start_time = start_time.replace(".", ",")
            end_time = end_time.replace(".", ",")
            
            text = "\n".join(lines[text_start:]).strip()
            
            if text:
                segments.append(
                    SubtitleSegment(
                        index=index,
                        start_time=start_time,
                        end_time=end_time,
                        text=text
                    )
                )

        return segments

    @staticmethod
    def build(segments: List[SubtitleSegment]) -> str:
        """从 Segment 列表重建 SRT 文本"""
        blocks = []
        for i, seg in enumerate(segments, 1):
            # 重新分配连续的索引
            blocks.append(
                f"{i}\n"
                f"{seg.start_time} --> {seg.end_time}\n"
                f"{seg.text}"
            )
        return "\n\n".join(blocks) + "\n"
