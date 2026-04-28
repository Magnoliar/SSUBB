"""SSUBB Coordinator 配置管理"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class AudioConfig(BaseModel):
    format: str = "flac"
    sample_rate: int = 16000
    channels: int = 1
    temp_dir: str = "./data/audio_temp"


class WorkerConnectionConfig(BaseModel):
    url: str = ""
    heartbeat_interval: int = 30
    heartbeat_timeout: int = 300


class EmbyConfig(BaseModel):
    server: str = ""
    api_key: str = ""


class SubtitleOutputConfig(BaseModel):
    target_language: str = "zh"
    naming_format: str = "{video_name}.{lang}.srt"
    backup_existing: bool = True
    output_mode: str = "single"       # single / bilingual (双语字幕)
    output_format: str = "srt"        # srt / ass


class CheckerConfig(BaseModel):
    min_coverage: float = 0.7
    min_density: float = 2.0
    check_language: bool = True


class RetryConfig(BaseModel):
    max_retries: int = 3
    backoff_base: int = 60
    backoff_multiplier: int = 2


class StageTimeoutConfig(BaseModel):
    """各阶段超时配置 (秒)"""
    extracting: int = 600
    uploading: int = 600
    transcribing: int = 3600
    translating: int = 1800
    default: int = 1800


class AutomationConfig(BaseModel):
    """自动化扫描与补字幕配置"""
    enabled: bool = False
    scan_paths: list[str] = Field(default_factory=list, description="扫描目录列表")
    scan_recursive: bool = True
    scan_recent_days: int = 7
    schedule_start: str = "02:00"
    schedule_end: str = "06:00"
    scan_interval: int = 30
    max_tasks_per_scan: int = 5
    require_worker_idle: bool = True
    preheat_next_episode: bool = True


class CoordinatorConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8787
    db_path: str = "./data/ssubb.db"
    audio: AudioConfig = Field(default_factory=AudioConfig)
    worker: WorkerConnectionConfig = Field(default_factory=WorkerConnectionConfig)
    emby: EmbyConfig = Field(default_factory=EmbyConfig)
    subtitle: SubtitleOutputConfig = Field(default_factory=SubtitleOutputConfig)
    checker: CheckerConfig = Field(default_factory=CheckerConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    stage_timeout: StageTimeoutConfig = Field(default_factory=StageTimeoutConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)


def load_config(config_path: Optional[str] = None) -> CoordinatorConfig:
    """加载配置文件，优先环境变量覆盖"""
    if config_path is None:
        # 优先寻找 data/config.yaml (Docker 挂载友好)，其次寻找根目录 config.yaml
        default_data_cfg = Path(__file__).parent.parent / "data" / "config.yaml"
        default_root_cfg = Path(__file__).parent.parent / "config.yaml"
        
        if "SSUBB_CONFIG" in os.environ:
            config_path = os.environ["SSUBB_CONFIG"]
        elif default_data_cfg.exists():
            config_path = str(default_data_cfg)
        else:
            config_path = str(default_root_cfg)

    config_data = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
            config_data = raw.get("coordinator", {})

    # 环境变量覆盖关键配置
    env_overrides = {
        "worker.url": os.environ.get("SSUBB_WORKER_URL"),
        "emby.server": os.environ.get("SSUBB_EMBY_SERVER"),
        "emby.api_key": os.environ.get("SSUBB_EMBY_API_KEY"),
        "db_path": os.environ.get("SSUBB_DB_PATH"),
    }

    for key_path, value in env_overrides.items():
        if value is not None:
            parts = key_path.split(".")
            target = config_data
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

    config = CoordinatorConfig(**config_data)

    # 确保目录存在
    Path(config.audio.temp_dir).mkdir(parents=True, exist_ok=True)
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)

    return config

def save_config(config_data: dict, config_path: Optional[str] = None):
    """保存配置字典到文件"""
    if config_path is None:
        if "SSUBB_CONFIG" in os.environ:
            config_path = os.environ["SSUBB_CONFIG"]
        else:
            config_path = str(Path(__file__).parent.parent / "data" / "config.yaml")
            
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    
    # 读现有以保留不相关字段 (如 worker 端配置)
    full_data = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            full_data = yaml.safe_load(f) or {}
            
    full_data["coordinator"] = config_data
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(full_data, f, allow_unicode=True, sort_keys=False)
