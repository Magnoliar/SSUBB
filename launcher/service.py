"""Worker 子进程管理

启动/停止/重启 Worker 服务，捕获日志输出。
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class ServiceManager(QObject):
    """管理 Worker 子进程的生命周期。"""

    status_changed = Signal(str)  # "stopped" | "starting" | "running" | "error"
    log_line = Signal(str)

    def __init__(self, config_path=None, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._process = None
        self._status = "stopped"
        self._partial_line = ""

    @property
    def status(self):
        return self._status

    def _set_status(self, status):
        if self._status != status:
            self._status = status
            self.status_changed.emit(status)

    def _find_worker_cmd(self):
        """确定 Worker 启动命令。"""
        if getattr(sys, "frozen", False):
            # 打包模式：找同目录下的 ssubb-worker 可执行文件
            exe_dir = Path(sys.executable).parent
            if os.name == "nt":
                worker_exe = exe_dir / "ssubb-worker.exe"
            else:
                worker_exe = exe_dir / "ssubb-worker"
            if worker_exe.exists():
                return str(worker_exe), []
            # fallback: 用当前 python 启动 worker 模块
        # 开发模式
        return sys.executable, ["-m", "uvicorn", "worker.main:app"]

    def _get_port(self):
        """从配置读取端口号。"""
        try:
            from worker.config import load_worker_config
            config = load_worker_config(self._config_path)
            return str(config.port)
        except Exception:
            return "8788"

    def start(self):
        if self._status == "running":
            return

        self._set_status("starting")

        cmd, base_args = self._find_worker_cmd()
        port = self._get_port()
        args = base_args + ["--host", "0.0.0.0", "--port", port]

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

        if self._config_path:
            self._process.setProcessEnvironment(self._make_env())

        self._process.start(cmd, args)

        # 启动超时检测：3s 后如果进程仍在运行，认为启动成功
        QTimer.singleShot(3000, self._check_running)

    def _make_env(self):
        from PySide6.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SSUBB_CONFIG", self._config_path)
        env.insert("PYTHONIOENCODING", "utf-8")
        return env

    def _check_running(self):
        if self._status == "starting" and self._process and self._process.state() == QProcess.ProcessState.Running:
            self._set_status("running")

    def stop(self):
        if not self._process or self._status == "stopped":
            return

        self._process.terminate()

        # 5s 后如果还没退出，强制杀掉
        QTimer.singleShot(5000, self._force_kill)

    def _force_kill(self):
        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self.log_line.emit("[Launcher] Force killing worker process...")
            self._process.kill()

    def restart(self):
        if not self._process or self._status == "stopped":
            self.start()
            return
        self._restart_pending = True
        self._process.finished.connect(self._delayed_start)
        self.stop()

    def _delayed_start(self, exit_code=0, exit_status=0):
        if self._process:
            try:
                self._process.finished.disconnect(self._delayed_start)
            except RuntimeError:
                pass
        if getattr(self, "_restart_pending", False):
            self._restart_pending = False
            QTimer.singleShot(500, self.start)

    def _on_stdout(self):
        if not self._process:
            return
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._partial_line += data
        while "\n" in self._partial_line:
            line, self._partial_line = self._partial_line.split("\n", 1)
            self.log_line.emit(line.rstrip())

    def _on_finished(self, exit_code, exit_status):
        self._set_status("stopped")
        if exit_code != 0:
            self.log_line.emit(f"[Launcher] Worker exited with code {exit_code}")
        self._process = None

    def _on_error(self, error):
        self._set_status("error")
        self.log_line.emit(f"[Launcher] Process error: {error}")
