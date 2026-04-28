"""SSUBB 共享 Pydantic 数据模型

Coordinator 和 Worker 之间通信的统一数据结构。
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import uuid


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


# =============================================================================
# 任务相关
# =============================================================================

class TaskConfig(BaseModel):
    """任务处理配置 (随音频一起发送给 Worker)"""
    source_lang: str = Field(default="auto", description="源语言 (auto/en/ja/fr...)")
    target_lang: str = Field(default="zh", description="目标语言")
    
    # 转写
    whisper_model: str = Field(default="large-v3-turbo")
    compute_type: str = Field(default="float16")
    vad_filter: bool = Field(default=True)
    vad_method: str = Field(default="silero_v4_fw")
    
    # 优化
    optimize_enabled: bool = Field(default=True, description="是否启用 LLM 断句优化")
    
    # 翻译
    translate_service: str = Field(default="llm", description="翻译服务: llm/bing/google")
    translate_thread_num: int = Field(default=5)
    translate_batch_size: int = Field(default=10)
    need_reflect: bool = Field(default=False, description="反思翻译 (更高质量)")


class TaskCreate(BaseModel):
    """创建任务请求 (MoviePilot/Emby/手动 → Coordinator)"""
    media_path: str = Field(..., description="媒体文件路径")
    media_title: Optional[str] = Field(default=None, description="媒体标题")
    media_type: str = Field(default="unknown", description="movie/tv/unknown")
    season: Optional[int] = Field(default=None)
    episode: Optional[int] = Field(default=None)
    tmdb_id: Optional[int] = Field(default=None)
    source_lang: str = Field(default="auto")
    target_lang: str = Field(default="zh")
    audio_track: int = Field(default=-1, description="音轨索引 (-1=自动选择)")
    force: bool = Field(default=False, description="强制模式: 跳过所有检查，覆盖已有字幕")
    callback_url: Optional[str] = Field(default=None, description="通知回调地址 (Webhook)")


class TaskInfo(BaseModel):
    """任务完整信息 (Coordinator 内部 + API 返回)"""
    id: str = Field(default_factory=_gen_id)
    media_path: str
    media_title: Optional[str] = None
    media_type: str = "unknown"
    season: Optional[int] = None
    episode: Optional[int] = None
    tmdb_id: Optional[int] = None
    audio_path: Optional[str] = None
    source_lang: str = "auto"
    target_lang: str = "zh"
    
    status: str = "pending"
    force_mode: bool = False
    skip_reason: Optional[str] = None
    callback_url: Optional[str] = None
    meta_info: Dict[str, Any] = Field(default_factory=dict)
    
    worker_id: Optional[str] = None
    config: Optional[TaskConfig] = None
    
    progress: int = 0
    error_msg: Optional[str] = None
    error_code: Optional[str] = None         # 错误分类码 (ErrorCode.*)
    failed_stage: Optional[str] = None       # 失败所在阶段
    retry_count: int = 0
    
    # 阶段耗时记录 {"extracting": 12.3, "transcribing": 45.6, ...}
    stage_times: Dict[str, float] = Field(default_factory=dict)
    
    # 简化的结果摘要
    result_summary: Optional[Dict[str, Any]] = None
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =============================================================================
# Worker API 通信
# =============================================================================

class WorkerTaskRequest(BaseModel):
    """Coordinator → Worker: 任务请求 (随音频文件一起 POST)"""
    task_id: str
    source_lang: str = "auto"
    target_lang: str = "zh"
    config: TaskConfig = Field(default_factory=TaskConfig)


class WorkerProgressUpdate(BaseModel):
    """Worker → Coordinator: 进度更新"""
    task_id: str
    status: str
    progress: int = Field(ge=0, le=100)
    message: Optional[str] = None


class WorkerTaskResult(BaseModel):
    """Worker → Coordinator: 任务结果回调"""
    task_id: str
    status: str                              # completed / failed
    subtitle_srt: Optional[str] = None       # SRT 字幕内容
    subtitle_ass: Optional[str] = None       # ASS 字幕内容 (可选)
    detected_language: Optional[str] = None  # 检测到的源语言
    transcribe_duration: Optional[float] = None   # 转写耗时 (秒)
    translate_duration: Optional[float] = None    # 翻译耗时 (秒)
    total_duration: Optional[float] = None        # 总耗时 (秒)
    segment_count: Optional[int] = None           # 字幕条数
    error: Optional[str] = None
    error_code: Optional[str] = None              # 错误分类码


# =============================================================================
# Worker 状态
# =============================================================================

class WorkerHeartbeat(BaseModel):
    """Worker 心跳数据"""
    worker_id: str
    version: str
    gpu_name: Optional[str] = None
    gpu_utilization: Optional[int] = None       # %
    vram_used_mb: Optional[int] = None
    vram_total_mb: Optional[int] = None
    queue_length: int = 0
    current_task_id: Optional[str] = None
    current_progress: int = 0
    uptime_seconds: float = 0


class WorkerStatus(BaseModel):
    """Worker 状态 (Coordinator 维护)"""
    worker_id: str
    url: str
    online: bool = False
    last_heartbeat: Optional[datetime] = None
    heartbeat: Optional[WorkerHeartbeat] = None


# =============================================================================
# API 响应
# =============================================================================

class APIResponse(BaseModel):
    """通用 API 响应"""
    success: bool = True
    message: str = "OK"
    data: Optional[dict] = None


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int
    tasks: list[TaskInfo]


class SystemStatus(BaseModel):
    """系统状态"""
    version: str
    coordinator_online: bool = True
    worker: Optional[WorkerStatus] = None
    tasks_pending: int = 0
    tasks_active: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
