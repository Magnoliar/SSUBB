"""首次运行引导 (OOBE)

当 config.yaml 不存在时，引导用户完成初始配置。
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QRadioButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from launcher.theme import Colors, Fonts


class OOBEWizard(QDialog):
    """首次运行配置向导。"""

    config_ready = Signal(dict)  # 完成时发射配置数据

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSUBB Worker · 首次配置")
        self.setMinimumSize(580, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._current_step = 0
        self._config = {}
        self._setup_ui()
        self._apply_style()
        self._goto_step(0)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
            }}
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                {Fonts.body(12)}
            }}
            QLineEdit, QSpinBox, QComboBox {{
                background-color: {Colors.VOID};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 8px;
                padding: 8px 12px;
                {Fonts.body(13)}
            }}
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
                border-color: {Colors.AMBER};
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox::down-arrow {{
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {Colors.TEXT_SECONDARY};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                selection-background-color: {Colors.AMBER_DIM};
            }}
            QRadioButton {{
                color: {Colors.TEXT_PRIMARY};
                spacing: 10px;
                {Fonts.body(12)}
            }}
            QRadioButton::indicator {{
                width: 18px; height: 18px;
                border: 2px solid {Colors.BORDER_DIM};
                border-radius: 9px;
                background: {Colors.VOID};
            }}
            QRadioButton::indicator:checked {{
                border-color: {Colors.AMBER};
                background: {Colors.AMBER};
            }}
        """)

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── 顶部品牌栏 ──
        brand = QFrame()
        brand.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {Colors.VOID}, stop:1 {Colors.AMBER_DIM});
            padding: 24px;
        """)
        brand_layout = QVBoxLayout(brand)
        title = QLabel("SSUBB Worker")
        title.setStyleSheet(f"{Fonts.heading(24, '800')} color: {Colors.AMBER}; letter-spacing: 3px;")
        brand_layout.addWidget(title)
        sub = QLabel("首次运行 · 让我们配置你的 Worker")
        sub.setStyleSheet(f"{Fonts.body(13)} color: {Colors.TEXT_SECONDARY};")
        brand_layout.addWidget(sub)
        main.addWidget(brand)

        # ── 步骤指示器 ──
        self._step_bar = QFrame()
        self._step_bar.setStyleSheet(f"background: {Colors.PANEL}; padding: 12px 24px;")
        self._step_layout = QHBoxLayout(self._step_bar)
        self._step_layout.setSpacing(8)
        self._step_labels = []
        steps = ["欢迎", "Coordinator", "转写模型", "LLM 配置", "完成"]
        for i, name in enumerate(steps):
            dot = QLabel(f"  {i+1}  {name}  ")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(f"""
                {Fonts.body(11)}
                color: {Colors.TEXT_MUTED};
                padding: 4px 8px;
                border-radius: 12px;
            """)
            self._step_labels.append(dot)
            self._step_layout.addWidget(dot)
            if i < len(steps) - 1:
                line = QLabel("─")
                line.setStyleSheet(f"color: {Colors.BORDER_DIM}; {Fonts.body(10)};")
                line.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._step_layout.addWidget(line)
        self._step_layout.addStretch()
        main.addWidget(self._step_bar)

        # ── 步骤内容 ──
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._make_step_welcome())
        self._stack.addWidget(self._make_step_coordinator())
        self._stack.addWidget(self._make_step_transcribe())
        self._stack.addWidget(self._make_step_llm())
        self._stack.addWidget(self._make_step_done())
        main.addWidget(self._stack, 1)

        # ── 底部按钮栏 ──
        btn_bar = QFrame()
        btn_bar.setStyleSheet(f"background: {Colors.PANEL}; padding: 12px 24px;")
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setSpacing(12)

        self._back_btn = QPushButton("  上一步")
        self._back_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 8px;
                padding: 10px 24px;
                {Fonts.body(13)}
            }}
            QPushButton:hover {{ color: {Colors.AMBER}; border-color: {Colors.AMBER}44; }}
        """)
        self._back_btn.clicked.connect(self._go_back)
        btn_layout.addWidget(self._back_btn)

        btn_layout.addStretch()

        self._next_btn = QPushButton("  下一步  ")
        self._next_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.AMBER};
                color: {Colors.VOID};
                border: none;
                border-radius: 8px;
                padding: 10px 32px;
                {Fonts.heading(13, '600')}
            }}
            QPushButton:hover {{ background: #ffb833; }}
            QPushButton:pressed {{ background: #d4901e; }}
        """)
        self._next_btn.clicked.connect(self._go_next)
        btn_layout.addWidget(self._next_btn)
        main.addWidget(btn_bar)

    # ────────────────────────────────────────────────
    # Step 0: Welcome
    # ────────────────────────────────────────────────
    def _make_step_welcome(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        icon = QLabel("🎬")
        icon.setStyleSheet("font-size: 48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("欢迎使用 SSUBB")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"{Fonts.heading(20, '700')} color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel(
            "SSUBB 是一个分布式字幕转写翻译系统。\n\n"
            "Worker 运行在你的 GPU 电脑上，负责转写音频和翻译字幕。\n"
            "接下来我们会帮你配置 Worker 连接到 Coordinator。"
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"{Fonts.body(13)} color: {Colors.TEXT_SECONDARY}; line-height: 1.6;")
        layout.addWidget(desc)
        layout.addStretch()
        return w

    # ────────────────────────────────────────────────
    # Step 1: Coordinator
    # ────────────────────────────────────────────────
    def _make_step_coordinator(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(16)

        title = QLabel("连接 Coordinator")
        title.setStyleSheet(f"{Fonts.heading(16, '700')} color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel("输入 Coordinator 的地址，Worker 会自动注册并接收任务。")
        desc.setStyleSheet(f"{Fonts.body(12)} color: {Colors.TEXT_SECONDARY};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(12)

        self._oobe_coord_url = QLineEdit()
        self._oobe_coord_url.setPlaceholderText("http://192.168.1.10:8787")
        form.addRow("Coordinator 地址:", self._oobe_coord_url)

        self._oobe_worker_port = QSpinBox()
        self._oobe_worker_port.setRange(1, 65535)
        self._oobe_worker_port.setValue(8788)
        form.addRow("Worker 端口:", self._oobe_worker_port)

        layout.addLayout(form)
        layout.addStretch()
        return w

    # ────────────────────────────────────────────────
    # Step 2: Transcribe
    # ────────────────────────────────────────────────
    def _make_step_transcribe(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(16)

        title = QLabel("转写模型")
        title.setStyleSheet(f"{Fonts.heading(16, '700')} color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel("选择 Whisper 语音识别模型。模型越大越精准，但需要更多显存。")
        desc.setStyleSheet(f"{Fonts.body(12)} color: {Colors.TEXT_SECONDARY};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 模型选择卡片
        models = [
            ("tiny", "最小", "~1GB VRAM", "速度最快，精度最低"),
            ("base", "基础", "~1GB VRAM", "适合简单场景"),
            ("small", "小型", "~2GB VRAM", "平衡精度和速度"),
            ("medium", "中型", "~5GB VRAM", "高精度"),
            ("large-v3-turbo", "大型 Turbo", "~6GB VRAM", "最高精度，推荐"),
        ]

        self._oobe_model_btns = []
        for model, label, vram, desc_text in models:
            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background: {Colors.ELEVATED};
                    border: 1px solid {Colors.BORDER_DIM};
                    border-radius: 8px;
                    padding: 8px;
                }}
                QFrame:hover {{
                    border-color: {Colors.AMBER}66;
                }}
            """)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 12, 8)

            rb = QRadioButton()
            rb.setStyleSheet(f"""
                QRadioButton::indicator {{
                    width: 16px; height: 16px;
                    border: 2px solid {Colors.BORDER_DIM};
                    border-radius: 8px;
                    background: {Colors.VOID};
                }}
                QRadioButton::indicator:checked {{
                    border-color: {Colors.AMBER};
                    background: {Colors.AMBER};
                }}
            """)
            if model == "large-v3-turbo":
                rb.setChecked(True)
            self._oobe_model_btns.append((rb, model))
            row_layout.addWidget(rb)

            info = QVBoxLayout()
            info.setSpacing(2)
            name_label = QLabel(f"{label}  ({model})")
            name_label.setStyleSheet(f"{Fonts.body(12)} color: {Colors.TEXT_PRIMARY}; font-weight: 500;")
            info.addWidget(name_label)
            detail = QLabel(f"{vram} · {desc_text}")
            detail.setStyleSheet(f"{Fonts.body(11)} color: {Colors.TEXT_MUTED};")
            info.addWidget(detail)
            row_layout.addLayout(info, 1)

            layout.addWidget(row)

        layout.addStretch()
        return w

    # ────────────────────────────────────────────────
    # Step 3: LLM
    # ────────────────────────────────────────────────
    def _make_step_llm(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(16)

        title = QLabel("LLM 翻译配置")
        title.setStyleSheet(f"{Fonts.heading(16, '700')} color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel("配置大语言模型 API 用于字幕翻译。支持 OpenAI 兼容接口。")
        desc.setStyleSheet(f"{Fonts.body(12)} color: {Colors.TEXT_SECONDARY};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(12)

        self._oobe_api_base = QLineEdit()
        self._oobe_api_base.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("API Base URL:", self._oobe_api_base)

        self._oobe_api_key = QLineEdit()
        self._oobe_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._oobe_api_key.setPlaceholderText("sk-...")
        form.addRow("API Key:", self._oobe_api_key)

        self._oobe_model_name = QLineEdit()
        self._oobe_model_name.setPlaceholderText("deepseek-chat")
        form.addRow("模型名称:", self._oobe_model_name)

        self._oobe_target_lang = QComboBox()
        from shared.constants import LANGUAGE_MAP
        for code, name in LANGUAGE_MAP.items():
            self._oobe_target_lang.addItem(f"{name} ({code})", code)
        form.addRow("目标语言:", self._oobe_target_lang)

        layout.addLayout(form)
        layout.addStretch()
        return w

    # ────────────────────────────────────────────────
    # Step 4: Done
    # ────────────────────────────────────────────────
    def _make_step_done(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        icon = QLabel("✨")
        icon.setStyleSheet("font-size: 48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("配置完成！")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"{Fonts.heading(20, '700')} color: {Colors.GREEN};")
        layout.addWidget(title)

        self._summary_label = QLabel()
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(f"{Fonts.body(13)} color: {Colors.TEXT_SECONDARY}; line-height: 1.6;")
        layout.addWidget(self._summary_label)

        tip = QLabel("配置已保存到 config.yaml，之后可以随时在主界面修改。")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet(f"{Fonts.body(11)} color: {Colors.TEXT_MUTED};")
        layout.addWidget(tip)

        layout.addStretch()
        return w

    # ────────────────────────────────────────────────
    # Navigation
    # ────────────────────────────────────────────────
    def _goto_step(self, index):
        self._current_step = index
        self._stack.setCurrentIndex(index)

        # 更新步骤指示器
        for i, label in enumerate(self._step_labels):
            if i == index:
                label.setStyleSheet(f"""
                    {Fonts.body(11)}
                    color: {Colors.AMBER};
                    background: {Colors.AMBER_DIM};
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-weight: 600;
                """)
            elif i < index:
                label.setStyleSheet(f"""
                    {Fonts.body(11)}
                    color: {Colors.GREEN};
                    padding: 4px 8px;
                    border-radius: 12px;
                """)
            else:
                label.setStyleSheet(f"""
                    {Fonts.body(11)}
                    color: {Colors.TEXT_MUTED};
                    padding: 4px 8px;
                    border-radius: 12px;
                """)

        # 按钮状态
        self._back_btn.setVisible(index > 0 and index < 4)
        if index == 4:
            self._next_btn.setText("  完成并启动  ")
        else:
            self._next_btn.setText("  下一步  ")

    def _go_back(self):
        if self._current_step > 0:
            self._goto_step(self._current_step - 1)

    def _go_next(self):
        if self._current_step == 3:
            # 进入完成页前，收集配置
            self._collect_config()
            self._update_summary()
            self._save_config()
            self._goto_step(4)
        elif self._current_step == 4:
            self.config_ready.emit(self._config)
            self.accept()
        else:
            self._goto_step(self._current_step + 1)

    def _collect_config(self):
        self._config = {
            "coordinator_url": self._oobe_coord_url.text().strip() or "http://localhost:8787",
            "port": self._oobe_worker_port.value(),
            "whisper_model": "large-v3-turbo",
            "api_base": self._oobe_api_base.text().strip() or "https://api.deepseek.com/v1",
            "api_key": self._oobe_api_key.text().strip(),
            "model_name": self._oobe_model_name.text().strip() or "deepseek-chat",
            "target_lang": self._oobe_target_lang.currentData(),
        }
        for rb, model in self._oobe_model_btns:
            if rb.isChecked():
                self._config["whisper_model"] = model
                break

    def _update_summary(self):
        c = self._config
        self._summary_label.setText(
            f"Coordinator: {c['coordinator_url']}\n"
            f"Worker 端口: {c['port']}\n"
            f"Whisper 模型: {c['whisper_model']}\n"
            f"翻译模型: {c['model_name']}\n"
            f"目标语言: {c['target_lang']}"
        )

    def _save_config(self):
        try:
            from worker.config import WorkerConfig, save_worker_config
            from shared.models import LLMProviderConfig

            cfg = WorkerConfig()
            cfg.port = self._config["port"]
            cfg.coordinator_url = self._config["coordinator_url"]
            cfg.transcribe.model = self._config["whisper_model"]
            cfg.llm.api_base = self._config["api_base"]
            cfg.llm.api_key = self._config["api_key"]
            cfg.llm.model = self._config["model_name"]
            cfg.translate.target_language = self._config["target_lang"]

            save_config = cfg.model_dump()
            save_config.pop("host", None)
            save_worker_config(save_config)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"配置保存失败:\n{e}\n\n请稍后在配置界面手动设置。")
