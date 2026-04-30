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


class AssStyleConfig(BaseModel):
    """ASS 字幕默认样式"""
    font_name: str = "Noto Sans"
    font_size: int = 12
    primary_colour: str = "&H00FFFFFF"   # 白色 (AABBGGRR)
    outline_colour: str = "&H000000FF"   # 红色
    back_colour: str = "&H80000000"      # 半透明黑
    bold: int = -1                       # -1=粗体, 0=正常
    outline_width: float = 1.5
    shadow: int = 0
    alignment: int = 2                   # ASS 对齐: 2=底部居中
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 30
    play_res_x: int = 1920
    play_res_y: int = 1080


class AssBilingualStyleConfig(BaseModel):
    """ASS 双语模式原文样式（翻译用 Default 样式）"""
    font_size: int = 10
    alignment: int = 8                   # 8=顶部居中
    margin_v: int = 10


class SubtitleOutputConfig(BaseModel):
    target_language: str = "zh"
    naming_format: str = "{video_name}.{lang}.srt"
    backup_existing: bool = True
    output_mode: str = "single"       # single / bilingual (双语字幕)
    output_format: str = "srt"        # srt / ass
    ass_style: AssStyleConfig = Field(default_factory=AssStyleConfig)
    ass_bilingual_style: AssBilingualStyleConfig = Field(default_factory=AssBilingualStyleConfig)


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
    timezone: str = "Asia/Shanghai"


class DiscoveryConfig(BaseModel):
    """局域网自动发现配置"""
    enabled: bool = True
    port: int = 8789
    auto_register: bool = True


class WebhookConfig(BaseModel):
    """通用 Webhook 入口配置"""
    enabled: bool = True
    token: str = ""  # 空=不验证


class SecurityConfig(BaseModel):
    """API 安全配置"""
    api_token: str = ""              # API 访问令牌（空=不验证，向后兼容）
    worker_token: str = ""           # Worker 回调令牌（空=不验证）
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])


class LoggingConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    max_size_mb: int = 10            # 单文件最大大小 (MB)
    backup_count: int = 5            # 备份数量
    log_dir: str = "./data"          # 日志目录


class NotificationChannel(BaseModel):
    """单个通知渠道"""
    name: str = ""
    url: str = ""
    enabled: bool = True
    events: list[str] = Field(
        default_factory=lambda: ["task_completed", "task_failed"],
        description="订阅事件: task_completed, task_failed, worker_offline, scan_result",
    )
    headers: dict[str, str] = Field(default_factory=dict)
    template: str = ""               # 自定义 Body 模板（空=使用默认）
    channel_type: str = "generic"    # generic / bark / pushplus / gotify


class NotificationConfig(BaseModel):
    """通知系统配置"""
    enabled: bool = False
    channels: list[NotificationChannel] = Field(default_factory=list)


class WorkerNodeConfig(BaseModel):
    """单个 Worker 节点配置"""
    url: str
    worker_id: str = ""        # 可选，自动从心跳检测
    weight: int = 1            # 调度权重 (越高分配越多任务)
    enabled: bool = True       # 可关闭而不删除


class CoordinatorConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8787
    db_path: str = "./data/ssubb.db"
    audio: AudioConfig = Field(default_factory=AudioConfig)
    worker: WorkerConnectionConfig = Field(default_factory=WorkerConnectionConfig)
    workers: list[WorkerNodeConfig] = Field(default_factory=list)
    emby: EmbyConfig = Field(default_factory=EmbyConfig)
    subtitle: SubtitleOutputConfig = Field(default_factory=SubtitleOutputConfig)
    checker: CheckerConfig = Field(default_factory=CheckerConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    stage_timeout: StageTimeoutConfig = Field(default_factory=StageTimeoutConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)


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

    # 发现服务环境变量
    discovery_enabled = os.environ.get("SSUBB_DISCOVERY_ENABLED")
    if discovery_enabled is not None:
        config_data.setdefault("discovery", {})["enabled"] = discovery_enabled.lower() not in ("false", "0", "no")

    # Webhook 环境变量
    webhook_token = os.environ.get("SSUBB_WEBHOOK_TOKEN")
    if webhook_token is not None:
        config_data.setdefault("webhook", {})["token"] = webhook_token

    # 安全配置环境变量
    api_token = os.environ.get("SSUBB_API_TOKEN")
    if api_token is not None:
        config_data.setdefault("security", {})["api_token"] = api_token

    worker_token = os.environ.get("SSUBB_WORKER_TOKEN")
    if worker_token is not None:
        config_data.setdefault("security", {})["worker_token"] = worker_token

    for key_path, value in env_overrides.items():
        if value is not None:
            parts = key_path.split(".")
            target = config_data
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

    # 环境变量: SSUBB_WORKER_URLS (逗号分隔的多 Worker URL)
    worker_urls_env = os.environ.get("SSUBB_WORKER_URLS")
    if worker_urls_env and not config_data.get("workers"):
        urls = [u.strip() for u in worker_urls_env.split(",") if u.strip()]
        config_data["workers"] = [{"url": u, "weight": 1} for u in urls]

    config = CoordinatorConfig(**config_data)

    # 向后兼容: 若 workers 为空但 worker.url 存在，自动迁移
    if not config.workers and config.worker.url:
        config.workers = [WorkerNodeConfig(url=config.worker.url, weight=1)]

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
