"""SSUBB Coordinator 构建脚本 (Nuitka)

使用 Nuitka 将 Coordinator 打包为独立可执行文件。
Nuitka 提供更快的启动速度，适合 NAS 资源受限场景。

用法:
    python scripts/build_coordinator.py [--onefile] [--output-dir dist]

前置条件:
    pip install nuitka ordered-set
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

    # Nuitka 构建参数
    cmd = [
        sys.executable, "-m", "nuitka",
        "--module-name=coordinator",
        f"--output-dir={output_dir}",
        "--standalone",
        "--follow-imports",
        "--include-module=shared",
        "--include-module=shared.constants",
        "--include-module=shared.models",
        "--include-package=coordinator",
        "--include-package=shared",
        # 包含静态文件
        f"--include-data-dir={PROJECT_ROOT / 'coordinator' / 'static'}=coordinator/static",
        # 优化选项
        "--assume-yes-for-downloads",
        "--no-deployment",
        f"--company-name=SSUBB",
        f"--product-name=SSUBB Coordinator",
        f"--product-version={version}",
        f"--file-version={version}",
        "--file-description=SSUBB Coordinator Service",
    ]

    if args.onefile:
        cmd.append("--onefile")

    # 入口点
    cmd.append(str(PROJECT_ROOT / "coordinator" / "main.py"))

    print(f"[build] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[build] FAILED")
        sys.exit(1)

    # 打包产物
    if system == "windows":
        exe_name = "ssubb-coordinator.exe"
        src = output_dir / "coordinator.dist" / "coordinator.exe"
    else:
        exe_name = "ssubb-coordinator"
        src = output_dir / "coordinator.dist" / "coordinator"

    if not src.exists():
        # onefile 模式输出位置不同
        src = output_dir / ("coordinator.exe" if system == "windows" else "coordinator")

    if src.exists():
        dst = output_dir / exe_name
        if src != dst:
            shutil.copy2(src, dst)
        print(f"[build] Output: {dst}")
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
        f"更多文档: https://github.com/anthropics/ssubb\n",
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
    parser = argparse.ArgumentParser(description="Build SSUBB Coordinator with Nuitka")
    parser.add_argument("--onefile", action="store_true", help="Build as single file")
    parser.add_argument("--output-dir", default="dist/coordinator", help="Output directory")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
