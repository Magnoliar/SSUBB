"""SSUBB Worker - faster-whisper-xxl 二进制转写引擎

通过 subprocess 调用 faster-whisper-xxl 独立二进制进行语音转写。
不依赖 PyTorch / stable_whisper，二进制内置 CUDA runtime。
支持自动下载安装（参考 VideoCaptioner 方案）。

参考: VideoCaptioner/core/asr/faster_whisper.py
"""

import asyncio
import io
import logging
import os
import platform
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from worker.srt_parser import SRTParser, SubtitleSegment

logger = logging.getLogger("ssubb.whisper_runner")

# ============================================================================
# 下载配置（参考 VideoCaptioner）
# ============================================================================

# 二进制存放目录
BIN_DIR = Path("./bin")

# 下载源（GitHub Releases）
# 备用源: https://modelscope.cn/models/bkfengg/whisper-cpp
_WHISPER_DOWNLOAD_URLS = {
    "win64": "https://github.com/Purfview/whisper-standalone-win/releases/download/Faster-Whisper-XXL/Faster-Whisper-XXL_r245.2_windows.zip",
}

# ModelScope 备用源（国内更快）
_WHISPER_DOWNLOAD_URLS_CN = {
    "win64": "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/Faster-Whisper-XXL_r245.2_windows.7z",
}

# 幻觉关键词列表（Whisper 常见幻觉）
HALLUCINATION_KEYWORDS = [
    "请不吝点赞 订阅 转发",
    "打赏支持明镜",
    "请不吝点赞",
    "订阅频道",
    "转发分享",
    "Thanks for watching",
    "Thanks for watching!",
    "Thank you for watching",
    "Subscribe",
    "Like and subscribe",
]

# 进度映射：转写占流水线 10-50%
_PROGRESS_MIN = 10
_PROGRESS_MAX = 50


def find_whisper_binary(whisper_binary: str = "") -> Optional[Path]:
    """查找 faster-whisper-xxl 二进制

    优先级:
    1. 配置的 whisper_binary 路径
    2. PATH 中的 faster-whisper-xxl
    3. PATH 中的 faster-whisper
    4. ./bin/ 目录下的二进制

    Returns:
        Path 或 None
    """
    # 1. 配置路径
    if whisper_binary:
        p = Path(whisper_binary)
        if p.exists():
            return p
        # 可能是命令名，在 PATH 中查找
        found = shutil.which(whisper_binary)
        if found:
            return Path(found)

    # 2. PATH 中查找
    for name in ["faster-whisper-xxl", "faster-whisper"]:
        found = shutil.which(name)
        if found:
            return Path(found)

    # 3. ./bin/ 目录
    bin_dir = Path("./bin")
    if bin_dir.exists():
        for name in ["faster-whisper-xxl.exe", "faster-whisper-xxl",
                      "faster-whisper.exe", "faster-whisper"]:
            candidate = bin_dir / name
            if candidate.exists():
                return candidate
        # 检查子目录 Faster-Whisper-XXL/
        xxl_dir = bin_dir / "Faster-Whisper-XXL"
        if xxl_dir.exists():
            for name in ["faster-whisper-xxl.exe", "faster-whisper-xxl"]:
                candidate = xxl_dir / name
                if candidate.exists():
                    return candidate

    return None


def download_whisper_binary() -> Optional[Path]:
    """自动下载并安装 faster-whisper-xxl 二进制

    参考 VideoCaptioner 的下载逻辑，从 GitHub/ModelScope 下载。
    下载完成后解压到 ./bin/ 目录。

    Returns:
        Path 或 None（下载失败）
    """
    import urllib.request

    system = platform.system().lower()
    if system == "windows":
        platform_key = "win64"
    elif system == "linux":
        platform_key = "win64"  # Linux 可用 Windows 版本通过 Wine，或用 pip install faster-whisper
    else:
        logger.error(f"不支持的平台: {system}")
        return None

    # 选择下载源（优先 GitHub，失败则用 ModelScope）
    urls = []
    if platform_key in _WHISPER_DOWNLOAD_URLS:
        urls.append(_WHISPER_DOWNLOAD_URLS[platform_key])
    if platform_key in _WHISPER_DOWNLOAD_URLS_CN:
        urls.append(_WHISPER_DOWNLOAD_URLS_CN[platform_key])

    if not urls:
        logger.error(f"没有可用的下载源 (platform={platform_key})")
        return None

    BIN_DIR.mkdir(parents=True, exist_ok=True)

    for url in urls:
        try:
            logger.info(f"正在下载 faster-whisper-xxl ...")
            logger.info(f"  下载地址: {url}")
            print(f"[whisper] 正在下载 faster-whisper-xxl ...")
            print(f"[whisper]   {url}")

            # 下载
            req = urllib.request.Request(url, headers={"User-Agent": "SSUBB/1.0"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()

            logger.info(f"[whisper] 下载完成 ({len(data) / 1024 / 1024:.1f} MB)")

            # 解压
            if url.endswith(".zip"):
                print(f"[whisper] 正在解压...")
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    zf.extractall(BIN_DIR)
            elif url.endswith(".7z"):
                # 7z 需要外部工具
                logger.warning("7z 格式需要手动解压，请安装 7-Zip")
                archive_path = BIN_DIR / "faster-whisper-xxl.7z"
                archive_path.write_bytes(data)
                print(f"[whisper] 已下载到: {archive_path}")
                print(f"[whisper] 请手动解压到: {BIN_DIR}")
                return None
            else:
                # 直接是可执行文件
                exe_name = "faster-whisper-xxl.exe" if system == "windows" else "faster-whisper-xxl"
                exe_path = BIN_DIR / exe_name
                exe_path.write_bytes(data)
                if system != "windows":
                    exe_path.chmod(0o755)

            # 验证安装
            binary = find_whisper_binary()
            if binary:
                print(f"[whisper] 安装成功: {binary}")
                return binary

        except Exception as e:
            logger.warning(f"下载失败 ({url}): {e}")
            continue

    logger.error("所有下载源均失败")
    return None


def ensure_whisper_binary(whisper_binary: str = "") -> Optional[Path]:
    """确保 faster-whisper-xxl 可用，不存在则自动下载

    这是主要的入口函数，替代 find_whisper_binary() 用于需要保证可用的场景。

    Args:
        whisper_binary: 手动配置的二进制路径

    Returns:
        Path 或 None
    """
    # 先查找
    binary = find_whisper_binary(whisper_binary)
    if binary:
        return binary

    # 未找到，尝试自动下载
    logger.info("faster-whisper-xxl 未找到，尝试自动下载...")
    print("[whisper] faster-whisper-xxl 未找到，正在自动下载安装...")

    binary = download_whisper_binary()
    if binary:
        return binary

    # 下载也失败了，打印安装指引
    print_install_guide()
    return None


def print_install_guide():
    """打印 faster-whisper-xxl 安装指引"""
    msg = """
{eq}
  错误: faster-whisper-xxl 未找到
{eq}

  SSUBB Worker 需要 faster-whisper-xxl 进行语音转写。

  安装方法 (任选其一):

  方式 A: 下载预编译二进制 (推荐)
    Windows:
      1. 下载: https://github.com/Purfview/whisper-standalone-win/releases
      2. 解压到任意目录
      3. 将目录添加到 PATH，或在 config.yaml 中配置:
         worker:
           transcribe:
             whisper_binary: "C:/path/to/faster-whisper-xxl.exe"

    Linux:
      1. 下载: https://github.com/Purfview/whisper-standalone-win/releases
      2. 解压后赋予执行权限: chmod +x faster-whisper-xxl
      3. 移动到 PATH: mv faster-whisper-xxl /usr/local/bin/

  方式 B: 使用 pip 安装 (仅 CPU)
    pip install faster-whisper

  更多信息: https://github.com/Purfview/whisper-standalone-win
{eq}
""".format(eq="=" * 60)
    print(msg)


def _map_progress(whisper_progress: int) -> int:
    """将 whisper 进度 (0-100) 映射到流水线进度 (10-50)"""
    return _PROGRESS_MIN + int(whisper_progress * (_PROGRESS_MAX - _PROGRESS_MIN) / 100)


def _build_command(
    binary: Path,
    audio_path: str,
    output_dir: str,
    model: str = "large-v3-turbo",
    model_dir: str = "./models",
    device: str = "cuda",
    language: str = "",
    vad_filter: bool = True,
    vad_threshold: float = 0.5,
    vad_method: str = "silero_v4_fw",
    compute_type: str = "float16",
) -> List[str]:
    """构建 faster-whisper-xxl 命令行参数

    参考 VideoCaptioner/core/asr/faster_whisper.py _build_command()
    """
    cmd = [
        str(binary),
        "-m", str(model),
        "--print_progress",
    ]

    # 模型目录
    if model_dir:
        cmd.extend(["--model_dir", str(model_dir)])

    # 输入文件
    cmd.append(str(audio_path))

    # 设备 + 输出格式 + 输出目录
    cmd.extend(["-d", device, "--output_format", "srt", "-o", str(output_dir)])

    # 语言（有指定才传，空字符串让二进制自动检测）
    if language:
        cmd.extend(["-l", language])

    # VAD
    if vad_filter:
        cmd.extend([
            "--vad_filter", "true",
            "--vad_threshold", f"{vad_threshold:.2f}",
        ])
        if vad_method:
            cmd.extend(["--vad_method", vad_method])
    else:
        cmd.extend(["--vad_filter", "false"])

    # 句子级断句（不要单词级时间戳）
    cmd.append("--sentence")

    # 断句宽度（根据语言自动设置）
    if language in ("zh", "ja", "ko"):
        cmd.extend(["--max_line_width", "30"])
    else:
        cmd.extend(["--max_line_width", "90"])
    cmd.extend(["--max_line_count", "1"])

    # 关闭提示音
    cmd.append("--beep_off")

    # RTX 50 系列检测（需要 float16）
    if _is_rtx_50_series():
        cmd.extend(["--compute_type", "float16"])

    return cmd


def _is_rtx_50_series() -> bool:
    """检测是否为 RTX 50 系显卡（通过 nvidia-smi，不依赖 torch）"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if re.search(r"rtx\s*50\d{2}", line, re.IGNORECASE):
                    logger.debug(f"检测到 RTX 50 系显卡: {line.strip()}")
                    return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def filter_hallucinations(segments: List[SubtitleSegment]) -> List[SubtitleSegment]:
    """过滤 Whisper 幻觉和音乐标记

    参考 VideoCaptioner/core/asr/faster_whisper.py _make_segments()
    """
    filtered = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        # 跳过音乐标记
        if text.startswith(("[", "(", "【", "（")):
            continue

        # 跳过幻觉关键词
        if any(kw in text for kw in HALLUCINATION_KEYWORDS):
            continue

        filtered.append(seg)

    return filtered


async def run_whisper(
    binary: Path,
    audio_path: str,
    output_dir: str,
    model: str = "large-v3-turbo",
    model_dir: str = "./models",
    device: str = "cuda",
    language: str = "",
    vad_filter: bool = True,
    vad_threshold: float = 0.5,
    vad_method: str = "silero_v4_fw",
    compute_type: str = "float16",
    timeout: int = 3600,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> tuple[str, int]:
    """执行 faster-whisper-xxl 转写

    Args:
        binary: 二进制路径
        audio_path: 输入音频文件路径
        output_dir: SRT 输出目录
        model: Whisper 模型名
        model_dir: 模型存储目录
        device: cuda / cpu
        language: 语言代码（空=自动检测）
        vad_filter: 是否启用 VAD
        vad_threshold: VAD 阈值
        vad_method: VAD 方法
        compute_type: 计算类型
        timeout: 超时秒数
        progress_callback: 进度回调 (progress_pct, message)

    Returns:
        (srt_content, segment_count)

    Raises:
        RuntimeError: 转写失败
        asyncio.TimeoutError: 超时
    """
    # 确保输出目录存在
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 构建命令
    cmd = _build_command(
        binary=binary,
        audio_path=audio_path,
        output_dir=str(out_dir),
        model=model,
        model_dir=model_dir,
        device=device,
        language=language,
        vad_filter=vad_filter,
        vad_threshold=vad_threshold,
        vad_method=vad_method,
        compute_type=compute_type,
    )

    logger.info(f"启动转写: {' '.join(cmd[:6])}...")

    # 启动子进程
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Windows: 隐藏控制台窗口
        **({"env": {**os.environ}} if os.name != "nt" else {}),
    )

    is_finished = False
    error_lines: list[str] = []
    last_progress = 0

    try:
        # 实时读取 stdout
        async def _read_stream(stream, is_error=False):
            nonlocal is_finished, last_progress
            async for line_bytes in stream:
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                if is_error:
                    error_lines.append(line)
                    logger.debug(f"[stderr] {line}")
                    continue

                logger.debug(f"[whisper] {line}")

                # 解析进度百分比
                if match := re.search(r"(\d+)%", line):
                    progress = int(match.group(1))
                    if progress == 100:
                        is_finished = True
                    mapped = _map_progress(progress)
                    if mapped > last_progress:
                        last_progress = mapped
                        if progress_callback:
                            progress_callback(mapped, f"转写 {progress}%")

                # 完成标记
                if "Subtitles are written to" in line:
                    is_finished = True
                    if progress_callback:
                        progress_callback(_PROGRESS_MAX, "转写完成")

                # 错误检测
                if "error" in line.lower() or "Error" in line:
                    error_lines.append(line)

        # 并发读取 stdout 和 stderr
        await asyncio.gather(
            _read_stream(process.stdout, is_error=False),
            _read_stream(process.stderr, is_error=True),
        )

        # 等待进程结束
        await asyncio.wait_for(process.wait(), timeout=30)

    except asyncio.TimeoutError:
        process.kill()
        raise RuntimeError(f"转写超时 ({timeout}s)")

    if not is_finished:
        error_msg = "\n".join(error_lines[-10:]) if error_lines else "未知错误"
        raise RuntimeError(f"转写失败 (exit code: {process.returncode}):\n{error_msg}")

    # 读取输出的 SRT 文件
    srt_files = list(out_dir.glob("*.srt"))
    if not srt_files:
        raise RuntimeError(f"转写完成但未找到 SRT 输出文件 (目录: {out_dir})")

    # 取最新的 SRT 文件
    srt_path = max(srt_files, key=lambda p: p.stat().st_mtime)
    srt_content = srt_path.read_text(encoding="utf-8")

    # 解析段数
    segments = SRTParser.parse(srt_content)
    segment_count = len(segments)

    logger.info(f"转写完成: {segment_count} 段, 输出: {srt_path.name}")

    return srt_content, segment_count
