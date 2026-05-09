"""SSUBB Worker 启动器主窗口

电影级暗色主题，卡片式布局，流畅动画。
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QBrush, QPen
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
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(theme.MAIN_WINDOW + theme.SCROLLBAR)

        self._service = ServiceManager(config_path=config_path, parent=self)
        self._tray_manager = None
        self._first_start = True
        self._force_quit = False

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
            # 首次启动成功后自动最小化到托盘
            if status == "running" and self.isVisible() and getattr(self, "_first_start", True):
                self._first_start = False
                self.hide()
                self._tray_manager.show_message(
                    "SSUBB Worker", "Worker 已启动，正在后台运行。\n双击托盘图标可重新打开窗口。"
                )

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
            f"点击「下载」将在浏览器中打开下载页面。",
            MB.StandardButton.Yes | MB.StandardButton.No,
            MB.StandardButton.Yes,
        )

        if reply == MB.StandardButton.Yes:
            # 打开浏览器下载
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        # No / Ignore: 关闭对话框，不做任何操作

    def closeEvent(self, event):
        # 强制退出（来自托盘"退出"或 _try_close 超时）
        if getattr(self, "_force_quit", False):
            event.accept()
            return

        # 已在关闭流程中，防止重入
        if getattr(self, "_pending_close", False):
            event.ignore()
            return

        if self._tray_manager and self._tray_manager.is_visible():
            # 托盘可用时，提供三种选择
            if self._service.status in ("running", "starting"):
                box = QMessageBox(self)
                box.setWindowTitle("确认退出")
                box.setText("Worker 正在运行，选择操作：")
                box.setIcon(QMessageBox.Icon.Question)
                btn_minimize = box.addButton("最小化到托盘", QMessageBox.ButtonRole.RejectRole)
                btn_stop_close = box.addButton("停止并退出", QMessageBox.ButtonRole.YesRole)
                btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.NoRole)
                box.exec()
                clicked = box.clickedButton()
                if clicked == btn_stop_close:
                    event.ignore()
                    self._start_close()
                elif clicked == btn_minimize:
                    self.hide()
                    event.ignore()
                else:
                    event.ignore()
            else:
                # Worker 未运行，托盘可用：询问最小化还是退出
                box = QMessageBox(self)
                box.setWindowTitle("关闭窗口")
                box.setText("选择操作：")
                box.setIcon(QMessageBox.Icon.Question)
                btn_minimize = box.addButton("最小化到托盘", QMessageBox.ButtonRole.RejectRole)
                btn_quit = box.addButton("退出", QMessageBox.ButtonRole.YesRole)
                btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.NoRole)
                box.exec()
                clicked = box.clickedButton()
                if clicked == btn_quit:
                    event.accept()
                elif clicked == btn_minimize:
                    self.hide()
                    event.ignore()
                else:
                    event.ignore()
        elif self._service.status in ("running", "starting"):
            reply = QMessageBox.question(
                self, "确认退出",
                "Worker 正在运行，确定要退出吗？\n这将停止 Worker 服务。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                event.ignore()
                self._start_close()
            else:
                event.ignore()
        else:
            event.accept()

    def _start_close(self):
        """启动关闭流程：停止 Worker，轮询等待后退出。"""
        self._pending_close = True
        self._close_attempts = 0
        self._service.stop()
        if not hasattr(self, "_close_timer"):
            self._close_timer = QTimer(self)
            self._close_timer.timeout.connect(self._try_close)
        self._close_timer.start(200)

    def _try_close(self):
        """Worker 停止后强制退出。超时 6 秒也强制退出。"""
        self._close_attempts += 1
        if self._service.status in ("stopped", "error") or self._close_attempts > 30:
            self._close_timer.stop()
            self._force_quit = True
            QApplication.instance().quit()

    def set_tray_manager(self, tray_manager):
        self._tray_manager = tray_manager

    def _force_quit_and_exit(self):
        """托盘退出：跳过确认直接退出"""
        self._force_quit = True
        QApplication.instance().quit()


def _create_app_icon() -> QIcon:
    """生成应用图标（琥珀色 S 字母）"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 背景圆
    painter.setBrush(QBrush(QColor(Colors.AMBER)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 60, 60)
    # S 字母
    painter.setPen(QPen(QColor(Colors.VOID)))
    font = QFont("Arial", 32, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    painter.end()
    return QIcon(pixmap)


def main():
    """启动器主入口。"""
    app = QApplication(sys.argv)
    app.setApplicationName("SSUBB Worker")
    app.setStyle("Fusion")  # 跨平台一致的渲染引擎
    app.setWindowIcon(_create_app_icon())

    window = MainWindow()

    # 系统托盘（可选）
    try:
        from launcher.tray import TrayManager
        tray = TrayManager(parent=app)
        if tray.is_available():
            window.set_tray_manager(tray)
            tray.show_action.connect(window.show)
            tray.start_worker.connect(window._service.start)
            tray.stop_worker.connect(window._service.stop)
            tray.quit_action.connect(window._force_quit_and_exit)
            window._service.status_changed.connect(tray.update_status)
            tray.show()
    except Exception:
        pass

    window.show()
    sys.exit(app.exec())
