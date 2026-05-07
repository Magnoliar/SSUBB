"""SSUBB Coordinator 构建脚本 (PyInstaller)

使用 PyInstaller 将 Coordinator 打包为独立可执行文件。

用法:
    python scripts/build_coordinator.py [--onefile] [--output-dir dist]

前置条件:
    pip install pyinstaller
"""

import argparse
import platform
import shutil
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
    arch = "win64" if system == "windows" else "linux-x64"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build] SSUBB Coordinator v{version}")
    print(f"[build] Platform: {system} ({arch})")
    print(f"[build] Output: {output_dir}")

    # 静态文件目录
    static_dir = PROJECT_ROOT / "coordinator" / "static"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ssubb-coordinator",
        f"--distpath={output_dir}",
        f"--workpath={output_dir / 'build'}",
        f"--specpath={output_dir}",
        "--noconfirm",
        "--clean",
        # 收集 shared 包
        "--collect-all=shared",
        # 包含 coordinator 包
        "--collect-all=coordinator",
        # 包含静态文件
        f"--add-data={static_dir}{';' if system == 'windows' else ':''}coordinator/static",
    ]

    if args.onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    # 入口点
    cmd.append(str(PROJECT_ROOT / "coordinator" / "main.py"))

    print(f"[build] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[build] FAILED")
        sys.exit(1)

    # 打包产物路径
    if system == "windows":
        exe_name = "ssubb-coordinator.exe"
    else:
        exe_name = "ssubb-coordinator"

    if args.onefile:
        src = output_dir / exe_name
    else:
        src = output_dir / "ssubb-coordinator" / exe_name

    if src.exists():
        print(f"[build] Output: {src}")
    else:
        print(f"[build] Warning: expected output not found at {src}")

    # 创建 README
    readme = output_dir / "README.txt"
    readme.write_text(
        f"SSUBB Coordinator v{version}\n"
        f"{'=' * 40}\n\n"
        f"快速启动:\n"
        f"  1. 双击 {exe_name} 启动服务\n"
        f"  2. 首次运行会自动生成 config.yaml\n"
        f"  3. 浏览器访问 http://localhost:8787 进入 WebUI\n\n"
        f"配置文件: config.yaml (首次运行自动生成)\n"
        f"数据目录: data/ (首次运行自动创建)\n\n"
        f"更多文档: https://github.com/Magnoliar/SSUBB\n",
        encoding="utf-8",
    )

    # 创建空目录结构
    for d in ["data", "data/logs"]:
        (output_dir / d).mkdir(parents=True, exist_ok=True)

    print(f"\n[build] Done! Package contents:")
    for item in sorted(output_dir.iterdir()):
        print(f"  {item.name}")

    # 打包为 zip
    zip_name = f"ssubb-coordinator-{version}-{arch}"
    print(f"\n[build] Creating {zip_name}.zip ...")
    shutil.make_archive(str(output_dir / zip_name), "zip", str(output_dir))
    print(f"[build] Created: {output_dir / zip_name}.zip")


def main():
    parser = argparse.ArgumentParser(description="Build SSUBB Coordinator with PyInstaller")
    parser.add_argument("--onefile", action="store_true", help="Build as single file")
    parser.add_argument("--output-dir", default="dist/coordinator", help="Output directory")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
