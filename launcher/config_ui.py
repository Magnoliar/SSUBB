"""Worker 配置编辑对话框

分组卡片式表单，复用 worker.config 的 load/save。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from launcher.theme import Colors, Fonts
from shared.constants import LANGUAGE_MAP


class ConfigDialog(QDialog):
    """Worker 配置编辑对话框。"""

    def __init__(self, config_path=None, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self.setWindowTitle("Worker 配置")
        self.setMinimumSize(560, 600)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
            }}
            QGroupBox {{
                background-color: {Colors.PANEL};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 10px;
                margin-top: 18px;
                padding: 18px 14px 14px 14px;
                {Fonts.heading(12)}
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 10px;
                color: {Colors.AMBER};
                background-color: {Colors.PANEL};
                {Fonts.heading(12, '600')}
            }}
            QLabel {{
                color: {Colors.TEXT_SECONDARY};
                {Fonts.body(12)}
            }}
            QLineEdit, QSpinBox, QComboBox {{
                background-color: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 6px 10px;
                {Fonts.body(12)}
            }}
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
                border-color: {Colors.AMBER};
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox::down-arrow {{
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {Colors.TEXT_SECONDARY};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_DIM};
                selection-background-color: {Colors.AMBER_DIM};
            }}
            QCheckBox {{
                color: {Colors.TEXT_PRIMARY};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 4px;
                background: {Colors.SURFACE};
            }}
            QCheckBox::indicator:checked {{
                background: {Colors.AMBER};
                border-color: {Colors.AMBER};
            }}
        """)
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 标题
        title = QLabel("Worker 配置")
        title.setStyleSheet(f"{Fonts.heading(18, '700')} color: {Colors.TEXT_PRIMARY};")
        main_layout.addWidget(title)

        subtitle = QLabel("修改 Worker 运行参数，保存后重启生效")
        subtitle.setStyleSheet(f"{Fonts.body(11)} color: {Colors.TEXT_MUTED};")
        main_layout.addWidget(subtitle)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {Colors.BORDER_DIM};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._form = QVBoxLayout(container)
        self._form.setSpacing(12)

        # ── 基础 ──
        basic = QGroupBox("  基础  ")
        basic_form = QFormLayout(basic)
        basic_form.setSpacing(10)
        basic_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._worker_id = QLineEdit()
        self._worker_id.setPlaceholderText("自动生成")
        basic_form.addRow("Worker ID:", self._worker_id)

        self._coord_url = QLineEdit()
        self._coord_url.setPlaceholderText("http://192.168.1.10:8787")
        basic_form.addRow("Coordinator:", self._coord_url)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(8788)
        basic_form.addRow("端口:", self._port)
        self._form.addWidget(basic)

        # ── 转写 ──
        transcribe = QGroupBox("  转写  ")
        tr_form = QFormLayout(transcribe)
        tr_form.setSpacing(10)
        tr_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._whisper_model = QComboBox()
        self._whisper_model.addItems(["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"])
        tr_form.addRow("Whisper 模型:", self._whisper_model)

        self._device = QComboBox()
        self._device.addItems(["cuda", "cpu"])
        tr_form.addRow("设备:", self._device)

        self._compute_type = QComboBox()
        self._compute_type.addItems(["float16", "int8", "float32"])
        tr_form.addRow("计算类型:", self._compute_type)

        model_dir_row = QHBoxLayout()
        self._model_dir = QLineEdit()
        self._model_dir.setPlaceholderText("./models")
        model_dir_row.addWidget(self._model_dir)
        browse_btn = QPushButton("浏览")
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ color: {Colors.AMBER}; border-color: {Colors.AMBER}44; }}
        """)
        browse_btn.setFixedWidth(60)
        browse_btn.clicked.connect(self._browse_model_dir)
        model_dir_row.addWidget(browse_btn)
        tr_form.addRow("模型目录:", model_dir_row)

        # faster-whisper-xxl 二进制路径
        binary_row = QHBoxLayout()
        self._whisper_binary = QLineEdit()
        self._whisper_binary.setPlaceholderText("自动查找（留空则自动下载）")
        binary_row.addWidget(self._whisper_binary)
        binary_browse = QPushButton("浏览")
        binary_browse.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ color: {Colors.AMBER}; border-color: {Colors.AMBER}44; }}
        """)
        binary_browse.setFixedWidth(60)
        binary_browse.clicked.connect(self._browse_whisper_binary)
        binary_row.addWidget(binary_browse)
        tr_form.addRow("Whisper 引擎:", binary_row)
        self._form.addWidget(transcribe)

        # ── LLM ──
        llm = QGroupBox("  LLM 翻译  ")
        llm_form = QFormLayout(llm)
        llm_form.setSpacing(10)
        llm_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._api_base = QLineEdit()
        self._api_base.setPlaceholderText("https://api.deepseek.com/v1")
        llm_form.addRow("API Base:", self._api_base)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-...")
        llm_form.addRow("API Key:", self._api_key)

        self._model_name = QLineEdit()
        self._model_name.setPlaceholderText("deepseek-chat")
        llm_form.addRow("模型:", self._model_name)
        self._form.addWidget(llm)

        # ── 翻译 ──
        translate = QGroupBox("  翻译  ")
        tl_form = QFormLayout(translate)
        tl_form.setSpacing(10)
        tl_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._target_lang = QComboBox()
        for code, name in LANGUAGE_MAP.items():
            self._target_lang.addItem(f"{name} ({code})", code)
        tl_form.addRow("目标语言:", self._target_lang)

        self._thread_num = QSpinBox()
        self._thread_num.setRange(1, 20)
        self._thread_num.setValue(5)
        tl_form.addRow("线程数:", self._thread_num)

        self._batch_size = QSpinBox()
        self._batch_size.setRange(1, 50)
        self._batch_size.setValue(10)
        tl_form.addRow("批量大小:", self._batch_size)

        self._need_reflect = QCheckBox("启用反思校验")
        tl_form.addRow("", self._need_reflect)
        self._form.addWidget(translate)

        # ── 优化 ──
        optimize = QGroupBox("  字幕优化  ")
        opt_form = QFormLayout(optimize)
        opt_form.setSpacing(10)
        opt_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._optimize_enabled = QCheckBox("启用")
        opt_form.addRow("", self._optimize_enabled)

        self._max_cjk = QSpinBox()
        self._max_cjk.setRange(1, 50)
        self._max_cjk.setValue(12)
        opt_form.addRow("CJK 最大字数:", self._max_cjk)

        self._max_en = QSpinBox()
        self._max_en.setRange(1, 50)
        self._max_en.setValue(15)
        opt_form.addRow("英文最大词数:", self._max_en)
        self._form.addWidget(optimize)

        self._form.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll, 1)

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_DIM};
                border-radius: 6px;
                padding: 8px 20px;
                {Fonts.body(12)}
            }}
            QPushButton:hover {{ color: {Colors.TEXT_PRIMARY}; border-color: {Colors.AMBER}44; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("  保存配置")
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.AMBER};
                color: {Colors.VOID};
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                {Fonts.heading(12, '600')}
            }}
            QPushButton:hover {{ background: #ffb833; }}
            QPushButton:pressed {{ background: #d4901e; }}
        """)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        main_layout.addLayout(btn_row)

    def _browse_model_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择模型目录")
        if d:
            self._model_dir.setText(d)

    def _browse_whisper_binary(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择 faster-whisper-xxl 可执行文件", "",
            "可执行文件 (*.exe);;所有文件 (*)" if __import__("os").name == "nt"
            else "所有文件 (*)"
        )
        if f:
            self._whisper_binary.setText(f)

    def _load_config(self):
        try:
            from worker.config import load_worker_config, save_worker_config, WorkerConfig
        except Exception:
            return

        try:
            cfg = load_worker_config(self._config_path)
        except Exception:
            cfg = WorkerConfig()
            try:
                save_worker_config(cfg.model_dump(), self._config_path)
            except Exception:
                pass

        self._port.setValue(cfg.port)
        if hasattr(cfg, "worker_id") and cfg.worker_id:
            self._worker_id.setText(cfg.worker_id)
        if hasattr(cfg, "coordinator_url") and cfg.coordinator_url:
            self._coord_url.setText(cfg.coordinator_url)

        tc = cfg.transcribe
        idx = self._whisper_model.findText(tc.model)
        if idx >= 0:
            self._whisper_model.setCurrentIndex(idx)
        idx = self._device.findText(tc.device)
        if idx >= 0:
            self._device.setCurrentIndex(idx)
        idx = self._compute_type.findText(tc.compute_type)
        if idx >= 0:
            self._compute_type.setCurrentIndex(idx)
        self._model_dir.setText(tc.model_dir)
        if hasattr(tc, "whisper_binary") and tc.whisper_binary:
            self._whisper_binary.setText(tc.whisper_binary)

        lc = cfg.llm
        self._api_base.setText(lc.api_base)
        if lc.api_key:
            self._api_key.setText(lc.api_key)
            self._api_key.setPlaceholderText("***")
        self._model_name.setText(lc.model)

        trc = cfg.translate
        for i in range(self._target_lang.count()):
            if self._target_lang.itemData(i) == trc.target_language:
                self._target_lang.setCurrentIndex(i)
                break
        self._thread_num.setValue(trc.thread_num)
        self._batch_size.setValue(trc.batch_size)
        self._need_reflect.setChecked(trc.need_reflect)

        oc = cfg.optimize
        self._optimize_enabled.setChecked(oc.enabled)
        self._max_cjk.setValue(oc.max_word_count_cjk)
        self._max_en.setValue(oc.max_word_count_english)

    def _save(self):
        try:
            from worker.config import WorkerConfig, load_worker_config, save_worker_config

            cfg = load_worker_config(self._config_path)

            cfg.port = self._port.value()
            if self._worker_id.text().strip():
                cfg.worker_id = self._worker_id.text().strip()
            if self._coord_url.text().strip():
                cfg.coordinator_url = self._coord_url.text().strip()

            cfg.transcribe.model = self._whisper_model.currentText()
            cfg.transcribe.device = self._device.currentText()
            cfg.transcribe.compute_type = self._compute_type.currentText()
            cfg.transcribe.model_dir = self._model_dir.text() or "./models"
            cfg.transcribe.whisper_binary = self._whisper_binary.text().strip()

            cfg.llm.api_base = self._api_base.text()
            if self._api_key.text() and self._api_key.text() != "***":
                cfg.llm.api_key = self._api_key.text()
            cfg.llm.model = self._model_name.text()

            cfg.translate.target_language = self._target_lang.currentData()
            cfg.translate.thread_num = self._thread_num.value()
            cfg.translate.batch_size = self._batch_size.value()
            cfg.translate.need_reflect = self._need_reflect.isChecked()

            cfg.optimize.enabled = self._optimize_enabled.isChecked()
            cfg.optimize.max_word_count_cjk = self._max_cjk.value()
            cfg.optimize.max_word_count_english = self._max_en.value()

            WorkerConfig.model_validate(cfg.model_dump())

            save_config = cfg.model_dump()
            save_config.pop("host", None)
            save_worker_config(save_config, self._config_path)

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"配置验证失败:\n{e}")
