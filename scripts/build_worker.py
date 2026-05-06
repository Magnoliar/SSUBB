"""SSUBB Worker 构建脚本 (PyInstaller)

使用 PyInstaller 将 Worker 打包为独立可执行文件。
PyInstaller 的 hook 机制更适合处理 GPU 相关依赖链。

用法:
    python scripts/build_worker.py [--onefile] [--output-dir dist]

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


def detect_cuda_version() -> str:
    """检测系统 CUDA 版本"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            # 进一步检查 CUDA 版本
            result2 = subprocess.run(
                ["nvidia-smi"],
                capture_output=True, text=True, timeout=5,
            )
            output = result2.stdout
            if "CUDA Version: 12" in output:
                return "cuda12"
            elif "CUDA Version: 11" in output:
                return "cuda11"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "cpu"


def build(args):
    version = get_version()
    system = platform.system().lower()
    cuda = detect_cuda_version()
    arch = "win64" if system == "windows" else "linux-x64"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build] SSUBB Worker v{version}")
    print(f"[build] Platform: {system} ({arch})")
    print(f"[build] CUDA: {cuda}")
    print(f"[build] Output: {output_dir}")

    # PyInstaller spec 内容
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
# SSUBB Worker PyInstaller Spec

import sys
from pathlib import Path

block_cipher = None
project_root = Path(r'{PROJECT_ROOT}')

a = Analysis(
    [str(project_root / 'worker' / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'shared'), 'shared'),
    ],
    hiddenimports=[
        'shared',
        'shared.constants',
        'shared.models',
        'worker',
        'worker.config',
        'worker.task_executor',
        'worker.translator',
        'worker.optimizer',
        'worker.annotator',
        'worker.srt_parser',
        'worker.llm_client',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'pydantic',
        'httpx',
        'yaml',
        'openai',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy.testing',
        'scipy',
        'pandas',
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
    name='ssubb-worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='ssubb-worker',
)
"""

    spec_path = output_dir / "ssubb-worker.spec"
    spec_path.write_text(spec_content, encoding="utf-8")

    # 运行 PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_path),
        f"--distpath={output_dir}",
        f"--workpath={output_dir / 'build'}",
        "--clean",
        "--noconfirm",
    ]

    if args.onefile:
        cmd.append("--onefile")

    print(f"[build] Running PyInstaller...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("[build] FAILED")
        sys.exit(1)

    # 产物目录
    dist_dir = output_dir / "ssubb-worker"
    if not dist_dir.exists():
        dist_dir = output_dir

    # 创建 README
    readme = dist_dir / "README.txt"
    exe_name = "ssubb-worker.exe" if system == "windows" else "ssubb-worker"
    readme.write_text(
        f"SSUBB Worker v{version} ({cuda})\n"
        f"{'=' * 40}\n\n"
        f"快速启动:\n"
        f"  1. 双击 {exe_name} 启动 Worker\n"
        f"  2. 首次运行会自动生成 config.yaml 并引导配置\n"
        f"  3. Whisper 模型会在首次任务时自动下载\n\n"
        f"前置要求:\n"
        f"  - NVIDIA GPU + CUDA 驱动\n"
        f"  - Coordinator 地址 (在 config.yaml 中配置)\n\n"
        f"配置文件: config.yaml (首次运行自动生成)\n"
        f"模型目录: models/ (自动创建)\n\n"
        f"更多文档: https://github.com/anthropics/ssubb\n",
        encoding="utf-8",
    )

    # 创建空目录
    for d in ["data", "models"]:
        (dist_dir / d).mkdir(parents=True, exist_ok=True)

    print(f"\n[build] Done! Package contents:")
    for item in sorted(dist_dir.iterdir()):
        if item.is_dir():
            count = len(list(item.iterdir()))
            print(f"  {item.name}/ ({count} files)")
        else:
            print(f"  {item.name}")

    # 打包为 zip
    zip_name = f"ssubb-worker-{version}-{arch}-{cuda}"
    print(f"\n[build] Creating {zip_name}.zip ...")
    shutil.make_archive(str(output_dir / zip_name), "zip", str(dist_dir))
    print(f"[build] Created: {output_dir / zip_name}.zip")


def main():
    parser = argparse.ArgumentParser(description="Build SSUBB Worker with PyInstaller")
    parser.add_argument("--onefile", action="store_true", help="Build as single file")
    parser.add_argument("--output-dir", default="dist/worker", help="Output directory")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
