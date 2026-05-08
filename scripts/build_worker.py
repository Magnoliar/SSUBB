"""SSUBB Worker 构建脚本 (PyInstaller)

使用 PyInstaller 将 Worker 打包为独立可执行文件。
faster-whisper-xxl 内置 CUDA runtime，无需区分 CUDA 版本。

用法:
    python scripts/build_worker.py [--onefile] [--output-dir dist]

前置条件:
    pip install pyinstaller
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_version() -> str:
    """从 shared/constants.py 读取版本号"""
    constants = PROJECT_ROOT / "shared" / "constants.py"
    for line in constants.read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION"):
            return line.split('"')[1]
    return "0.0.0"


def build(args):
    version = get_version()
    system = platform.system().lower()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build] SSUBB Worker v{version}")
    print(f"[build] Platform: {system}")
    print(f"[build] Output: {output_dir}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ssubb-worker",
        f"--distpath={output_dir}",
        f"--workpath={output_dir / 'build'}",
        f"--specpath={output_dir}",
        "--noconfirm",
        "--clean",
        "--collect-all=shared",
        "--collect-all=worker",
        "--hidden-import=uvicorn",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=fastapi",
        "--hidden-import=pydantic",
        "--hidden-import=httpx",
        "--hidden-import=yaml",
        "--hidden-import=openai",
        "--hidden-import=json_repair",
        "--hidden-import=python_multipart",
        # 排除不需要的大型依赖
        "--exclude-module=tkinter",
        "--exclude-module=matplotlib",
        "--exclude-module=scipy",
        "--exclude-module=pandas",
    ]

    if args.onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.append(str(PROJECT_ROOT / "worker" / "main.py"))

    print(f"[build] Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[build] FAILED")
        sys.exit(1)

    # 产物路径
    exe_name = "ssubb-worker.exe" if system == "windows" else "ssubb-worker"
    if args.onefile:
        src = output_dir / exe_name
    else:
        src = output_dir / "ssubb-worker" / exe_name

    if src.exists():
        print(f"[build] Output: {src}")
    else:
        print(f"[build] Warning: expected output not found at {src}")

    # 创建 README
    readme = output_dir / "README.txt"
    readme.write_text(
        f"SSUBB Worker v{version}\n"
        f"{'=' * 40}\n\n"
        f"快速启动:\n"
        f"  1. 双击 {exe_name} 启动 Worker\n"
        f"  2. 首次运行会自动生成 config.yaml 并引导配置\n"
        f"  3. 首次启动自动下载 faster-whisper-xxl 转写引擎\n"
        f"  4. Whisper 模型会在首次任务时自动下载\n\n"
        f"前置要求:\n"
        f"  - NVIDIA GPU + CUDA 驱动\n"
        f"  - 无需安装 PyTorch (faster-whisper-xxl 内置 CUDA)\n"
        f"  - Coordinator 地址 (在 config.yaml 中配置)\n\n"
        f"更多文档: https://github.com/Magnoliar/SSUBB\n",
        encoding="utf-8",
    )

    for d in ["data", "models"]:
        (output_dir / d).mkdir(parents=True, exist_ok=True)

    print(f"\n[build] Done!")
    for item in sorted(output_dir.iterdir()):
        print(f"  {item.name}")


def main():
    parser = argparse.ArgumentParser(description="Build SSUBB Worker with PyInstaller")
    parser.add_argument("--onefile", action="store_true", help="Build as single file")
    parser.add_argument("--output-dir", default="dist/worker", help="Output directory")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
