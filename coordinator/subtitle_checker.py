"""SSUBB Coordinator - 字幕质量验证器

检查已有字幕是否可用（时长匹配、密度、语言等），
解决 Emby 刮削字幕对不上的问题。
"""

import logging
import re
from pathlib import Path
from typing import Optional

from shared.constants import SUBTITLE_EXTENSIONS, ZH_SUBTITLE_TAGS

logger = logging.getLogger("ssubb.checker")


class SubtitleChecker:
    """字幕质量验证器"""

    def __init__(
        self,
        min_coverage: float = 0.7,
        min_density: float = 2.0,
        check_language: bool = True,
    ):
        self.min_coverage = min_coverage
        self.min_density = min_density
        self.check_language = check_language

    def should_process(
        self,
        video_path: str,
        target_lang: str = "zh",
        force: bool = False,
        video_duration: Optional[float] = None,
    ) -> tuple[bool, str]:
        """判断是否需要处理该视频

        Args:
            video_path: 视频文件路径
            target_lang: 目标语言
            force: 强制模式
            video_duration: 视频时长 (秒)，未提供则不做时长检查

        Returns:
            (should_process: bool, reason: str)
        """
        if force:
            return True, "强制重新生成"

        # 查找目标语言字幕
        subtitle_path = self.find_subtitle(video_path, target_lang)
        if subtitle_path is None:
            return True, f"未找到 {target_lang} 字幕"

        # 质量检查
        is_valid, reason = self.check_quality(subtitle_path, video_duration)
        if not is_valid:
            return True, f"字幕质量不合格: {reason}"

        return False, f"已有合格字幕: {Path(subtitle_path).name}"

    def find_subtitle(self, video_path: str, target_lang: str = "zh") -> Optional[str]:
        """查找视频对应的目标语言字幕文件

        搜索逻辑:
        1. {video_name}.zh.srt / {video_name}.chi.srt 等
        2. {video_name}.srt (无语言标记，检查内容)
        """
        video = Path(video_path)
        video_stem = video.stem
        video_dir = video.parent

        if not video_dir.is_dir():
            return None

        lang_tags = ZH_SUBTITLE_TAGS if target_lang == "zh" else {target_lang}

        # 1. 精确匹配: video_name.{lang_tag}.{ext}
        for ext in SUBTITLE_EXTENSIONS:
            for tag in lang_tags:
                candidate = video_dir / f"{video_stem}.{tag}{ext}"
                if candidate.is_file():
                    logger.debug(f"找到字幕: {candidate.name}")
                    return str(candidate)

        # 2. 模糊匹配: 同名无语言标记 (仅 .srt)
        plain_srt = video_dir / f"{video_stem}.srt"
        if plain_srt.is_file():
            logger.debug(f"找到无标记字幕: {plain_srt.name}")
            return str(plain_srt)

        return None

    def check_quality(
        self,
        subtitle_path: str,
        video_duration: Optional[float] = None,
    ) -> tuple[bool, str]:
        """检查字幕文件质量

        Returns:
            (is_valid: bool, reason: str)
        """
        sub_path = Path(subtitle_path)

        # 0. 文件大小检查
        try:
            file_size = sub_path.stat().st_size
            if file_size < 100:
                return False, f"字幕文件过小 ({file_size} bytes)，可能已损坏"
        except OSError:
            return False, "字幕文件不可读"

        # 1. 基础: 文件可读
        try:
            subs = self._parse_srt(subtitle_path)
        except Exception as e:
            return False, f"字幕解析失败: {e}"

        if not subs:
            return False, "字幕文件为空"

        # 2. 条目数量检查
        if len(subs) < 5:
            return False, f"字幕条目过少 ({len(subs)} 条)"

        # 3. 时长覆盖率检查
        if video_duration and video_duration > 0:
            last_end = max(s["end"] for s in subs)
            coverage = last_end / video_duration
            if coverage < self.min_coverage:
                return False, f"时长覆盖率 {coverage:.0%} < {self.min_coverage:.0%}"

            # 4. 密度检查
            density = len(subs) / (video_duration / 60)
            if density < self.min_density:
                return False, f"密度 {density:.1f}条/分 < {self.min_density}条/分"

        # 5. 时间连续性检查 (检测大段空白)
        if len(subs) >= 10:
            max_gap = 0
            for i in range(1, len(subs)):
                gap = subs[i]["start"] - subs[i - 1]["end"]
                max_gap = max(max_gap, gap)
            if max_gap > 300:  # 超过 5 分钟的空白
                return False, f"字幕存在 {max_gap:.0f}s 空白段，可能不完整"

        # 6. 语言内容检查 (简易: 检测 CJK 字符占比)
        if self.check_language:
            all_text = " ".join(s["text"] for s in subs)
            if all_text:
                cjk_count = sum(1 for c in all_text if self._is_cjk(c))
                cjk_ratio = cjk_count / max(len(all_text), 1)
                if cjk_ratio < 0.1:  # 中文字幕应有至少 10% CJK 字符
                    return False, f"CJK 字符占比 {cjk_ratio:.0%}，可能非中文字幕"

        return True, "字幕正常"

    # =========================================================================
    # SRT 解析
    # =========================================================================

    @staticmethod
    def _parse_srt(path: str) -> list[dict]:
        """解析 SRT 文件，返回 [{index, start, end, text}, ...]"""
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"]
        content = None
        for enc in encodings:
            try:
                content = Path(path).read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if content is None:
            raise ValueError(f"无法解码字幕文件: {path}")

        subs = []
        # SRT 格式: 索引 \n 时间码 \n 内容 \n\n
        blocks = re.split(r"\n\s*\n", content.strip())
        time_pattern = re.compile(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
        )

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # 查找时间码行
            time_match = None
            text_start = 0
            for i, line in enumerate(lines):
                m = time_pattern.search(line)
                if m:
                    time_match = m
                    text_start = i + 1
                    break

            if time_match is None:
                continue

            h1, m1, s1, ms1, h2, m2, s2, ms2 = time_match.groups()
            start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000
            end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000
            text = " ".join(lines[text_start:]).strip()

            if text:  # 跳过空文本
                subs.append({"start": start, "end": end, "text": text})

        return subs

    @staticmethod
    def _is_cjk(char: str) -> bool:
        """判断字符是否为 CJK 统一汉字"""
        cp = ord(char)
        return (
            (0x4E00 <= cp <= 0x9FFF) or      # CJK 基本
            (0x3400 <= cp <= 0x4DBF) or      # CJK 扩展 A
            (0x20000 <= cp <= 0x2A6DF) or    # CJK 扩展 B
            (0xF900 <= cp <= 0xFAFF) or      # CJK 兼容
            (0x2F800 <= cp <= 0x2FA1F)       # CJK 兼容补充
        )
