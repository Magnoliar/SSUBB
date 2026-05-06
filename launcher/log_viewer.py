"""实时日志面板

深色终端风格，支持过滤、着色、自动滚动。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from launcher.theme import Colors, Fonts

MAX_LINES = 5000
TRIM_LINES = 1000


class LogViewer(QWidget):
    """实时日志查看器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # 日志标题
        title = QLabel("实时日志")
        title.setStyleSheet(f"{Fonts.heading(13)} color: {Colors.TEXT_PRIMARY};")
        toolbar.addWidget(title)

        toolbar.addStretch()

        # 搜索
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("搜索...")
        self._filter_input.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 4px 10px;
                {Fonts.mono(11)}
                max-width: 160px;
            }}
            QLineEdit:focus {{
                border-color: {Colors.AMBER};
            }}
        """)
        self._filter_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._filter_input)

        # 级别过滤
        self._level_filter = QComboBox()
        self._level_filter.addItems(["All", "INFO", "WARNING", "ERROR"])
        self._level_filter.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 4px 8px;
                {Fonts.body(11)}
                max-width: 90px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid {Colors.TEXT_SECONDARY};
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                selection-background-color: {Colors.AMBER_DIM};
            }}
        """)
        self._level_filter.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._level_filter)

        # 自动滚动
        self._auto_scroll = QCheckBox("自动滚动")
        self._auto_scroll.setChecked(True)
        self._auto_scroll.setStyleSheet(f"""
            QCheckBox {{
                color: {Colors.TEXT_SECONDARY};
                {Fonts.body(11)}
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 3px;
                background: {Colors.SURFACE};
            }}
            QCheckBox::indicator:checked {{
                background: {Colors.AMBER};
                border-color: {Colors.AMBER};
            }}
        """)
        toolbar.addWidget(self._auto_scroll)

        # 清空
        clear_btn = QPushButton("清空")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Colors.TEXT_MUTED};
                border: none;
                {Fonts.body(11)}
                padding: 4px 8px;
            }}
            QPushButton:hover {{ color: {Colors.RED}; }}
        """)
        clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # 日志文本区
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.VOID};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 8px;
                {Fonts.mono(11)}
                selection-background-color: {Colors.AMBER_DIM};
            }}
        """)
        layout.addWidget(self._text)

    def append_line(self, line: str):
        self._lines.append(line)

        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[TRIM_LINES:]
            self._refresh_display()
            return

        if self._matches_filter(line):
            self._append_colored(line)
            if self._auto_scroll.isChecked():
                self._scroll_to_end()

    def clear(self):
        self._lines.clear()
        self._text.clear()

    def _refresh_display(self):
        self._text.clear()
        text_filter = self._filter_input.text().lower()
        level_filter = self._level_filter.currentText()
        for line in self._lines:
            if self._matches_filter(line, text_filter, level_filter):
                self._append_colored(line)
        if self._auto_scroll.isChecked():
            self._scroll_to_end()

    def _matches_filter(self, line, text_filter=None, level_filter=None):
        if text_filter is None:
            text_filter = self._filter_input.text().lower()
        if level_filter is None:
            level_filter = self._level_filter.currentText()
        if text_filter and text_filter not in line.lower():
            return False
        if level_filter != "All" and level_filter not in line:
            return False
        return True

    def _append_colored(self, line: str):
        if "ERROR" in line or "CRITICAL" in line:
            color = Colors.RED
        elif "WARNING" in line:
            color = Colors.YELLOW
        elif "DEBUG" in line:
            color = Colors.TEXT_MUTED
        else:
            color = Colors.TEXT_PRIMARY

        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._text.append(f'<span style="color:{color}">{escaped}</span>')

    def _scroll_to_end(self):
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _apply_filter(self):
        self._refresh_display()
