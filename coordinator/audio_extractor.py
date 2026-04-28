"""SSUBB Coordinator - 音频提取

使用 FFmpeg 从视频中提取音轨，转换为 Whisper 友好的格式。
支持自动音轨选择：优先对白音轨，跳过评论/配音音轨。
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ssubb.audio")


# =============================================================================
# 音轨信息
# =============================================================================

class AudioTrackInfo:
    """音轨信息"""
    def __init__(self, index: int, codec: str, channels: int,
                 language: str = "", title: str = "",
                 is_default: bool = False, is_commentary: bool = False):
        self.index = index
        self.codec = codec
        self.channels = channels
        self.language = language
        self.title = title
        self.is_default = is_default
        self.is_commentary = is_commentary

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "codec": self.codec,
            "channels": self.channels,
            "language": self.language,
            "title": self.title,
            "is_default": self.is_default,
            "is_commentary": self.is_commentary,
        }


def probe_audio_tracks(file_path: str) -> list[AudioTrackInfo]:
    """使用 ffprobe 分析视频的所有音轨

    Returns:
        AudioTrackInfo 列表，按流索引排序
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-select_streams", "a",
                file_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0
            ),
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe 失败 (code={result.returncode})")
            return []

        data = json.loads(result.stdout)
        tracks = []
        audio_idx = 0

        for stream in data.get("streams", []):
            if stream.get("codec_type") != "audio":
                continue

            tags = stream.get("tags", {})
            title = tags.get("title", "").lower()

            # 检测评论/描述性音轨
            commentary_keywords = [
                "commentary", "comment", "director", "description",
                "descriptive", "narr", "评论", "解说", "导演",
            ]
            is_commentary = any(kw in title for kw in commentary_keywords)

            # 检测配音音轨 (通常标题含 "dub" / "dubbed")
            if any(kw in title for kw in ["dub", "dubbed"]):
                is_commentary = True  # 同样降低优先级

            tracks.append(AudioTrackInfo(
                index=audio_idx,
                codec=stream.get("codec_name", "unknown"),
                channels=stream.get("channels", 0),
                language=tags.get("language", ""),
                title=tags.get("title", ""),
                is_default=stream.get("disposition", {}).get("default", 0) == 1,
                is_commentary=is_commentary,
            ))
            audio_idx += 1

        logger.info(f"发现 {len(tracks)} 条音轨: "
                     + ", ".join(f"[{t.index}] {t.language or '?'} {t.channels}ch"
                                 + (" 🎙评论" if t.is_commentary else "")
                                 + (" ★默认" if t.is_default else "")
                                 for t in tracks))

        return tracks

    except Exception as e:
        logger.warning(f"音轨分析失败: {e}")
        return []


def select_best_audio_track(tracks: list[AudioTrackInfo]) -> int:
    """从音轨列表中选择最佳音轨

    优先级:
    1. 非评论/非描述性
    2. 默认音轨
    3. 声道数更多的 (立体声 > 单声道，但不偏好 7.1 over 2.0)
    4. 索引靠前的

    Returns:
        最佳音轨索引
    """
    if not tracks:
        return 0

    # 过滤掉评论/描述音轨
    candidates = [t for t in tracks if not t.is_commentary]
    if not candidates:
        candidates = tracks  # 如果全是评论，回退到全部

    # 优先默认音轨
    defaults = [t for t in candidates if t.is_default]
    if defaults:
        return defaults[0].index

    # 否则选声道数合适的 (2~6声道优先，太多声道可能是环绕声效轨)
    def channel_score(t: AudioTrackInfo) -> int:
        if 2 <= t.channels <= 6:
            return 0
        elif t.channels == 1:
            return 1
        else:
            return 2

    candidates.sort(key=lambda t: (channel_score(t), t.index))
    return candidates[0].index


def extract_audio(
    input_file: str,
    output_dir: str,
    audio_format: str = "flac",
    sample_rate: int = 16000,
    channels: int = 1,
    audio_track_index: int = -1,
) -> Optional[str]:
    """从视频提取音频

    Args:
        input_file: 输入视频文件路径
        output_dir: 输出目录
        audio_format: 输出格式 (flac/wav)
        sample_rate: 采样率 (默认 16kHz)
        channels: 声道数 (默认 1 单声道)
        audio_track_index: 音轨索引 (-1=自动选择)

    Returns:
        输出音频文件路径，失败返回 None
    """
    input_path = Path(input_file)
    if not input_path.is_file():
        logger.error(f"输入文件不存在: {input_file}")
        return None

    # 自动选择最佳音轨
    if audio_track_index < 0:
        tracks = probe_audio_tracks(input_file)
        audio_track_index = select_best_audio_track(tracks)
        if tracks:
            selected = next((t for t in tracks if t.index == audio_track_index), None)
            if selected:
                logger.info(
                    f"自动选择音轨 [{audio_track_index}]: "
                    f"{selected.language or '?'} {selected.channels}ch {selected.codec}"
                    f"{' (默认)' if selected.is_default else ''}"
                )

    # 生成输出路径
    output_path = Path(output_dir) / f"{input_path.stem}.{audio_format}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-map", f"0:a:{audio_track_index}",
        "-vn",                    # 无视频
        "-ac", str(channels),     # 声道
        "-ar", str(sample_rate),  # 采样率
        "-threads", "1",          # 限制线程数量
    ]

    if audio_format == "flac":
        cmd.extend(["-c:a", "flac", "-compression_level", "5"])
    else:
        cmd.extend(["-c:a", "pcm_s16le"])

    cmd.append(str(output_path))

    # Linux 补充低优先级 (nice -n 10) 容错
    if sys.platform != "win32":
        cmd = ["nice", "-n", "10"] + cmd

    logger.info(f"提取音频: {input_path.name} → {output_path.name} (音轨 {audio_track_index})")
    logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # 10 分钟超时
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0
            ),
        )

        if result.returncode == 0 and output_path.is_file():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"音频提取完成: {output_path.name} ({size_mb:.1f} MB)")
            return str(output_path)
        else:
            logger.error(f"FFmpeg 失败 (code={result.returncode})")
            if result.stderr:
                logger.error(f"stderr: {result.stderr[-500:]}")
            return None

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg 超时 (>10min)")
        return None
    except Exception as e:
        logger.exception(f"音频提取异常: {e}")
        return None


def get_video_duration(file_path: str) -> Optional[float]:
    """获取视频时长 (秒)

    Args:
        file_path: 视频文件路径

    Returns:
        时长 (秒)，失败返回 None
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0
            ),
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"获取视频时长失败: {e}")
    return None


def cleanup_audio(audio_path: str):
    """清理临时音频文件"""
    try:
        p = Path(audio_path)
        if p.is_file():
            p.unlink()
            logger.debug(f"已清理音频: {p.name}")
    except Exception as e:
        logger.warning(f"清理音频失败: {e}")
