"""SSUBB 共享常量"""

# =============================================================================
# 版本
# =============================================================================
VERSION = "0.10.0"
PROJECT_NAME = "SSUBB"
PROJECT_DESC = "异地分布式字幕转写翻译系统"

# =============================================================================
# 任务状态 (细粒度阶段化)
# =============================================================================
class TaskStatus:
    PENDING = "pending"                         # 等待处理
    SUBTITLE_CHECKING = "subtitle_checking"     # 正在检查已有字幕
    EXTRACTING = "extracting"                   # 正在提取音频
    EXTRACTED = "extracted"                     # 音频已提取，等待分发
    UPLOADING = "uploading"                     # 正在上传到 Worker
    WORKER_QUEUED = "worker_queued"             # Worker 已接收，队列中
    TRANSCRIBING = "transcribing"               # 正在转写
    OPTIMIZING = "optimizing"                   # 正在 LLM 优化断句
    TRANSLATING = "translating"                 # 正在翻译
    ALIGNING = "aligning"                       # 正在对轴/后处理
    WRITING_SUBTITLE = "writing_subtitle"       # 正在写回字幕
    REFRESHING_EMBY = "refreshing_emby"         # 正在刷新 Emby
    COMPLETED = "completed"                     # 已完成
    FAILED = "failed"                           # 失败
    SKIPPED = "skipped"                         # 已跳过 (字幕已存在且合格)
    CANCELLED = "cancelled"                     # 已取消

    ALL = [PENDING, SUBTITLE_CHECKING, EXTRACTING, EXTRACTED, UPLOADING, WORKER_QUEUED,
           TRANSCRIBING, OPTIMIZING, TRANSLATING, ALIGNING,
           WRITING_SUBTITLE, REFRESHING_EMBY,
           COMPLETED, FAILED, SKIPPED, CANCELLED]

    # 活跃状态 (任务尚未结束)
    ACTIVE = [PENDING, SUBTITLE_CHECKING, EXTRACTING, EXTRACTED, UPLOADING, WORKER_QUEUED,
              TRANSCRIBING, OPTIMIZING, TRANSLATING, ALIGNING,
              WRITING_SUBTITLE, REFRESHING_EMBY]

    # Coordinator 本地阶段
    COORDINATOR_STAGES = [PENDING, SUBTITLE_CHECKING, EXTRACTING, EXTRACTED, UPLOADING,
                          WRITING_SUBTITLE, REFRESHING_EMBY]

    # Worker 执行阶段
    WORKER_STAGES = [WORKER_QUEUED, TRANSCRIBING, OPTIMIZING, TRANSLATING, ALIGNING]

    # 终态
    TERMINAL = [COMPLETED, FAILED, SKIPPED, CANCELLED]


# =============================================================================
# 错误分类
# =============================================================================
class ErrorCode:
    """任务失败时的错误分类码"""
    CONFIG_ERROR = "config_error"               # 配置错误
    NETWORK_ERROR = "network_error"             # 网络连接错误
    MEDIA_READ_ERROR = "media_read_error"       # 媒体文件读取错误
    AUDIO_EXTRACT_ERROR = "audio_extract_error" # 音频提取错误
    UPLOAD_ERROR = "upload_error"               # 上传 Worker 错误
    MODEL_ERROR = "model_error"                 # ASR 模型错误
    LLM_ERROR = "llm_error"                     # LLM 调用错误
    SUBTITLE_WRITE_ERROR = "subtitle_write_error"   # 字幕写入错误
    EMBY_REFRESH_ERROR = "emby_refresh_error"       # Emby 刷新错误
    CALLBACK_ERROR = "callback_error"           # Worker 回调错误
    TIMEOUT_ERROR = "timeout_error"             # 阶段超时错误
    UNKNOWN_ERROR = "unknown_error"             # 未分类错误

    # 可自动重试的错误
    RETRYABLE = {NETWORK_ERROR, UPLOAD_ERROR, LLM_ERROR,
                 EMBY_REFRESH_ERROR, CALLBACK_ERROR, TIMEOUT_ERROR}


# =============================================================================
# 阶段超时默认值 (秒)
# =============================================================================
STAGE_TIMEOUTS = {
    TaskStatus.EXTRACTING: 600,         # 10 分钟
    TaskStatus.UPLOADING: 600,          # 10 分钟
    TaskStatus.TRANSCRIBING: 3600,      # 60 分钟
    TaskStatus.OPTIMIZING: 1800,        # 30 分钟
    TaskStatus.TRANSLATING: 1800,       # 30 分钟
    TaskStatus.ALIGNING: 300,           # 5 分钟
    TaskStatus.WRITING_SUBTITLE: 60,    # 1 分钟
    TaskStatus.REFRESHING_EMBY: 60,     # 1 分钟
    "_default": 1800,                   # 默认 30 分钟
}


# =============================================================================
# 媒体类型
# =============================================================================
class MediaType:
    MOVIE = "movie"
    TV = "tv"
    UNKNOWN = "unknown"

# =============================================================================
# 支持的文件格式
# =============================================================================
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".m4v", ".ts", ".m2ts", ".vob", ".rmvb",
})

AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus", ".wma",
})

SUBTITLE_EXTENSIONS = frozenset({
    ".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx",
})

# =============================================================================
# 语言映射
# =============================================================================
LANGUAGE_MAP = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "fr": "Français",
    "de": "Deutsch",
    "ko": "한국어",
    "es": "Español",
    "ru": "Русский",
    "pt": "Português",
    "it": "Italiano",
    "auto": "自动检测",
}

# 中文字幕文件标识 (用于查找已有字幕)
ZH_SUBTITLE_TAGS = frozenset({
    "zh", "chi", "chs", "cht", "chinese", "zh-cn", "zh-tw",
    "zh-hans", "zh-hant", "zho", "cmn",
})

# =============================================================================
# 默认值
# =============================================================================
DEFAULT_TARGET_LANG = "zh"
DEFAULT_WHISPER_MODEL = "large-v3-turbo"
DEFAULT_COMPUTE_TYPE = "float16"
DEFAULT_AUDIO_SAMPLE_RATE = 16000
DEFAULT_AUDIO_CHANNELS = 1

# Worker 心跳
HEARTBEAT_INTERVAL = 30       # 秒
HEARTBEAT_TIMEOUT = 300       # 秒

# 局域网发现
DISCOVERY_PORT = 8789

# 重试
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 60       # 秒
RETRY_BACKOFF_MULTIPLIER = 2
