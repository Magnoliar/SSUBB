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
        suffix = sub_path.suffix.lower()
        if suffix in (".ass", ".ssa"):
            # ASS/SSA 格式：仅做文件大小和行数检查，不做 SRT 解析
            try:
                content = sub_path.read_text(encoding="utf-8", errors="replace")
                line_count = content.count("\n")
                if line_count < 10:
                    return False, f"ASS 字幕行数过少 ({line_count} 行)"
                return True, "ASS 字幕文件正常"
            except Exception as e:
                return False, f"ASS 字幕读取失败: {e}"

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

    # =========================================================================
    # 质量评分
    # =========================================================================

    def score_subtitle(self, subtitle_content: str, video_duration: float) -> dict:
        """对生成的字幕进行质量评分 (0-100)

        评分维度:
        - 覆盖率 (30分): 字幕时间覆盖视频时长的比例
        - 密度 (20分): 每分钟字幕条数
        - 行长合理性 (20分): 过长/过短行的比例
        - 时间连续性 (15分): 相邻字幕间隔是否合理
        - 内容质量 (15分): 空白行、重复行检测

        Returns:
            {"score": 85, "grade": "B", "details": {...}, "issues": [...]}
        """
        issues = []
        details = {}

        # 解析 SRT
        try:
            subs = self._parse_srt_content(subtitle_content)
        except Exception as e:
            return {"score": 0, "grade": "F", "details": {}, "issues": [f"解析失败: {e}"]}

        if not subs:
            return {"score": 0, "grade": "F", "details": {}, "issues": ["字幕为空"]}

        total_score = 0

        # 1. 覆盖率 (30分)
        if video_duration and video_duration > 0:
            last_end = max(s["end"] for s in subs)
            coverage = min(1.0, last_end / video_duration)
            cov_score = round(coverage * 30)
            total_score += cov_score
            details["coverage"] = f"{coverage:.0%} ({cov_score}/30)"
            if coverage < 0.5:
                issues.append(f"覆盖率过低: {coverage:.0%}")
        else:
            total_score += 20  # 无视频时长，给默认分
            details["coverage"] = "N/A (20/30)"

        # 2. 密度 (20分)
        if video_duration and video_duration > 0:
            density = len(subs) / (video_duration / 60)
            # 理想密度: 3-15 条/分钟
            if 3 <= density <= 15:
                density_score = 20
            elif 2 <= density < 3 or 15 < density <= 20:
                density_score = 15
            elif 1 <= density < 2 or 20 < density <= 30:
                density_score = 10
            else:
                density_score = 5
            total_score += density_score
            details["density"] = f"{density:.1f}条/分 ({density_score}/20)"
            if density < 1:
                issues.append(f"密度过低: {density:.1f}条/分")
        else:
            total_score += 12
            details["density"] = "N/A (12/20)"

        # 3. 行长合理性 (20分)
        long_lines = sum(1 for s in subs if len(s["text"]) > 50)
        short_lines = sum(1 for s in subs if len(s["text"]) < 3)
        bad_ratio = (long_lines + short_lines) / max(len(subs), 1)
        length_score = round(max(0, 20 * (1 - bad_ratio * 2)))
        total_score += length_score
        details["line_length"] = f"异常行{bad_ratio:.0%} ({length_score}/20)"
        if bad_ratio > 0.3:
            issues.append(f"异常行长占比过高: {bad_ratio:.0%}")

        # 4. 时间连续性 (15分)
        if len(subs) >= 2:
            gaps = []
            overlaps = 0
            for i in range(1, len(subs)):
                gap = subs[i]["start"] - subs[i - 1]["end"]
                gaps.append(gap)
                if gap < -0.5:
                    overlaps += 1

            avg_gap = sum(gaps) / len(gaps) if gaps else 0
            max_gap = max(gaps) if gaps else 0

            if max_gap < 60 and overlaps == 0:
                cont_score = 15
            elif max_gap < 120 and overlaps <= 2:
                cont_score = 10
            else:
                cont_score = 5
            total_score += cont_score
            details["continuity"] = f"最大间隔{max_gap:.0f}s, {overlaps}处重叠 ({cont_score}/15)"
            if max_gap > 120:
                issues.append(f"存在{max_gap:.0f}s的长间隔")
        else:
            total_score += 10
            details["continuity"] = "N/A (10/15)"

        # 5. 内容质量 (15分)
        empty_lines = sum(1 for s in subs if not s["text"].strip())
        all_texts = [s["text"].strip() for s in subs]
        duplicates = len(all_texts) - len(set(all_texts))
        content_issues = empty_lines + duplicates
        content_ratio = content_issues / max(len(subs), 1)
        content_score = round(max(0, 15 * (1 - content_ratio * 3)))
        total_score += content_score
        details["content"] = f"空行{empty_lines}, 重复{duplicates} ({content_score}/15)"
        if duplicates > len(subs) * 0.1:
            issues.append(f"重复行过多: {duplicates}条")

        # 等级
        if total_score >= 90:
            grade = "A"
        elif total_score >= 75:
            grade = "B"
        elif total_score >= 60:
            grade = "C"
        elif total_score >= 40:
            grade = "D"
        else:
            grade = "F"

        return {
            "score": total_score,
            "grade": grade,
            "details": details,
            "issues": issues,
        }

    @staticmethod
    def _parse_srt_content(content: str) -> list[dict]:
        """从 SRT 内容字符串解析字幕"""
        subs = []
        blocks = re.split(r"\n\s*\n", content.strip())
        time_pattern = re.compile(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
        )

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

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
