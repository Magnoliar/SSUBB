"""SSUBB Worker 启动器主窗口

电影级暗色主题，卡片式布局，流畅动画。
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from launcher.env_check_panel import EnvCheckPanel
from launcher.log_viewer import LogViewer
from launcher.service import ServiceManager
from launcher import theme
from launcher.theme import Colors, STATUS_COLORS, STATUS_LABELS, STATUS_ICONS


class StatusCard(QFrame):
    """顶部状态卡片：服务状态 + 控制按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"""
            QFrame#card {{
                background-color: {Colors.PANEL};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 12px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 状态指示灯
        self._dot = QLabel("●")
        self._dot.setFixedSize(32, 32)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setStyleSheet(f"color: {Colors.RED}; font-size: 24px; background: transparent;")
        layout.addWidget(self._dot)

        # 状态文字
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self._status_label = QLabel("已停止")
        self._status_label.setStyleSheet(f"{theme.Fonts.heading(16)} color: {Colors.TEXT_PRIMARY}; background: transparent;")
        info_layout.addWidget(self._status_label)

        self._detail_label = QLabel("Worker 服务未运行")
        self._detail_label.setStyleSheet(f"{theme.Fonts.body(11)} color: {Colors.TEXT_SECONDARY}; background: transparent;")
        info_layout.addWidget(self._detail_label)
        layout.addLayout(info_layout, 1)

        # 控制按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._start_btn = QPushButton("  启动")
        self._start_btn.setStyleSheet(theme.BUTTON_PRIMARY)
        self._start_btn.setMinimumWidth(80)
        btn_layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("  停止")
        self._stop_btn.setStyleSheet(theme.BUTTON_DANGER)
        self._stop_btn.setMinimumWidth(80)
        self._stop_btn.setEnabled(False)
        btn_layout.addWidget(self._stop_btn)

        self._restart_btn = QPushButton("  重启")
        self._restart_btn.setStyleSheet(theme.BUTTON_SECONDARY)
        self._restart_btn.setMinimumWidth(80)
        self._restart_btn.setEnabled(False)
        btn_layout.addWidget(self._restart_btn)

        layout.addLayout(btn_layout)

    def update_status(self, status):
        color = STATUS_COLORS.get(status, Colors.TEXT_MUTED)
        label = STATUS_LABELS.get(status, status)
        icon = STATUS_ICONS.get(status, "?")

        self._dot.setText("●")
        self._dot.setStyleSheet(f"color: {color}; font-size: 24px; background: transparent;")

        self._status_label.setText(f"{icon}  {label}")
        self._status_label.setStyleSheet(f"{theme.Fonts.heading(16)} color: {color}; background: transparent;")

        details = {
            "stopped": "Worker 服务未运行",
            "starting": "正在启动 Worker 进程...",
            "running": "Worker 正在接收和处理任务",
            "error": "Worker 进程异常退出",
        }
        self._detail_label.setText(details.get(status, ""))

        is_running = status == "running"
        is_stopped = status in ("stopped", "error")
        self._start_btn.setEnabled(is_stopped)
        self._stop_btn.setEnabled(is_running)
        self._restart_btn.setEnabled(is_running)


class HeaderBar(QWidget):
    """顶部标题栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)

        # Logo 文字
        logo = QLabel("SSUBB")
        logo.setStyleSheet(f"""
            {theme.Fonts.heading(20, '800')}
            color: {Colors.AMBER};
            letter-spacing: 3px;
            background: transparent;
        """)
        layout.addWidget(logo)

        subtitle = QLabel("Worker Launcher")
        subtitle.setStyleSheet(f"""
            {theme.Fonts.body(12)}
            color: {Colors.TEXT_MUTED};
            padding-top: 4px;
            background: transparent;
        """)
        layout.addWidget(subtitle)

        layout.addStretch()

        # 配置按钮
        self._config_btn = QPushButton("  配置")
        self._config_btn.setStyleSheet(theme.BUTTON_GHOST)
        layout.addWidget(self._config_btn)

        # 版本号
        version = "1.0.0"
        try:
            from shared.constants import VERSION
            version = VERSION
        except Exception:
            pass
        ver = QLabel(f"v{version}")
        ver.setStyleSheet(f"""
            {theme.Fonts.mono(10)}
            color: {Colors.TEXT_MUTED};
            padding: 4px 8px;
            background: {Colors.ELEVATED};
            border-radius: 4px;
        """)
        layout.addWidget(ver)


class MainWindow(QMainWindow):
    """Worker 启动器主窗口。"""

    def __init__(self, config_path=None, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self.setWindowTitle("SSUBB Worker Launcher")
        self.setMinimumSize(800, 650)
        self.resize(900, 700)
        self.setStyleSheet(theme.MAIN_WINDOW + theme.SCROLLBAR)

        self._service = ServiceManager(config_path=config_path, parent=self)
        self._tray_manager = None

        self._setup_ui()
        self._connect_signals()

        # 首次自动运行环境检测
        QTimer.singleShot(500, self._env_panel.run_checks)
        # 延迟检查更新
        QTimer.singleShot(3000, self._check_update)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 标题栏 ──
        self._header = HeaderBar()
        main_layout.addWidget(self._header)

        # ── 内容区域 ──
        content = QWidget()
        content.setStyleSheet(f"background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 8, 20, 20)
        content_layout.setSpacing(12)

        # 状态卡片
        self._status_card = StatusCard()
        content_layout.addWidget(self._status_card)

        # 环境检测卡片
        env_card = QFrame()
        env_card.setObjectName("card")
        env_card.setStyleSheet(f"""
            QFrame#card {{
                background-color: {Colors.PANEL};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 12px;
            }}
        """)
        env_layout = QVBoxLayout(env_card)
        env_layout.setContentsMargins(16, 12, 16, 12)
        self._env_panel = EnvCheckPanel(config_path=self._config_path)
        env_layout.addWidget(self._env_panel)
        content_layout.addWidget(env_card)

        # 日志卡片（占据剩余空间）
        log_card = QFrame()
        log_card.setObjectName("card")
        log_card.setStyleSheet(f"""
            QFrame#card {{
                background-color: {Colors.PANEL};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 12px;
            }}
        """)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(12, 8, 12, 12)
        self._log_viewer = LogViewer()
        log_layout.addWidget(self._log_viewer)
        content_layout.addWidget(log_card, 1)  # stretch=1

        main_layout.addWidget(content, 1)

    def _connect_signals(self):
        # Status card buttons
        self._status_card._start_btn.clicked.connect(self._service.start)
        self._status_card._stop_btn.clicked.connect(self._service.stop)
        self._status_card._restart_btn.clicked.connect(self._service.restart)

        # Service signals
        self._service.status_changed.connect(self._on_status_changed)
        self._service.log_line.connect(self._log_viewer.append_line)

        # Header config button
        self._header._config_btn.clicked.connect(self._open_config)

    def _on_status_changed(self, status):
        self._status_card.update_status(status)
        if self._tray_manager:
            self._tray_manager.update_status(status)

    def _open_config(self):
        from launcher.config_ui import ConfigDialog
        dlg = ConfigDialog(config_path=self._config_path, parent=self)
        if dlg.exec() == ConfigDialog.DialogCode.Accepted:
            QMessageBox.information(
                self, "配置已保存",
                "配置已保存。如果 Worker 正在运行，建议重启以使配置生效。",
            )

    def _check_update(self):
        try:
            from launcher.updater import UpdateChecker
            self._updater = UpdateChecker(parent=self)
            self._updater.update_available.connect(self._on_update_available)
            self._updater.check()
        except Exception:
            pass

    def _on_update_available(self, version, url, body):
        from PySide6.QtWidgets import QMessageBox as MB
        reply = MB.information(
            self, "发现新版本",
            f"新版本 v{version} 可用。\n\n{body[:300]}\n\n"
            f"点击「下载更新」将自动下载并替换当前版本。\n"
            f"点击「手动下载」将在浏览器中打开下载页面。",
            MB.StandardButton.Yes | MB.StandardButton.No | MB.StandardButton.Ignore,
            MB.StandardButton.Yes,
        )

        if reply == MB.StandardButton.Yes:
            # 打开浏览器下载
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        elif reply == MB.StandardButton.No:
            # 手动下载
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))

    def closeEvent(self, event):
        if self._tray_manager and self._tray_manager.is_visible():
            self.hide()
            event.ignore()
        elif self._service.status == "running":
            reply = QMessageBox.question(
                self, "确认退出",
                "Worker 正在运行，确定要退出吗？\n这将停止 Worker 服务。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._service.stop()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def set_tray_manager(self, tray_manager):
        self._tray_manager = tray_manager


def main():
    """启动器主入口。"""
    app = QApplication(sys.argv)
    app.setApplicationName("SSUBB Worker")
    app.setStyle("Fusion")  # 跨平台一致的渲染引擎

    window = MainWindow()

    # 系统托盘（可选）
    try:
        from launcher.tray import TrayManager
        tray = TrayManager(parent=app)
        if tray.is_available():
            window.set_tray_manager(tray)
            tray.show_action.connect(window.show)
            tray.quit_action.connect(app.quit)
            window._service.status_changed.connect(tray.update_status)
            tray.show()
    except Exception:
        pass

    window.show()
    sys.exit(app.exec())
