"""SSUBB Coordinator - 字幕写入 + Emby 刷新

将处理完成的字幕保存到媒体目录，并通知 Emby 刷新元数据。
支持: 单语/双语字幕，SRT/ASS 格式。
"""

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("ssubb.subtitle_writer")


class SubtitleWriter:
    """字幕文件写入 + Emby 元数据刷新"""

    # ISO 639-2/B 语言码映射 (Emby/Jellyfin 友好)
    LANG_MAP = {
        "zh": "chi", "en": "eng", "ja": "jpn", "ko": "kor",
        "fr": "fre", "de": "ger", "es": "spa", "ru": "rus",
        "pt": "por", "it": "ita", "ar": "ara", "th": "tha",
        "vi": "vie", "hi": "hin", "tr": "tur", "pl": "pol",
        "nl": "dut", "sv": "swe", "da": "dan", "fi": "fin",
        "nb": "nor", "el": "gre", "he": "heb", "cs": "cze",
        "ro": "rum", "hu": "hun", "id": "ind", "ms": "may",
        "uk": "ukr",
    }

    def __init__(
        self,
        emby_server: str = "",
        emby_api_key: str = "",
        backup_existing: bool = True,
        output_mode: str = "single",       # single / bilingual
        output_format: str = "srt",        # srt / ass
        ass_style=None,                    # AssStyleConfig
        ass_bilingual_style=None,          # AssBilingualStyleConfig
    ):
        self.emby_server = emby_server.rstrip("/")
        self.emby_api_key = emby_api_key
        self.backup_existing = backup_existing
        self.output_mode = output_mode
        self.output_format = output_format
        self.ass_style = ass_style
        self.ass_bilingual_style = ass_bilingual_style
        self._http: Optional[httpx.AsyncClient] = None

    async def close(self):
        """关闭 httpx 客户端"""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    def write_subtitle(
        self,
        video_path: str,
        subtitle_content: str,
        target_lang: str = "zh",
        subtitle_format: str = "",
        original_srt: str = "",
    ) -> Optional[str]:
        """将字幕内容写入媒体目录

        Args:
            video_path: 视频文件路径
            subtitle_content: 翻译后的字幕内容 (SRT 文本)
            target_lang: 目标语言标签
            subtitle_format: 字幕格式 (空=使用配置默认值)
            original_srt: 原始语言字幕 (SRT)，用于双语模式

        Returns:
            字幕文件路径
        """
        video = Path(video_path)
        if not video.parent.is_dir():
            logger.error(f"媒体目录不存在: {video.parent}")
            return None

        fmt = subtitle_format or self.output_format
        mode = self.output_mode
        lang3 = self.LANG_MAP.get(target_lang, target_lang)

        # 决定最终内容和文件名
        if mode == "bilingual" and original_srt:
            # 双语模式强制 ASS（SRT 双语无样式区分，体验差）
            if fmt != "ass":
                logger.info(f"双语模式自动切换为 ASS 格式 (原配置: {fmt})")
                fmt = "ass"
            final_content = self._merge_bilingual(original_srt, subtitle_content, fmt)
            subtitle_path = video.parent / f"{video.stem}.{lang3}.forced.ssubb.{fmt}"
        else:
            if fmt == "ass":
                final_content = self._srt_to_ass(subtitle_content, target_lang)
            else:
                final_content = subtitle_content
            subtitle_path = video.parent / f"{video.stem}.{lang3}.ssubb.{fmt}"

        # 备份已有字幕
        if subtitle_path.is_file() and self.backup_existing:
            backup_name = f"{video.stem}.{lang3}.{fmt}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            backup_path = video.parent / backup_name
            shutil.copy2(str(subtitle_path), str(backup_path))
            logger.info(f"已备份: {subtitle_path.name} → {backup_name}")

        # 写入字幕
        try:
            subtitle_path.write_text(final_content, encoding="utf-8")
            logger.info(f"字幕已写入: {subtitle_path.name} ({mode}/{fmt})")
            return str(subtitle_path)
        except Exception as e:
            logger.exception(f"写入字幕失败: {e}")
            return None

    # =========================================================================
    # 双语合并
    # =========================================================================

    def _merge_bilingual(self, original_srt: str, translated_srt: str, fmt: str) -> str:
        """合并原文和翻译为双语字幕

        SRT 格式: 每条字幕两行 (原文 + 翻译)
        ASS 格式: 翻译在底部，原文在顶部
        """
        orig_entries = self._parse_srt_entries(original_srt)
        trans_entries = self._parse_srt_entries(translated_srt)

        if fmt == "ass":
            return self._build_bilingual_ass(orig_entries, trans_entries)
        else:
            return self._build_bilingual_srt(orig_entries, trans_entries)

    def _build_bilingual_srt(self, orig: list, trans: list) -> str:
        """构建双语 SRT (翻译在上，原文在下)"""
        lines = []
        # 以翻译条目为主轴，按索引对齐
        for i, t_entry in enumerate(trans):
            lines.append(str(i + 1))
            lines.append(t_entry["timecode"])
            lines.append(t_entry["text"])
            if i < len(orig):
                lines.append(orig[i]["text"])
            lines.append("")
        return "\n".join(lines)

    def _build_bilingual_ass(self, orig: list, trans: list) -> str:
        """构建双语 ASS (翻译底部大字，原文顶部小字)"""
        bs = self.ass_bilingual_style
        if bs:
            orig_style = (
                f"Style: Original,Noto Sans,{bs.font_size},"
                f"&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                f"-1,0,0,0,100,100,0,0,1,1,0,{bs.alignment},10,10,{bs.margin_v},1"
            )
        else:
            orig_style = (
                "Style: Original,Noto Sans,10,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                "-1,0,0,0,100,100,0,0,1,1,0,8,10,10,10,1"
            )
        header = self._ass_header("SSUBB Bilingual", style_extra=[orig_style])
        events = []
        for i, t_entry in enumerate(trans):
            start, end = self._timecode_to_ass(t_entry["timecode"])
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{t_entry['text']}")
            if i < len(orig):
                events.append(f"Dialogue: 0,{start},{end},Original,,0,0,0,,{orig[i]['text']}")

        return header + "\n".join(events) + "\n"

    # =========================================================================
    # ASS 格式
    # =========================================================================

    def _srt_to_ass(self, srt_content: str, target_lang: str = "zh") -> str:
        """SRT 转 ASS 格式"""
        entries = self._parse_srt_entries(srt_content)
        header = self._ass_header(f"SSUBB {target_lang.upper()}")

        events = []
        for entry in entries:
            start, end = self._timecode_to_ass(entry["timecode"])
            # 清理 SRT 标签
            text = re.sub(r"<[^>]+>", "", entry["text"])
            text = text.replace("\n", "\\N")
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

        return header + "\n".join(events) + "\n"

    def _ass_header(self, title: str = "SSUBB", style_extra: list = None) -> str:
        """生成 ASS 文件头"""
        # 使用配置的样式或默认值
        s = self.ass_style
        if s:
            default_style = (
                f"Style: Default,{s.font_name},{s.font_size},"
                f"{s.primary_colour},&H000000FF,{s.outline_colour},{s.back_colour},"
                f"{s.bold},0,0,0,100,100,0,0,1,{s.outline_width},{s.shadow},"
                f"{s.alignment},{s.margin_l},{s.margin_r},{s.margin_v},1"
            )
            play_res_x = s.play_res_x
            play_res_y = s.play_res_y
        else:
            default_style = (
                "Style: Default,Noto Sans,12,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                "-1,0,0,0,100,100,0,0,1,1.5,0,2,10,10,30,1"
            )
            play_res_x = 1920
            play_res_y = 1080

        styles = [default_style]
        if style_extra:
            styles.extend(style_extra)

        return (
            "[Script Info]\n"
            f"Title: {title}\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {play_res_x}\n"
            f"PlayResY: {play_res_y}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            + "\n".join(styles) + "\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

    @staticmethod
    def _timecode_to_ass(srt_timecode: str) -> tuple[str, str]:
        """SRT 时间码转 ASS 时间码

        SRT: 00:01:23,456 --> 00:01:25,789
        ASS: 0:01:23.46, 0:01:25.79
        """
        match = re.search(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            srt_timecode,
        )
        if not match:
            return "0:00:00.00", "0:00:00.00"

        h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
        start = f"{int(h1)}:{m1}:{s1}.{ms1[:2]}"
        end = f"{int(h2)}:{m2}:{s2}.{ms2[:2]}"
        return start, end

    # =========================================================================
    # SRT 解析工具
    # =========================================================================

    @staticmethod
    def _parse_srt_entries(srt_content: str) -> list[dict]:
        """解析 SRT 为结构化条目列表"""
        entries = []
        blocks = re.split(r"\n\s*\n", srt_content.strip())
        time_pattern = re.compile(
            r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}"
        )

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            timecode = None
            text_start = 0
            for i, line in enumerate(lines):
                if time_pattern.search(line):
                    timecode = line.strip()
                    text_start = i + 1
                    break

            if timecode is None:
                continue

            text = "\n".join(lines[text_start:]).strip()
            if text:
                entries.append({"timecode": timecode, "text": text})

        return entries

    def _get_http(self, timeout: float = 15) -> httpx.AsyncClient:
        """获取或创建共享 httpx 客户端"""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=timeout)
        return self._http

    async def refresh_emby(self, video_path: str) -> bool:
        """通知 Emby 刷新元数据

        通过 Emby API 刷新指定媒体的元数据，使新字幕可见。
        """
        if not self.emby_server or not self.emby_api_key:
            logger.debug("Emby 未配置，跳过刷新")
            return False

        try:
            item_id = await self._find_emby_item(video_path)
            if not item_id:
                logger.info("未找到精确匹配，触发库扫描")
                return await self._trigger_library_scan()

            client = self._get_http(30)
            response = await client.post(
                f"{self.emby_server}/Items/{item_id}/Refresh",
                params={
                    "api_key": self.emby_api_key,
                    "Recursive": "true",
                    "MetadataRefreshMode": "Default",
                    "ImageRefreshMode": "None",
                    "ReplaceAllMetadata": "false",
                    "ReplaceAllImages": "false",
                },
            )
            if response.status_code in (200, 204):
                logger.info(f"Emby 元数据已刷新 (item={item_id})")
                return True
            else:
                logger.warning(f"Emby 刷新失败: {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Emby 刷新异常: {e}")
            return False

    async def _find_emby_item(self, video_path: str) -> Optional[str]:
        """通过文件路径查找 Emby item ID"""
        video_name = Path(video_path).name
        try:
            client = self._get_http()
            response = await client.get(
                f"{self.emby_server}/Items",
                params={
                    "api_key": self.emby_api_key,
                    "SearchTerm": Path(video_path).stem,
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Episode",
                    "Fields": "Path",
                    "Limit": 10,
                },
            )
            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                for item in items:
                    item_path = item.get("Path", "")
                    if Path(item_path).name == video_name:
                        return item.get("Id")
        except Exception as e:
            logger.debug(f"Emby 搜索失败: {e}")
        return None

    async def _trigger_library_scan(self) -> bool:
        """触发 Emby 全库扫描"""
        try:
            client = self._get_http()
            response = await client.post(
                f"{self.emby_server}/Library/Refresh",
                params={"api_key": self.emby_api_key},
            )
            return response.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"触发 Emby 库扫描失败: {e}")
            return False
