"""SSUBB Worker 启动器入口

用法:
    python -m launcher              # 启动 GUI（需要 PySide6）
    python -m launcher --no-gui     # 强制 CLI 模式
    python -m launcher --config X   # 指定配置文件
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="SSUBB Worker Launcher")
    parser.add_argument("--no-gui", action="store_true", help="Force CLI mode")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    args = parser.parse_args()

    if args.no_gui:
        _run_cli(args.config)
        return

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 not installed. Falling back to CLI mode.")
        print("For GUI mode: pip install PySide6\n")
        _run_cli(args.config)
        return

    from launcher.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SSUBB Worker")
    app.setStyle("Fusion")

    config_path = args.config

    # 首次运行检测：没有 config.yaml 时显示 OOBE 向导
    if config_path:
        config_file = Path(config_path)
    else:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
        config_file = base / "config.yaml"
    if not config_file.exists():
        from launcher.oobe import OOBEWizard
        wizard = OOBEWizard()
        if wizard.exec() != OOBEWizard.DialogCode.Accepted:
            sys.exit(0)

    window = MainWindow(config_path=config_path)
    window.show()

    sys.exit(app.exec())


def _run_cli(config_path=None):
    """CLI fallback: run setup wizard then start worker directly."""
    import subprocess

    print("=== SSUBB Worker CLI ===\n")

    if config_path:
        config = Path(config_path)
    else:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
        config = base / "config.yaml"

    if not config.exists():
        print("No config.yaml found. Running setup wizard...\n")
        if getattr(sys, "frozen", False):
            print("ERROR: Setup wizard not available in frozen mode.")
            print("Please create config.yaml manually or use the GUI launcher.")
            sys.exit(1)
        subprocess.run([sys.executable, "-m", "worker.setup_wizard"])

    print("\nStarting Worker...")
    from worker.config import load_worker_config
    cfg = load_worker_config(str(config) if config.exists() else None)

    if getattr(sys, "frozen", False):
        # 冻结模式：直接导入并运行 worker
        import uvicorn
        from worker.main import app
        uvicorn.run(app, host=cfg.host, port=cfg.port, reload=False)
    else:
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "worker.main:app",
            "--host", cfg.host,
            "--port", str(cfg.port),
        ])


if __name__ == "__main__":
    main()
