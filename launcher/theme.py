"""SSUBB Launcher 视觉主题

电影级暗色主题，与 WebUI 视觉语言一致。
所有颜色、字体、动画、QSS 样式集中管理。
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor


# ══════════════════════════════════════════════════════════════
# 色彩系统
# ══════════════════════════════════════════════════════════════

class Colors:
    # 背景层级
    VOID = "#06070a"           # 最深背景
    SURFACE = "#0c0e13"        # 主背景
    PANEL = "#0e1118"          # 面板背景
    ELEVATED = "#161a24"       # 悬浮/卡片
    HOVER = "#1c2030"          # 悬停态
    ACTIVE = "#252a38"         # 按下态

    # 边框
    BORDER_SUBTLE = "#1a1e28"
    BORDER_DIM = "#252a38"
    BORDER_FOCUS = "#f5a623"

    # 文字
    TEXT_PRIMARY = "#e8eaed"
    TEXT_SECONDARY = "#8b919a"
    TEXT_MUTED = "#4a4f57"

    # 强调色
    AMBER = "#f5a623"
    AMBER_DIM = "#2a1f0f"
    AMBER_GLOW = "#f5a62366"
    CYAN = "#3ecfcf"
    CYAN_DIM = "#0f2a2a"
    RED = "#e54b4b"
    RED_DIM = "#2a0f0f"
    GREEN = "#4ade80"
    GREEN_DIM = "#0f2a1a"
    BLUE = "#6b8afd"
    YELLOW = "#ffd93d"


# ══════════════════════════════════════════════════════════════
# 字体
# ══════════════════════════════════════════════════════════════

class Fonts:
    @staticmethod
    def heading(size=14, weight="bold"):
        return f"font-family: 'Segoe UI', 'Outfit', sans-serif; font-size: {size}px; font-weight: {weight};"

    @staticmethod
    def body(size=12):
        return f"font-family: 'Segoe UI', 'Outfit', sans-serif; font-size: {size}px;"

    @staticmethod
    def mono(size=11):
        return f"font-family: 'Cascadia Code', 'Consolas', 'JetBrains Mono', monospace; font-size: {size}px;"


# ══════════════════════════════════════════════════════════════
# QSS 样式表
# ══════════════════════════════════════════════════════════════

MAIN_WINDOW = f"""
QMainWindow {{
    background-color: {Colors.VOID};
}}
QWidget {{
    color: {Colors.TEXT_PRIMARY};
    font-family: 'Segoe UI', 'Outfit', sans-serif;
    font-size: 12px;
}}
"""

CARD = f"""
QFrame#card {{
    background-color: {Colors.PANEL};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 8px;
}}
"""

BUTTON_PRIMARY = f"""
QPushButton {{
    background-color: {Colors.AMBER};
    color: {Colors.VOID};
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: #ffb833;
}}
QPushButton:pressed {{
    background-color: #d4901e;
}}
QPushButton:disabled {{
    background-color: {Colors.ELEVATED};
    color: {Colors.TEXT_MUTED};
}}
"""

BUTTON_DANGER = f"""
QPushButton {{
    background-color: {Colors.RED_DIM};
    color: {Colors.RED};
    border: 1px solid {Colors.RED}33;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {Colors.RED}33;
    border-color: {Colors.RED}66;
}}
QPushButton:pressed {{
    background-color: {Colors.RED}44;
}}
QPushButton:disabled {{
    background-color: {Colors.ELEVATED};
    color: {Colors.TEXT_MUTED};
    border-color: {Colors.BORDER_SUBTLE};
}}
"""

BUTTON_SECONDARY = f"""
QPushButton {{
    background-color: {Colors.ELEVATED};
    color: {Colors.TEXT_SECONDARY};
    border: 1px solid {Colors.BORDER_DIM};
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {Colors.HOVER};
    color: {Colors.TEXT_PRIMARY};
    border-color: {Colors.AMBER}44;
}}
QPushButton:pressed {{
    background-color: {Colors.ACTIVE};
}}
QPushButton:disabled {{
    background-color: {Colors.SURFACE};
    color: {Colors.TEXT_MUTED};
    border-color: {Colors.BORDER_SUBTLE};
}}
"""

BUTTON_GHOST = f"""
QPushButton {{
    background-color: transparent;
    color: {Colors.TEXT_SECONDARY};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}}
QPushButton:hover {{
    background-color: {Colors.ELEVATED};
    color: {Colors.TEXT_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {Colors.ACTIVE};
}}
"""

INPUT = f"""
QLineEdit, QSpinBox, QComboBox {{
    background-color: {Colors.SURFACE};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DIM};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {Colors.AMBER};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {Colors.TEXT_SECONDARY};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {Colors.ELEVATED};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_DIM};
    selection-background-color: {Colors.AMBER_DIM};
}}
"""

CHECKBOX = f"""
QCheckBox {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {Colors.BORDER_DIM};
    border-radius: 4px;
    background-color: {Colors.SURFACE};
}}
QCheckBox::indicator:checked {{
    background-color: {Colors.AMBER};
    border-color: {Colors.AMBER};
}}
QCheckBox::indicator:hover {{
    border-color: {Colors.AMBER}88;
}}
"""

GROUPBOX = f"""
QGroupBox {{
    background-color: {Colors.PANEL};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 8px;
    margin-top: 16px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    color: {Colors.AMBER};
    background-color: {Colors.PANEL};
}}
"""

SCROLLBAR = f"""
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {Colors.BORDER_DIM};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""

TEXT_EDIT = f"""
QTextEdit {{
    background-color: {Colors.VOID};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 8px;
    padding: 8px;
    font-family: 'Cascadia Code', 'Consolas', 'JetBrains Mono', monospace;
    font-size: 11px;
    selection-background-color: {Colors.AMBER_DIM};
}}
{SCROLLBAR}
"""

LABEL_SECONDARY = f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"
LABEL_MUTED = f"color: {Colors.TEXT_MUTED}; font-size: 11px;"
LABEL_AMBER = f"color: {Colors.AMBER}; font-weight: 600;"


# ══════════════════════════════════════════════════════════════
# 动画工具
# ══════════════════════════════════════════════════════════════

def fade_in(widget, duration=300):
    """淡入动画。"""
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()
    widget._fade_anim = anim  # 防止 GC
    return anim


def pulse_color(widget, prop, color_from, color_to, duration=800):
    """颜色脉冲动画（用于状态指示灯）。"""
    anim = QPropertyAnimation(widget, prop)
    anim.setDuration(duration)
    anim.setStartValue(QColor(color_from))
    anim.setEndValue(QColor(color_to))
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    anim.setLoopCount(-1)  # 无限循环
    anim.start()
    widget._pulse_anim = anim
    return anim


# ══════════════════════════════════════════════════════════════
# 状态映射
# ══════════════════════════════════════════════════════════════

STATUS_COLORS = {
    "stopped": Colors.RED,
    "starting": Colors.YELLOW,
    "running": Colors.GREEN,
    "error": Colors.RED,
}

STATUS_BG = {
    "stopped": Colors.RED_DIM,
    "starting": "#2a2a0f",
    "running": Colors.GREEN_DIM,
    "error": Colors.RED_DIM,
}

STATUS_LABELS = {
    "stopped": "已停止",
    "starting": "启动中",
    "running": "运行中",
    "error": "错误",
}

STATUS_ICONS = {
    "stopped": "■",
    "starting": "◉",
    "running": "▶",
    "error": "✕",
}
