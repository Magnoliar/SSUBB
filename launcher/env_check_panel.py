"""环境检测面板

卡片式环境检测结果展示，复用 worker/env_check.py。
"""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from launcher.theme import Colors, Fonts


class _CheckWorker(QThread):
    """后台线程运行环境检测。"""

    finished = Signal(list)

    def __init__(self, config_path=None):
        super().__init__()
        self._config_path = config_path

    def run(self):
        try:
            from worker.env_check import run_full_check
            from worker.config import load_worker_config
            try:
                config = load_worker_config(self._config_path)
                results = run_full_check(config)
            except Exception:
                results = run_full_check()
        except Exception as e:
            try:
                from worker.env_check import EnvCheckResult
                results = [EnvCheckResult("Import", False, str(e))]
            except Exception:
                # worker 模块完全不可用，构造简单结果
                class _FallbackResult:
                    def __init__(self, name, passed, detail, required=True):
                        self.name = name
                        self.passed = passed
                        self.detail = detail
                        self.required = required
                results = [_FallbackResult("Import", False, str(e))]
        self.finished.emit(results)


class CheckRow(QWidget):
    """单个检测项行。"""

    def __init__(self, name="", detail="", passed=True, required=True, parent=None):
        super().__init__(parent)
        self._setup_ui(name, detail, passed, required)

    def _setup_ui(self, name, detail, passed, required):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # 状态图标
        if passed:
            icon_text = "✓"
            icon_color = Colors.GREEN
            bg = Colors.GREEN_DIM
        elif required:
            icon_text = "✕"
            icon_color = Colors.RED
            bg = Colors.RED_DIM
        else:
            icon_text = "!"
            icon_color = Colors.YELLOW
            bg = "#2a2a0f"

        icon = QLabel(icon_text)
        icon.setFixedSize(22, 22)
        from PySide6.QtCore import Qt
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"""
            color: {icon_color};
            {Fonts.heading(12)}
            background-color: {bg};
            border-radius: 11px;
        """)
        layout.addWidget(icon)

        # 名称
        name_label = QLabel(name)
        name_label.setFixedWidth(130)
        name_label.setStyleSheet(f"{Fonts.body(12)} color: {Colors.TEXT_PRIMARY}; font-weight: 500;")
        layout.addWidget(name_label)

        # 详情
        detail_label = QLabel(detail)
        detail_label.setStyleSheet(f"{Fonts.body(11)} color: {Colors.TEXT_SECONDARY};")
        detail_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(detail_label, 1)

        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)


class EnvCheckPanel(QWidget):
    """环境检测结果面板。"""

    def __init__(self, config_path=None, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._worker = None
        self._rows = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 标题行
        header = QHBoxLayout()
        title = QLabel("环境检测")
        title.setStyleSheet(f"{Fonts.heading(13)} color: {Colors.TEXT_PRIMARY};")
        header.addWidget(title)
        header.addStretch()

        self._refresh_btn = QPushButton("  刷新")
        self._refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 4px 12px;
                {Fonts.body(11)}
            }}
            QPushButton:hover {{
                color: {Colors.AMBER};
                border-color: {Colors.AMBER}44;
            }}
        """)
        self._refresh_btn.clicked.connect(self.run_checks)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # 结果容器
        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(0)
        layout.addWidget(self._results_widget)

        # 占位
        self._placeholder = QLabel("点击「刷新」检测运行环境")
        from PySide6.QtCore import Qt
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"""
            {Fonts.body(12)}
            color: {Colors.TEXT_MUTED};
            padding: 20px;
        """)
        self._results_layout.addWidget(self._placeholder)

        layout.addStretch()

    def run_checks(self):
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("  检测中...")
        self._clear_results()

        self._worker = _CheckWorker(self._config_path)
        self._worker.finished.connect(self._on_checks_done)
        self._worker.start()

    def _on_checks_done(self, results):
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("  刷新")
        self._display_results(results)

    def _display_results(self, results):
        self._clear_results()
        for r in results:
            row = CheckRow(
                name=r.name,
                detail=r.detail,
                passed=r.passed,
                required=r.required,
            )
            self._rows.append(row)
            self._results_layout.addWidget(row)

    def _clear_results(self):
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        # 也清空 placeholder
        if self._placeholder:
            self._placeholder.deleteLater()
            self._placeholder = None
