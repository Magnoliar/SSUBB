"""SSUBB Worker - 环境检查与诊断

首次启动或运维时自动检查 Worker 运行环境，输出诊断报告。
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ssubb.env_check")


class EnvCheckResult:
    """环境检查单项结果"""
    def __init__(self, name: str, passed: bool, detail: str = "", required: bool = True):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.required = required

    def __repr__(self):
        icon = "✅" if self.passed else ("❌" if self.required else "⚠️")
        return f"{icon} {self.name}: {self.detail}"


def check_python_version() -> EnvCheckResult:
    """检查 Python 版本 >= 3.10"""
    ver = sys.version_info
    version_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if ver >= (3, 10):
        return EnvCheckResult("Python", True, f"{version_str} (OK)")
    return EnvCheckResult("Python", False, f"{version_str} (需要 >= 3.10)")


def check_ffmpeg() -> EnvCheckResult:
    """检查 FFmpeg 可用性"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return EnvCheckResult("FFmpeg", False, "未找到 (需要安装 FFmpeg)")
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        first_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        return EnvCheckResult("FFmpeg", True, first_line.strip())
    except Exception as e:
        return EnvCheckResult("FFmpeg", False, str(e))


def check_ffprobe() -> EnvCheckResult:
    """检查 ffprobe 可用性"""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return EnvCheckResult("FFprobe", True, ffprobe)
    return EnvCheckResult("FFprobe", False, "未找到 (通常随 FFmpeg 一起安装)", required=False)


def check_cuda() -> EnvCheckResult:
    """检查 CUDA / GPU 可用性"""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_total = torch.cuda.get_device_properties(0).total_mem / (1024 ** 3)
            return EnvCheckResult(
                "CUDA GPU", True,
                f"{gpu_name} ({vram_total:.1f} GB VRAM)"
            )
        else:
            return EnvCheckResult("CUDA GPU", False, "torch.cuda 不可用 (将使用 CPU 模式)")
    except ImportError:
        return EnvCheckResult("CUDA GPU", False, "PyTorch 未安装", required=False)
    except Exception as e:
        return EnvCheckResult("CUDA GPU", False, str(e))


def check_whisper_model(model_dir: str = "./models", model_name: str = "large-v3-turbo") -> EnvCheckResult:
    """检查 Whisper 模型是否已下载"""
    model_path = Path(model_dir)
    if not model_path.exists():
        return EnvCheckResult("Whisper 模型", False, f"目录不存在: {model_dir}")

    # faster-whisper 模型目录命名
    possible_names = [
        model_name,
        f"faster-whisper-{model_name}",
        f"models--Systran--faster-whisper-{model_name}",
    ]

    for name in possible_names:
        candidate = model_path / name
        if candidate.exists() and candidate.is_dir():
            # 检查目录是否有 model.bin 或类似文件
            files = list(candidate.rglob("model.bin")) + list(candidate.rglob("*.bin"))
            if files:
                size_gb = sum(f.stat().st_size for f in files) / (1024 ** 3)
                return EnvCheckResult(
                    "Whisper 模型", True,
                    f"{model_name} ({size_gb:.1f} GB) @ {candidate}"
                )

    return EnvCheckResult(
        "Whisper 模型", False,
        f"未找到 {model_name} (首次启动将自动下载约 3GB)"
    )


def check_disk_space(path: str = ".") -> EnvCheckResult:
    """检查磁盘可用空间"""
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        if free_gb > 10:
            return EnvCheckResult("磁盘空间", True, f"{free_gb:.1f} GB 可用 / {total_gb:.0f} GB 总计")
        elif free_gb > 3:
            return EnvCheckResult("磁盘空间", True, f"⚠️ {free_gb:.1f} GB 可用 (偏低)")
        else:
            return EnvCheckResult("磁盘空间", False, f"{free_gb:.1f} GB 可用 (不足)")
    except Exception as e:
        return EnvCheckResult("磁盘空间", False, str(e), required=False)


def check_llm_config(api_base: str = "", api_key: str = "") -> EnvCheckResult:
    """检查 LLM 配置"""
    if not api_base:
        return EnvCheckResult("LLM 配置", False, "api_base 未配置")
    if not api_key:
        return EnvCheckResult("LLM 配置", False, "api_key 未配置")
    return EnvCheckResult("LLM 配置", True, f"{api_base} (Key: {api_key[:8]}...)")


def check_coordinator_url(url: str = "") -> EnvCheckResult:
    """检查 Coordinator URL"""
    if not url:
        return EnvCheckResult("Coordinator URL", False, "未配置 (无法回调结果)")
    return EnvCheckResult("Coordinator URL", True, url)


def run_full_check(config=None) -> list[EnvCheckResult]:
    """执行完整环境检查

    Args:
        config: WorkerConfig 对象 (可选)

    Returns:
        EnvCheckResult 列表
    """
    results = [
        check_python_version(),
        check_ffmpeg(),
        check_ffprobe(),
        check_cuda(),
        check_disk_space(),
    ]

    if config:
        results.append(check_whisper_model(
            config.transcribe.model_dir,
            config.transcribe.model,
        ))
        results.append(check_llm_config(
            config.llm.api_base,
            config.llm.api_key,
        ))
        results.append(check_coordinator_url(config.coordinator_url))
    else:
        results.append(check_whisper_model())
        results.append(check_llm_config())
        results.append(check_coordinator_url())

    return results


def print_check_report(results: list[EnvCheckResult]):
    """打印环境检查报告"""
    print("\n" + "=" * 60)
    print("  SSUBB Worker 环境检查")
    print("=" * 60 + "\n")

    passed = 0
    failed = 0
    warned = 0

    for r in results:
        print(f"  {r}")
        if r.passed:
            passed += 1
        elif r.required:
            failed += 1
        else:
            warned += 1

    print(f"\n  结果: {passed} 通过 / {failed} 失败 / {warned} 警告")

    if failed > 0:
        print("  ⚠️ 存在必要组件缺失，部分功能可能不可用")
    else:
        print("  🎉 环境检查通过!")

    print("=" * 60 + "\n")

    return failed == 0


if __name__ == "__main__":
    # 独立运行: python -m worker.env_check
    try:
        from worker.config import load_worker_config
        cfg = load_worker_config()
        results = run_full_check(cfg)
    except Exception:
        results = run_full_check()

    ok = print_check_report(results)
    sys.exit(0 if ok else 1)
