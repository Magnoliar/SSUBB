"""系统托盘集成

托盘图标、右键菜单、通知气泡。
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from launcher.theme import Colors


def _make_icon(color: str) -> QIcon:
    """生成带发光效果的圆形图标。"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 外圈发光
    painter.setBrush(QColor(color))
    painter.setPen(QColor("transparent"))
    painter.drawEllipse(8, 8, 48, 48)

    # 内圈
    inner = QColor(color)
    inner.setAlpha(200)
    painter.setBrush(inner)
    painter.drawEllipse(16, 16, 32, 32)

    painter.end()
    return QIcon(pixmap)


class TrayManager(QObject):
    """系统托盘管理。"""

    show_action = Signal()
    quit_action = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(self)
        self._menu = QMenu()
        self._menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Colors.ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 8px;
                padding: 4px;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 8px 24px 8px 16px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {Colors.AMBER_DIM};
                color: {Colors.AMBER};
            }}
            QMenu::separator {{
                height: 1px;
                background: {Colors.BORDER_DIM};
                margin: 4px 8px;
            }}
        """)

        self._show_action = QAction("显示窗口")
        self._show_action.triggered.connect(self.show_action.emit)
        self._menu.addAction(self._show_action)

        self._menu.addSeparator()

        self._toggle_action = QAction("启动 Worker")
        self._toggle_action.triggered.connect(self._on_toggle)
        self._menu.addAction(self._toggle_action)

        self._menu.addSeparator()

        quit_action = QAction("退出")
        quit_action.triggered.connect(self.quit_action.emit)
        self._menu.addAction(quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

        self._status = "stopped"
        self.update_status("stopped")

    def is_available(self):
        return QSystemTrayIcon.isSystemTrayAvailable()

    def is_visible(self):
        return self._tray.isVisible()

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def update_status(self, status):
        self._status = status
        if status == "running":
            self._tray.setIcon(_make_icon(Colors.GREEN))
            self._tray.setToolTip("SSUBB Worker · 运行中")
            self._toggle_action.setText("停止 Worker")
        elif status == "starting":
            self._tray.setIcon(_make_icon(Colors.YELLOW))
            self._tray.setToolTip("SSUBB Worker · 启动中")
            self._toggle_action.setText("停止 Worker")
        elif status == "error":
            self._tray.setIcon(_make_icon(Colors.RED))
            self._tray.setToolTip("SSUBB Worker · 错误")
            self._toggle_action.setText("启动 Worker")
            self._tray.showMessage("SSUBB Worker", "Worker 发生错误", QSystemTrayIcon.MessageIcon.Critical)
        else:
            self._tray.setIcon(_make_icon(Colors.TEXT_MUTED))
            self._tray.setToolTip("SSUBB Worker · 已停止")
            self._toggle_action.setText("启动 Worker")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_action.emit()

    def _on_toggle(self):
        self.show_action.emit()
