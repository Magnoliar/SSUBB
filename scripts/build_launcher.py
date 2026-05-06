"""SSUBB Launcher 构建脚本 (PyInstaller)

将 PySide6 桌面启动器打包为独立可执行文件。
启动器管理 Worker 子进程，本身不含 Worker 逻辑。

用法:
    python scripts/build_launcher.py [--output-dir dist]

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

    # PyInstaller spec
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
# SSUBB Launcher PyInstaller Spec

from pathlib import Path

block_cipher = None
project_root = Path(r'{PROJECT_ROOT}')

a = Analysis(
    [str(project_root / 'launcher' / '__main__.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'shared'), 'shared'),
    ],
    hiddenimports=[
        'shared',
        'shared.constants',
        'shared.models',
        'launcher',
        'launcher.app',
        'launcher.env_check_panel',
        'launcher.service',
        'launcher.config_ui',
        'launcher.log_viewer',
        'launcher.tray',
        'launcher.updater',
        'worker',
        'worker.config',
        'worker.env_check',
        'worker.model_manager',
        'worker.health',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'yaml',
        'pydantic',
        'httpx',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy.testing',
        'scipy',
        'pandas',
        'uvicorn',
        'fastapi',
        'torch',
        'faster_whisper',
        'stable_ts',
        'openai',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ssubb-launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ssubb-launcher',
)
"""

    spec_path = output_dir / "ssubb-launcher.spec"
    spec_path.write_text(spec_content, encoding="utf-8")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_path),
        f"--distpath={output_dir}",
        f"--workpath={output_dir / 'build'}",
        "--clean",
        "--noconfirm",
    ]

    print(f"[build] Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[build] FAILED")
        sys.exit(1)

    dist_dir = output_dir / "ssubb-launcher"
    if not dist_dir.exists():
        dist_dir = output_dir

    exe_name = "ssubb-launcher.exe" if system == "windows" else "ssubb-launcher"
    readme = dist_dir / "README.txt"
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
        f"更多文档: https://github.com/anthropics/ssubb\n",
        encoding="utf-8",
    )

    print(f"\n[build] Done! Package contents:")
    for item in sorted(dist_dir.iterdir()):
        if item.is_dir():
            count = len(list(item.iterdir()))
            print(f"  {item.name}/ ({count} files)")
        else:
            print(f"  {item.name}")

    zip_name = f"ssubb-launcher-{version}-{arch}"
    print(f"\n[build] Creating {zip_name}.zip ...")
    shutil.make_archive(str(output_dir / zip_name), "zip", str(dist_dir))
    print(f"[build] Created: {output_dir / zip_name}.zip")


def main():
    parser = argparse.ArgumentParser(description="Build SSUBB Launcher with PyInstaller")
    parser.add_argument("--output-dir", default="dist/launcher", help="Output directory")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
