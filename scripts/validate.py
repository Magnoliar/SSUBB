"""SSUBB 环境验证脚本

检查依赖、GPU、网络连通性等运行前置条件。
支持 --check-deps / --check-gpu / --check-network / --check-all。

使用方法:
    python scripts/validate.py --check-all
    python scripts/validate.py --check-gpu --check-network
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.terminal import console, Section, KV, run


# =============================================================================
# 检查项
# =============================================================================

def check_python(*, verbose: bool = True) -> bool:
    """检查 Python 版本"""
    v = sys.version_info
    ok = v >= (3, 10)
    if verbose:
        tag = f"{v.major}.{v.minor}.{v.micro}"
        (console.ok if ok else console.fail)(f"Python {tag}" + ("" if ok else " (需要 ≥ 3.10)"))
    return ok


def check_deps(*, verbose: bool = True) -> bool:
    """检查核心依赖是否可导入"""
    deps = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("pydantic", "Pydantic"),
        ("yaml", "PyYAML"),
        ("httpx", "httpx"),
        ("faster_whisper", "faster-whisper"),
        ("openai", "openai"),
        ("torch", "PyTorch"),
        ("ctranslate2", "CTranslate2"),
    ]
    all_ok = True
    for module, label in deps:
        try:
            mod = importlib.import_module(module)
            ver = getattr(mod, "__version__", "?")
            if verbose:
                console.ok(f"{label} ({ver})")
        except ImportError:
            if verbose:
                console.fail(f"{label} — 未安装")
            all_ok = False
    return all_ok


def check_gpu(*, verbose: bool = True) -> bool:
    """检查 CUDA / GPU 可用性"""
    try:
        import torch
        avail = torch.cuda.is_available()
        if avail:
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_mem / 1024**3
            if verbose:
                console.ok(f"CUDA 可用 — {name} ({vram:.1f} GB)")
        elif verbose:
            console.warn("CUDA 不可用，将使用 CPU 模式（速度较慢）")
        return avail
    except ImportError:
        if verbose:
            console.fail("PyTorch 未安装，无法检测 GPU")
        return False


def check_ffmpeg(*, verbose: bool = True) -> bool:
    """检查 FFmpeg 是否可用"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        code, out, _ = run(["ffmpeg", "-version"], timeout=10)
        ver = out.split("\n")[0] if code == 0 else "?"
        if verbose:
            console.ok(f"FFmpeg — {ver}")
        return True
    if verbose:
        console.fail("FFmpeg 未找到（音频提取必需）")
    return False


def check_network(url: str = "https://api.deepseek.com/v1/models", *, verbose: bool = True) -> bool:
    """检查外网连通性"""
    import httpx
    try:
        r = httpx.get(url, timeout=8)
        ok = r.status_code < 500
        if verbose:
            (console.ok if ok else console.warn)(f"网络连通 — {url} ({r.status_code})")
        return ok
    except Exception as e:
        if verbose:
            console.fail(f"网络不通 — {url} ({e})")
        return False


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SSUBB 环境验证")
    parser.add_argument("--check-deps", action="store_true", help="检查 Python 依赖")
    parser.add_argument("--check-gpu", action="store_true", help="检查 GPU / CUDA")
    parser.add_argument("--check-network", action="store_true", help="检查网络连通性")
    parser.add_argument("--check-all", action="store_true", help="检查所有项目")
    args = parser.parse_args()

    # 默认行为: 无参数时检查全部
    if not any(vars(args).values()):
        args.check_all = True

    console.h1("SSUBB 环境验证")
    results = {}

    # Python
    with Section("Python"):
        results["python"] = check_python()

    # 依赖
    if args.check_deps or args.check_all:
        with Section("核心依赖"):
            results["deps"] = check_deps()

    # GPU
    if args.check_gpu or args.check_all:
        with Section("GPU / CUDA"):
            results["gpu"] = check_gpu()

    # FFmpeg
    if args.check_all:
        with Section("系统工具"):
            results["ffmpeg"] = check_ffmpeg()

    # 网络
    if args.check_network or args.check_all:
        with Section("网络连通性"):
            results["network"] = check_network()

    # 汇总
    console.blank()
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    if passed == total:
        console.ok(f"全部通过 ({passed}/{total})")
    else:
        console.warn(f"通过 {passed}/{total}，请修复上述问题后重试")
        sys.exit(1)


if __name__ == "__main__":
    main()
