"""SSUBB Launcher 构建脚本 (PyInstaller)

将 PySide6 桌面启动器打包为独立可执行文件。

用法:
    python scripts/build_launcher.py [--onefile] [--output-dir dist]

前置条件:
    pip install pyinstaller PySide6
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_version() -> str:
    constants = PROJECT_ROOT / "shared" / "constants.py"
    for line in constants.read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION"):
            return line.split('"')[1]
    return "0.0.0"


def build(args):
    version = get_version()
    system = platform.system().lower()
    arch = "win64" if system == "windows" else "linux-x64"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build] SSUBB Launcher v{version}")
    print(f"[build] Platform: {system} ({arch})")
    print(f"[build] Output: {output_dir}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ssubb-launcher",
        f"--distpath={output_dir}",
        f"--workpath={output_dir / 'build'}",
        f"--specpath={output_dir}",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--collect-all=shared",
        "--collect-all=launcher",
        "--hidden-import=worker",
        "--hidden-import=worker.config",
        "--hidden-import=worker.env_check",
        "--hidden-import=worker.model_manager",
        "--hidden-import=worker.health",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=yaml",
        "--hidden-import=pydantic",
        "--hidden-import=httpx",
        "--exclude-module=matplotlib",
        "--exclude-module=numpy.testing",
        "--exclude-module=scipy",
        "--exclude-module=pandas",
        "--exclude-module=uvicorn",
        "--exclude-module=fastapi",
        "--exclude-module=torch",
        "--exclude-module=faster_whisper",
        "--exclude-module=stable_ts",
        "--exclude-module=openai",
    ]

    if args.onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.append(str(PROJECT_ROOT / "launcher" / "__main__.py"))

    print(f"[build] Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[build] FAILED")
        sys.exit(1)

    exe_name = "ssubb-launcher.exe" if system == "windows" else "ssubb-launcher"
    if args.onefile:
        src = output_dir / exe_name
    else:
        src = output_dir / "ssubb-launcher" / exe_name

    if src.exists():
        print(f"[build] Output: {src}")
    else:
        print(f"[build] Warning: expected output not found at {src}")

    readme = output_dir / "README.txt"
    readme.write_text(
        f"SSUBB Launcher v{version}\n"
        f"{'=' * 40}\n\n"
        f"双击 {exe_name} 启动 Worker 管理界面。\n\n"
        f"功能:\n"
        f"  - 环境检测 (GPU/CUDA/FFmpeg/模型)\n"
        f"  - 一键启动/停止/重启 Worker\n"
        f"  - 实时日志查看\n"
        f"  - 配置编辑 (无需手写 YAML)\n"
        f"  - 系统托盘常驻\n\n"
        f"需要配合 ssubb-worker 可执行文件使用。\n"
        f"将 ssubb-launcher 和 ssubb-worker 放在同一目录下。\n\n"
        f"更多文档: https://github.com/Magnoliar/SSUBB\n",
        encoding="utf-8",
    )

    print(f"\n[build] Done!")
    for item in sorted(output_dir.iterdir()):
        print(f"  {item.name}")


def main():
    parser = argparse.ArgumentParser(description="Build SSUBB Launcher with PyInstaller")
    parser.add_argument("--onefile", action="store_true", help="Build as single file")
    parser.add_argument("--output-dir", default="dist/launcher", help="Output directory")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
