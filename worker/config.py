"""SSUBB Worker 配置管理"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from shared.models import LLMProviderConfig


class TranscribeConfig(BaseModel):
    model: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    concurrent_transcriptions: int = 1
    vad_filter: bool = True
    vad_method: str = "silero_v4_fw"
    vad_threshold: float = 0.5
    custom_regroup: str = "cm_sl=84_sl=42++++++1"
    detect_language_length: int = 30
    model_dir: str = "./models"


class LLMConfig(BaseModel):
    api_base: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"


class TranslateConfig(BaseModel):
    service: str = "llm"
    target_language: str = "zh"
    thread_num: int = 5
    batch_size: int = 10
    need_reflect: bool = False


class OptimizeConfig(BaseModel):
    enabled: bool = True
    max_word_count_cjk: int = 12
    max_word_count_english: int = 18


class VRAMConfig(BaseModel):
    clear_on_complete: bool = True
    cleanup_delay: int = 30


class WorkerSecurityConfig(BaseModel):
    """Worker 安全配置"""
    worker_token: str = ""   # 验证 Coordinator 请求的 Token（空=不验证）


class WorkerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8788
    worker_id: str = "office-gpu"
    coordinator_url: str = ""
    transcribe: TranscribeConfig = Field(default_factory=TranscribeConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    llm_providers: list[LLMProviderConfig] = Field(default_factory=list)
    translate: TranslateConfig = Field(default_factory=TranslateConfig)
    optimize: OptimizeConfig = Field(default_factory=OptimizeConfig)
    vram: VRAMConfig = Field(default_factory=VRAMConfig)
    security: WorkerSecurityConfig = Field(default_factory=WorkerSecurityConfig)
    temp_dir: str = "./data/worker_temp"

    def model_post_init(self, __context):
        # 向后兼容：如果 llm_providers 为空但 llm.api_key 有值，自动迁移
        if not self.llm_providers and self.llm.api_key:
            self.llm_providers = [LLMProviderConfig(
                api_base=self.llm.api_base,
                api_key=self.llm.api_key,
                model=self.llm.model,
                priority=1,
                enabled=True,
                label="默认",
            )]


def load_worker_config(config_path: Optional[str] = None) -> WorkerConfig:
    """加载 Worker 配置"""
    if config_path is None:
        config_path = os.environ.get(
            "SSUBB_CONFIG",
            str(Path(__file__).parent.parent / "config.yaml")
        )

    config_data = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
            config_data = raw.get("worker", {})

    # 环境变量覆盖
    env_overrides = {
        "coordinator_url": os.environ.get("SSUBB_COORDINATOR_URL"),
        "llm.api_key": os.environ.get("SSUBB_LLM_API_KEY"),
        "llm.api_base": os.environ.get("SSUBB_LLM_API_BASE"),
        "llm.model": os.environ.get("SSUBB_LLM_MODEL"),
        "worker_id": os.environ.get("SSUBB_WORKER_ID"),
    }

    for key_path, value in env_overrides.items():
        if value is not None:
            parts = key_path.split(".")
            target = config_data
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

    config = WorkerConfig(**config_data)

    # 确保目录存在
    Path(config.temp_dir).mkdir(parents=True, exist_ok=True)
    Path(config.transcribe.model_dir).mkdir(parents=True, exist_ok=True)

    return config


def save_worker_config(config_data: dict, config_path: Optional[str] = None):
    """保存 Worker 配置到文件（保留非 worker 字段）"""
    if config_path is None:
        config_path = os.environ.get(
            "SSUBB_CONFIG",
            str(Path(__file__).parent.parent / "config.yaml")
        )

    # 读取现有配置以保留非 worker 字段
    existing = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    existing["worker"] = config_data

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing, f, default_flow_style=False, allow_unicode=True)
