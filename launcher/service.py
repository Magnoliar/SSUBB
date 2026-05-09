"""Worker 子进程管理

启动/停止/重启 Worker 服务，捕获日志输出。
支持：端口探测、已有 Worker 接管、进程树杀死、健康检查轮询。
"""

import os
import socket
import subprocess
import sys
import urllib.request
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
        self._health_poll_count = 0
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._poll_health)

    @property
    def status(self):
        return self._status

    def _set_status(self, status):
        if self._status != status:
            self._status = status
            self.status_changed.emit(status)

    # =========================================================================
    # 启动
    # =========================================================================

    def _find_worker_cmd(self):
        """确定 Worker 启动命令。"""
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            worker_exe = exe_dir / ("ssubb-worker.exe" if os.name == "nt" else "ssubb-worker")
            if worker_exe.exists():
                return str(worker_exe), []
        return sys.executable, ["-m", "uvicorn", "worker.main:app"]

    def _get_port(self):
        """从配置读取端口号。"""
        try:
            from worker.config import load_worker_config
            config = load_worker_config(self._config_path)
            return int(config.port)
        except Exception:
            return 8788

    def _is_port_open(self, port: int) -> bool:
        """检测端口是否有进程监听。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _check_existing_worker(self, port: int) -> bool:
        """检测端口上是否已有 SSUBB Worker 在运行。"""
        if not self._is_port_open(port):
            return False
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/status", timeout=3
            )
            return resp.status == 200
        except Exception:
            return False

    def start(self):
        if self._status in ("running", "starting"):
            return

        # 清理上一次残留的 QProcess（error 状态后重试）
        if self._process is not None:
            try:
                self._process.finished.disconnect()
                self._process.errorOccurred.disconnect()
                self._process.readyReadStandardOutput.disconnect()
            except Exception:
                pass
            try:
                self._process.kill()
            except Exception:
                pass
            self._process.deleteLater()
            self._process = None

        port = self._get_port()

        # 检测端口状态
        if self._check_existing_worker(port):
            self.log_line.emit(f"[Launcher] 检测到已有 Worker 运行在端口 {port}，接管监控")
            self._set_status("running")
            return

        if self._is_port_open(port):
            self._set_status("error")
            self.log_line.emit(f"[Launcher] 端口 {port} 已被其他程序占用，请检查或更换端口")
            return

        self._set_status("starting")

        cmd, base_args = self._find_worker_cmd()
        args = base_args + ["--host", "0.0.0.0", "--port", str(port)]

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

        if self._config_path:
            self._process.setProcessEnvironment(self._make_env())

        self._process.start(cmd, args)

        # 启动成功检测：轮询 /api/status
        self._health_poll_count = 0
        self._health_timer.start(500)

    def _make_env(self):
        from PySide6.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SSUBB_CONFIG", self._config_path)
        env.insert("PYTHONIOENCODING", "utf-8")
        return env

    def _poll_health(self):
        """每 500ms 轮询 Worker /api/status，最多 15 秒。"""
        self._health_poll_count += 1

        if self._status != "starting":
            self._health_timer.stop()
            return

        port = self._get_port()
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/status", timeout=1
            )
            if resp.status == 200:
                self._health_timer.stop()
                self._set_status("running")
                self.log_line.emit(f"[Launcher] Worker 已就绪 (端口 {port})")
                return
        except Exception:
            pass

        # 超时 15 秒 (30 次 * 500ms)
        if self._health_poll_count >= 30:
            self._health_timer.stop()
            if self._process and self._process.state() == QProcess.ProcessState.Running:
                # 进程还活着但 HTTP 没响应，继续等
                self.log_line.emit("[Launcher] Worker 启动较慢，继续等待...")
                QTimer.singleShot(5000, self._final_health_check)
            else:
                self._set_status("error")
                self.log_line.emit("[Launcher] Worker 启动失败：进程已退出")

    def _final_health_check(self):
        """额外 5 秒后的最终检查。"""
        if self._status != "starting":
            return
        port = self._get_port()
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/status", timeout=2
            )
            if resp.status == 200:
                self._set_status("running")
                return
        except Exception:
            pass
        self._set_status("error")
        self.log_line.emit("[Launcher] Worker 启动超时，请检查日志")

    # =========================================================================
    # 停止
    # =========================================================================

    def stop(self):
        if self._status == "stopped":
            return

        self._health_timer.stop()

        # 如果没有本地进程句柄（接管的外部 Worker），用端口探测杀掉
        if not self._process:
            self._kill_by_port(self._get_port())
            self._set_status("stopped")
            return

        try:
            pid = self._process.processId()
            if pid:
                self._kill_process_tree(pid)
            else:
                self._process.kill()
        except Exception:
            self._process.kill()

        # 兜底：500ms 后确认是否已停止
        QTimer.singleShot(500, self._ensure_stopped)

    def _kill_process_tree(self, pid: int):
        """用 taskkill 杀掉整个进程树（Windows）。"""
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                self.log_line.emit(f"[Launcher] 已停止 Worker 进程树 (PID {pid})")
            else:
                self.log_line.emit(f"[Launcher] taskkill 返回: {result.stderr.strip()}")
        except FileNotFoundError:
            # 非 Windows，用 kill
            self._process.kill()
        except subprocess.TimeoutExpired:
            self._process.kill()

    def _kill_by_port(self, port: int):
        """通过端口找到并杀死进程（用于接管的外部 Worker）。"""
        try:
            # Windows: netstat 找 PID
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid.isdigit():
                        subprocess.run(["taskkill", "/F", "/PID", pid],
                                       capture_output=True, timeout=10)
                        self.log_line.emit(f"[Launcher] 已停止占用端口 {port} 的进程 (PID {pid})")
                        return
        except Exception as e:
            self.log_line.emit(f"[Launcher] 无法自动停止外部进程: {e}")

    def _ensure_stopped(self):
        """兜底：确保状态变为 stopped。"""
        if self._status not in ("stopped", "error"):
            if self._process and self._process.state() != QProcess.ProcessState.Running:
                self._set_status("stopped")
                self._process = None
            else:
                # 进程还在，再试一次强杀
                if self._process:
                    self._process.kill()
                QTimer.singleShot(500, self._force_stopped_fallback)

    def _force_stopped_fallback(self):
        """最终兜底。"""
        if self._status not in ("stopped", "error"):
            self._set_status("stopped")
            self._process = None
            self.log_line.emit("[Launcher] 强制停止完成")

    # =========================================================================
    # 重启
    # =========================================================================

    def restart(self):
        if not self._process or self._status == "stopped":
            self.start()
            return
        self._restart_pending = True
        try:
            self._process.finished.disconnect(self._delayed_start)
        except (RuntimeError, TypeError):
            pass
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

    # =========================================================================
    # 进程事件
    # =========================================================================

    def _on_stdout(self):
        if not self._process:
            return
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._partial_line += data
        while "\n" in self._partial_line:
            line, self._partial_line = self._partial_line.split("\n", 1)
            line = line.rstrip()
            self.log_line.emit(line)
            # 检测关键错误
            lower = line.lower()
            if "address already in use" in lower or "10048" in lower:
                self._health_timer.stop()
                self._set_status("error")
                self.log_line.emit(f"[Launcher] 端口冲突：{line.strip()}")

    def _on_finished(self, exit_code, exit_status):
        self._health_timer.stop()
        if self._status == "error":
            pass  # 已由 _on_error 或 _on_stdout 设置，不覆盖
        elif exit_code != 0:
            self._set_status("error")
            self.log_line.emit(f"[Launcher] Worker 异常退出 (代码 {exit_code})")
        else:
            self._set_status("stopped")
        self._process = None

    def _on_error(self, error):
        self._health_timer.stop()
        self._set_status("error")
        self.log_line.emit(f"[Launcher] 进程错误: {error}")
