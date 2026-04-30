"""SSUBB Coordinator - FastAPI 入口

NAS 端的 HTTP 服务，接收 MoviePilot/Emby/手动请求，管理任务生命周期。
"""

import asyncio
import json
import logging
import sys
from collections import deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.constants import VERSION, PROJECT_NAME, TaskStatus
from shared.models import (
    APIResponse,
    SystemStatus,
    TaskCreate,
    TaskInfo,
    TaskListResponse,
    WorkerProgressUpdate,
    WorkerTaskResult,
)

from .config import load_config, WorkerNodeConfig
from .task_manager import TaskManager

# =============================================================================
# 日志配置
# =============================================================================
import os
from pathlib import Path

LOG_DIR = Path("./data")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ssubb.log"

# 配置根日志
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 清除已有的 handlers 避免重复
if root_logger.hasHandlers():
    root_logger.handlers.clear()

formatter = logging.Formatter(
    fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 终端输出
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# 文件输出
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("ssubb.coordinator")


# =============================================================================
# WebSocket 日志广播
# =============================================================================

class LogBroadcaster:
    """维护日志历史和 WebSocket 订阅者列表"""

    def __init__(self, max_history: int = 200):
        self._history: deque[str] = deque(maxlen=max_history)
        self._subscribers: set[asyncio.Queue] = set()

    def emit(self, message: str):
        self._history.append(message)
        for q in self._subscribers:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass  # 丢弃慢消费者

    def subscribe(self) -> tuple[deque, asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return self._history, q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)


log_broadcaster = LogBroadcaster()


class WebSocketLogHandler(logging.Handler):
    """将日志记录广播到所有 WebSocket 订阅者"""

    def __init__(self, broadcaster: LogBroadcaster):
        super().__init__()
        self._broadcaster = broadcaster

    def emit(self, record):
        try:
            msg = self.format(record)
            self._broadcaster.emit(msg)
        except Exception:
            self.handleError(record)


# 注册 WebSocket 日志 handler
ws_handler = WebSocketLogHandler(log_broadcaster)
ws_handler.setFormatter(formatter)
root_logger.addHandler(ws_handler)


# =============================================================================
# 应用初始化
# =============================================================================

config = load_config()
task_manager: Optional[TaskManager] = None
auto_scheduler = None  # AutoScheduler 实例
discovery_service = None  # UDPDiscoveryService 实例
SETUP_REQUIRED = not bool(config.worker.url) and not bool(config.workers)  # 如果没有 worker 配置，说明需要配置
_config_lock = asyncio.Lock()  # 配置更新并发锁


@asynccontextmanager
async def lifespan(app: FastAPI):
    global task_manager, auto_scheduler, discovery_service
    logger.info(f"SSUBB Coordinator v{VERSION} 启动")

    if SETUP_REQUIRED:
        logger.warning("未检测到配置文件或 Worker 配置，进入 Setup 引导模式")
    else:
        _init_services()

    yield
    if task_manager and hasattr(task_manager, 'registry'):
        await task_manager.registry.stop_heartbeat()
    if auto_scheduler:
        auto_scheduler.stop()
    if discovery_service:
        await discovery_service.stop()
    logger.info("SSUBB Coordinator 关闭")

def _init_services():
    """初始化核心调度服务 (可热启动)"""
    global task_manager, auto_scheduler, discovery_service, config

    from .worker_registry import WorkerRegistry

    # 创建或重载注册中心
    if task_manager and hasattr(task_manager, 'registry'):
        task_manager.registry.reload_config(config)
        worker_registry = task_manager.registry
    else:
        worker_registry = WorkerRegistry(config)

    if task_manager is None:
        task_manager = TaskManager(config, worker_registry)
        task_manager.start_watcher()

        from .scanner import MediaScanner
        from .scheduler import AutoScheduler
        scanner = MediaScanner(task_manager.checker, task_manager.store)
        auto_scheduler = AutoScheduler(config, task_manager, scanner)
        task_manager.scheduler = auto_scheduler
        auto_scheduler.start()

    # 启动心跳轮询
    asyncio.create_task(worker_registry.start_heartbeat())

    # 启动自动发现服务
    if config.discovery.enabled and discovery_service is None:
        from .discovery import UDPDiscoveryService

        async def _on_worker_discovered(url: str) -> bool:
            """发现新 Worker 时的回调"""
            existing_urls = {w.url for w in config.workers}
            if url in existing_urls:
                return False
            new_worker = WorkerNodeConfig(url=url, weight=1, enabled=True)
            config.workers.append(new_worker)
            worker_registry.reload_config(config)
            # 持久化到配置文件
            from .config import save_config
            save_config(config.model_dump())
            logger.info(f"自动注册新 Worker: {url}")
            return True

        coordinator_url = f"http://{config.host}:{config.port}"
        discovery_service = UDPDiscoveryService(
            coordinator_url=coordinator_url,
            port=config.discovery.port,
            auto_register=config.discovery.auto_register,
            on_worker_discovered=_on_worker_discovered,
        )
        asyncio.create_task(discovery_service.start())

    worker_urls = [w.url for w in config.workers if w.enabled]
    logger.info(f"  Workers: {worker_urls or '未配置'}")
    logger.info(f"  Emby: {config.emby.server or '未配置'}")
    logger.info(f"  数据库: {config.db_path}")
    logger.info(f"  自动化: {'已启用' if config.automation.enabled else '已关闭'}")
    logger.info(f"  自动发现: {'已启用' if config.discovery.enabled else '已关闭'}")


async def _push_config_to_workers(global_config: dict):
    """推送全局配置到所有在线 Worker"""
    if not task_manager or not hasattr(task_manager, 'registry'):
        return
    for client, status, _ in task_manager.registry.get_online_workers():
        try:
            ok = await client.push_config(global_config)
            if ok:
                logger.info(f"配置已推送到 {status.worker_id or status.url}")
            else:
                logger.warning(f"推送配置到 {status.worker_id or status.url} 失败")
        except Exception as e:
            logger.warning(f"推送配置到 {status.worker_id or status.url} 异常: {e}")


app = FastAPI(
    title=f"{PROJECT_NAME} Coordinator API",
    version=VERSION,
    description=f"{PROJECT_NAME} — 异地分布式字幕转写翻译系统 REST API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# =============================================================================
# 任务 API
# =============================================================================

@app.post("/api/task", response_model=TaskInfo, tags=["任务管理"])
async def create_task(req: TaskCreate):
    """创建字幕任务 (MoviePilot / 手动触发)"""
    if SETUP_REQUIRED:
        raise HTTPException(status_code=503, detail="系统未配置，请访问控制台完成初始化")
    task = await task_manager.create_task(req)
    return task


@app.post("/api/task/force", tags=["任务管理"])
async def force_regenerate(media_path: str, target_lang: str = "zh"):
    """强制重新生成字幕 (忽略所有跳过逻辑)"""
    if SETUP_REQUIRED:
        raise HTTPException(status_code=503, detail="系统未配置，请访问控制台完成初始化")
    task = await task_manager.force_regenerate(media_path, target_lang)
    return task


@app.get("/api/task/{task_id}", response_model=TaskInfo, tags=["任务管理"])
async def get_task(task_id: str):
    """查询单个任务状态"""
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/task/{task_id}/detail", tags=["任务管理"])
async def get_task_detail(task_id: str):
    """查询任务详情 (含阶段耗时、错误详情、结果摘要)"""
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "task": task.model_dump(),
        "stage_times": task.stage_times,
        "result_summary": task.result_summary,
    }


@app.post("/api/task/{task_id}/retry", tags=["任务管理"])
async def retry_task(task_id: str):
    """手动重试失败的任务"""
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = await task_manager.retry_task(task_id)
    if result is None:
        raise HTTPException(status_code=400, detail="重试失败")

    return APIResponse(
        success=True,
        message=f"任务已重新排队 (第 {result.retry_count} 次重试)",
        data={"task_id": task_id, "status": result.status},
    )


@app.get("/api/tasks", response_model=TaskListResponse, tags=["任务管理"])
async def get_tasks(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询任务列表"""
    if SETUP_REQUIRED:
        return TaskListResponse(total=0, tasks=[])
    tasks = task_manager.get_tasks(status=status, limit=limit, offset=offset)
    total = task_manager.get_task_count(status=status)
    return TaskListResponse(total=total, tasks=tasks)


# =============================================================================
# 字幕管理 API
# =============================================================================

@app.get("/api/task/{task_id}/subtitle", tags=["字幕管理"])
async def get_subtitle(task_id: str):
    """获取任务的字幕内容"""
    sub = task_manager.store.get_subtitle(task_id)
    if sub:
        return sub
    # Fallback: 检查任务是否完成
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成，字幕不可用")
    raise HTTPException(status_code=404, detail="字幕未找到")


@app.put("/api/task/{task_id}/subtitle", tags=["字幕管理"])
async def update_subtitle(task_id: str, request: Request):
    """手动编辑字幕内容"""
    body = await request.json()
    srt_content = body.get("srt_content", "")
    if not srt_content:
        raise HTTPException(status_code=400, detail="srt_content 不能为空")

    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 保存到数据库
    task_manager.store.update_subtitle_content(task_id, srt_content)

    # 重写磁盘文件
    from .subtitle_writer import SubtitleWriter
    writer = task_manager.writer
    subtitle_path = writer.write_subtitle(
        video_path=task.media_path,
        subtitle_content=srt_content,
        target_lang=task.target_lang,
    )

    return APIResponse(
        success=True,
        message="字幕已更新",
        data={"subtitle_path": subtitle_path},
    )


@app.post("/api/task/{task_id}/subtitle/reoptimize", tags=["字幕管理"])
async def reoptimize_subtitle(task_id: str, request: Request):
    """对指定段落重新调用 LLM 优化"""
    body = await request.json()
    segment_indices = body.get("segment_indices", [])
    if not segment_indices:
        raise HTTPException(status_code=400, detail="segment_indices 不能为空")

    sub = task_manager.store.get_subtitle(task_id)
    if not sub:
        raise HTTPException(status_code=404, detail="字幕未找到")

    # 将选中段落发给 Worker 重新处理
    task = task_manager.get_task(task_id)
    worker_client = None
    if task and task.worker_id:
        worker_client = task_manager.registry.get_client_by_url(task.worker_id)

    if not worker_client:
        # 选择任意在线 Worker
        online = task_manager.registry.get_online_workers()
        if online:
            worker_client = online[0][0]

    if not worker_client:
        raise HTTPException(status_code=503, detail="无在线 Worker 可用")

    try:
        # 解析 SRT 条目
        import re
        srt_content = sub["srt_content"]
        entries = []
        blocks = re.split(r"\n\s*\n", srt_content.strip())
        time_pattern = re.compile(
            r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}"
        )
        for block in blocks:
            lines = block.strip().split("\n")
            timecode = None
            text_start = 0
            for i, line in enumerate(lines):
                if time_pattern.search(line):
                    timecode = line.strip()
                    text_start = i + 1
                    break
            if timecode:
                text_val = "\n".join(lines[text_start:]).strip()
                if text_val:
                    entries.append({"timecode": timecode, "text": text_val})

        # 重新优化选中段落
        repaired = await worker_client.reoptimize_segments(entries, segment_indices)
        if repaired:
            # 重建 SRT
            for i, seg in zip(segment_indices, repaired):
                if i < len(entries):
                    entries[i] = seg
            lines = []
            for i, entry in enumerate(entries):
                lines.append(str(i + 1))
                lines.append(entry["timecode"])
                lines.append(entry["text"])
                lines.append("")
            new_srt = "\n".join(lines)
            task_manager.store.update_subtitle_content(task_id, new_srt)

            # 重写磁盘
            task_manager.writer.write_subtitle(
                video_path=task.media_path,
                subtitle_content=new_srt,
                target_lang=task.target_lang,
            )
            return APIResponse(success=True, message=f"已重新优化 {len(repaired)} 个段落")
    except Exception as e:
        logger.error(f"重新优化失败: {e}")
        raise HTTPException(status_code=500, detail=f"重新优化失败: {e}")

    return APIResponse(success=False, message="重新优化未产生变更")


# =============================================================================
# 批量操作 API
# =============================================================================

class BatchRequest(BaseModel):
    """批量操作请求"""
    task_ids: list[str]


# =============================================================================
# 数据洞察 API
# =============================================================================

@app.get("/api/statistics", tags=["数据洞察"])
async def get_statistics(days: int = 30):
    """获取任务统计数据 (最近 N 天)"""
    if SETUP_REQUIRED:
        return {"total": 0, "completed": 0, "failed": 0, "success_rate": 0}
    return task_manager.store.get_statistics(days)


@app.get("/api/statistics/workers", tags=["数据洞察"])
async def get_worker_statistics():
    """获取各 Worker 的统计数据"""
    if SETUP_REQUIRED:
        return {"workers": {}}
    return task_manager.store.get_worker_statistics()


# =============================================================================
# 批量操作 API
# =============================================================================

@app.post("/api/tasks/batch/retry", tags=["批量操作"])
async def batch_retry(req: BatchRequest):
    """批量重试失败的任务"""
    if not req.task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")
    affected = 0
    for tid in req.task_ids:
        task = task_manager.get_task(tid)
        if task and task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            result = await task_manager.retry_task(tid)
            if result:
                affected += 1
    return APIResponse(success=True, message=f"已重试 {affected} 个任务", data={"affected": affected})


@app.post("/api/tasks/batch/cancel", tags=["批量操作"])
async def batch_cancel(req: BatchRequest):
    """批量取消 pending 任务"""
    if not req.task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")
    affected = 0
    for tid in req.task_ids:
        task = task_manager.get_task(tid)
        if task and task.status == TaskStatus.PENDING:
            task_manager.store.update_status(tid, TaskStatus.CANCELLED)
            affected += 1
    return APIResponse(success=True, message=f"已取消 {affected} 个任务", data={"affected": affected})


@app.post("/api/tasks/batch/delete", tags=["批量操作"])
async def batch_delete(req: BatchRequest):
    """批量删除已完成/失败/跳过的任务"""
    if not req.task_ids:
        raise HTTPException(status_code=400, detail="task_ids 不能为空")
    # 只允许删除非活跃任务
    allowed_statuses = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
    to_delete = []
    for tid in req.task_ids:
        task = task_manager.get_task(tid)
        if task and task.status in allowed_statuses:
            to_delete.append(tid)
    if not to_delete:
        raise HTTPException(status_code=400, detail="没有可删除的任务（只能删除已完成/失败/跳过的任务）")
    affected = task_manager.store.batch_delete(to_delete)
    return APIResponse(success=True, message=f"已删除 {affected} 个任务", data={"affected": affected})


# =============================================================================
# Worker 回调
# =============================================================================

@app.post("/api/task/{task_id}/priority", tags=["任务管理"])
async def update_task_priority(task_id: str, request: Request):
    """修改任务优先级 (仅 pending 状态)"""
    body = await request.json()
    priority = body.get("priority", 3)
    if not (1 <= priority <= 5):
        raise HTTPException(status_code=400, detail="优先级必须在 1-5 之间")

    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail="仅 pending 状态的任务可修改优先级")

    task_manager.store.update_priority(task_id, priority)
    return APIResponse(success=True, message=f"优先级已更新为 {priority}")


@app.post("/api/result", tags=["Worker 回调"])
async def receive_result(result: WorkerTaskResult):
    """接收 Worker 的任务结果回调"""
    success = await task_manager.handle_result(result)
    return APIResponse(success=success, message="OK" if success else "处理失败")


@app.post("/api/progress", tags=["Worker 回调"])
async def receive_progress(update: WorkerProgressUpdate):
    """接收 Worker 的进度更新"""
    task_manager.update_progress(update.task_id, update.status, update.progress)
    return APIResponse(success=True)


# =============================================================================
# Emby Webhook
# =============================================================================

@app.post("/emby", tags=["Webhook"])
async def emby_webhook(request: Request):
    """接收 Emby webhook 事件

    支持事件:
    - library.new: 新媒体入库
    - playback.start: 播放开始 (可用于按需生成)
    """
    try:
        form = await request.form()
        data_str = form.get("data")
        if not data_str:
            return APIResponse(success=False, message="空请求")

        import json
        data = json.loads(data_str)
        event = data.get("Event", "")

        # 测试通知
        if event == "system.notificationtest":
            logger.info("Emby 测试通知收到!")
            return APIResponse(success=True, message="测试通知收到")

        # 处理媒体事件
        if event in ("library.new", "playback.start"):
            item = data.get("Item", {})
            item_path = item.get("Path", "")
            item_name = item.get("Name", "")
            item_type = "movie" if item.get("Type") == "Movie" else "tv"

            if not item_path:
                return APIResponse(success=False, message="无文件路径")

            logger.info(f"Emby 事件 [{event}]: {item_name} ({item_path})")

            req = TaskCreate(
                media_path=item_path,
                media_title=item_name,
                media_type=item_type,
            )
            task = await task_manager.create_task(req)
            return APIResponse(
                success=True,
                message=f"任务已创建: {task.id}",
                data={"task_id": task.id, "status": task.status},
            )

        return APIResponse(success=True, message=f"忽略事件: {event}")

    except Exception as e:
        logger.exception(f"Emby webhook 处理失败: {e}")
        return APIResponse(success=False, message=str(e))


# =============================================================================
# 通用 Webhook
# =============================================================================

@app.post("/api/webhook", tags=["Webhook"])
async def generic_webhook(request: Request):
    """通用 Webhook 入口

    接受 JSON 或 form 数据，创建字幕任务。
    必填字段: media_path
    可选字段: media_title, media_type, target_lang, priority, callback_url

    认证: 如果配置了 webhook.token，需要在 Header 中传 X-SSUBB-Token
    """
    if not config.webhook.enabled:
        raise HTTPException(status_code=403, detail="Webhook 已禁用")

    # Token 认证
    if config.webhook.token:
        token = request.headers.get("X-SSUBB-Token", "")
        if token != config.webhook.token:
            raise HTTPException(status_code=401, detail="认证失败")

    # 解析请求体
    try:
        content_type = request.headers.get("content-type", "")
        if "json" in content_type:
            body = await request.json()
        else:
            form = await request.form()
            body = dict(form)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"请求体解析失败: {e}")

    # 必填字段
    media_path = body.get("media_path")
    if not media_path:
        raise HTTPException(status_code=400, detail="缺少必填字段: media_path")

    # 构建任务请求
    try:
        priority = int(body.get("priority", 3))
        if not (1 <= priority <= 5):
            priority = 3
    except (ValueError, TypeError):
        priority = 3

    req = TaskCreate(
        media_path=media_path,
        media_title=body.get("media_title"),
        media_type=body.get("media_type", "unknown"),
        target_lang=body.get("target_lang", "zh"),
        priority=priority,
        callback_url=body.get("callback_url"),
    )

    task = await task_manager.create_task(req)
    logger.info(f"Webhook 创建任务: {task.id} ({req.media_title or req.media_path})")

    return APIResponse(
        success=True,
        message=f"任务已创建: {task.id}",
        data={"task_id": task.id, "status": task.status, "priority": task.priority},
    )


# =============================================================================
# 系统状态
# =============================================================================

@app.get("/api/status", response_model=SystemStatus, tags=["系统状态"])
async def system_status():
    """系统状态检查"""
    if SETUP_REQUIRED:
        return SystemStatus(
            version=VERSION,
            coordinator_online=True,
            worker=None,
            workers=[],
        )

    workers = task_manager.registry.get_all_statuses()
    stats = task_manager.get_stats()

    # 统计活跃任务数
    active_count = sum(
        stats.get(s, 0) for s in TaskStatus.ACTIVE if s != TaskStatus.PENDING
    )

    return SystemStatus(
        version=VERSION,
        coordinator_online=True,
        worker=workers[0] if workers else None,  # 向后兼容
        workers=workers,
        tasks_pending=stats.get(TaskStatus.PENDING, 0),
        tasks_active=active_count,
        tasks_completed=stats.get(TaskStatus.COMPLETED, 0),
        tasks_failed=stats.get(TaskStatus.FAILED, 0),
    )

@app.get("/api/fs", tags=["系统状态"])
async def api_fs_browser(path: Optional[str] = None):
    """服务器物理文件浏览器"""
    import os
    import platform
    from pathlib import Path

    # 支持的媒体后缀
    MEDIA_EXTS = {'.mp4', '.mkv', '.avi', '.ts', '.mov', '.wmv', '.flv', '.rmvb'}

    # 根目录策略
    if not path:
        if platform.system() == "Windows":
            # 返回所有驱动器盘符
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:")]
            return {"current_path": "", "parent_path": "", "dirs": drives, "files": []}
        else:
            path = "/"

    # 路径遍历防护: 禁止 .. 组件
    if ".." in path.replace("\\", "/").split("/"):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    target = Path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")

    dirs = []
    files = []
    
    try:
        for entry in os.scandir(target):
            if entry.is_dir():
                dirs.append(entry.name)
            elif entry.is_file() and Path(entry.name).suffix.lower() in MEDIA_EXTS:
                # 附带文件大小 MB
                size_mb = round(entry.stat().st_size / (1024 * 1024), 1)
                files.append({"name": entry.name, "size_mb": size_mb})
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
        
    dirs.sort()
    files.sort(key=lambda x: x["name"])

    return {
        "current_path": str(target.absolute()),
        "parent_path": str(target.parent.absolute()) if target.parent != target else "",
        "dirs": dirs,
        "files": files
    }

# =============================================================================
# 自动化 API
# =============================================================================

@app.get("/api/automation/status", tags=["自动化"])
async def automation_status():
    """查询自动化调度器状态"""
    if auto_scheduler is None:
        return {"enabled": False, "message": "调度器未初始化"}
    return auto_scheduler.get_status()


@app.post("/api/automation/scan", tags=["自动化"])
async def trigger_scan():
    """手动触发一次媒体库扫描"""
    if auto_scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    result = await auto_scheduler.trigger_scan()
    return APIResponse(success=True, message="扫描完成", data=result)


@app.post("/api/automation/toggle", tags=["自动化"])
async def toggle_automation(enabled: bool = True):
    """开关自动化调度"""
    if auto_scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    auto_scheduler.enabled = enabled
    return APIResponse(
        success=True,
        message=f"自动化已{'\u542f\u7528' if enabled else '\u5173\u95ed'}",
    )


# =============================================================================
# Worker 管理 API
# =============================================================================

@app.get("/api/workers", tags=["Worker 管理"])
async def list_workers():
    """获取所有 Worker 状态"""
    if not task_manager or not hasattr(task_manager, 'registry'):
        return {"workers": []}
    statuses = task_manager.registry.get_all_statuses()
    perf_stats = task_manager.registry.get_performance_stats()
    workers_data = []
    for s in statuses:
        d = s.model_dump()
        perf = perf_stats.get(s.url, {})
        d["adaptive_weight"] = perf.get("adaptive_weight", s.weight)
        d["performance_samples"] = perf.get("samples", 0)
        d["avg_rate"] = perf.get("avg_rate", 0)
        workers_data.append(d)
    return {"workers": workers_data}


@app.post("/api/workers/{worker_url}/toggle", tags=["Worker 管理"])
async def toggle_worker(worker_url: str, request: Request):
    """启用/禁用指定 Worker 节点"""
    global config
    body = await request.json()
    enabled = body.get("enabled", True)

    from .config import save_config
    cfg_dict = config.model_dump()
    found = False
    for w in cfg_dict.get("workers", []):
        if w["url"].rstrip("/") == worker_url.rstrip("/"):
            w["enabled"] = enabled
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Worker not found")

    save_config(cfg_dict)
    config = load_config()
    _init_services()

    return APIResponse(
        success=True,
        message=f"Worker {worker_url} 已{'启用' if enabled else '关闭'}",
    )


@app.get("/api/discovery/status", tags=["自动发现"])
async def get_discovery_status():
    """获取自动发现服务状态"""
    if not discovery_service:
        return {"enabled": False, "peers": {}}
    peers = discovery_service.get_discovered_peers()
    return {
        "enabled": config.discovery.enabled,
        "port": config.discovery.port,
        "auto_register": config.discovery.auto_register,
        "peers": peers,
    }


@app.post("/api/discovery/register", tags=["自动发现"])
async def register_discovered_worker(request: Request):
    """手动注册一个发现的 Worker"""
    global config
    body = await request.json()
    url = body.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    existing_urls = {w.url for w in config.workers}
    if url in existing_urls:
        return APIResponse(success=False, message="Worker 已存在于配置中")

    from .config import save_config
    new_worker = WorkerNodeConfig(url=url, weight=1, enabled=True)
    config.workers.append(new_worker)

    cfg_dict = config.model_dump()
    save_config(cfg_dict)
    config = load_config()
    _init_services()

    return APIResponse(success=True, message=f"Worker {url} 已注册")


@app.get("/api/health", tags=["系统状态"])
async def get_health():
    """配置健康度检查"""
    checks = {}
    suggestions = []
    score = 0
    total = 0

    # 1. Worker 已配置
    total += 1
    if config.workers:
        checks["worker_configured"] = {"pass": True, "message": f"已配置 {len(config.workers)} 个 Worker"}
        score += 1
    else:
        checks["worker_configured"] = {"pass": False, "message": "未配置 Worker", "suggestion": "请在设置中添加 Worker 节点"}
        suggestions.append("添加 Worker 节点以启用转写功能")

    # 2. Worker 在线
    total += 1
    if task_manager and hasattr(task_manager, 'registry'):
        online = task_manager.registry.get_online_workers()
        if online:
            names = [s.worker_id or s.url for _, s, _ in online]
            checks["worker_online"] = {"pass": True, "message": f"{len(online)} 个 Worker 在线: {', '.join(names)}"}
            score += 1
        else:
            checks["worker_online"] = {"pass": False, "message": "无 Worker 在线", "suggestion": "请检查 Worker 是否已启动"}
            suggestions.append("启动至少一个 Worker 节点")
    else:
        checks["worker_online"] = {"pass": False, "message": "服务未初始化"}

    # 3. LLM 配置检查 (通过 Worker 心跳间接检查)
    total += 1
    # 我们无法直接检查 Worker 的 LLM 配置，但可以标记为信息项
    checks["llm_hint"] = {"pass": True, "message": "LLM 配置由 Worker 端管理"}

    # 4. Emby 配置
    total += 1
    if config.emby.server and config.emby.api_key:
        checks["emby_configured"] = {"pass": True, "message": f"Emby 已配置: {config.emby.server}"}
        score += 1
    elif not config.emby.server:
        checks["emby_configured"] = {"pass": True, "message": "Emby 未配置（可选）"}
        score += 1
    else:
        checks["emby_configured"] = {"pass": False, "message": "Emby API Key 未配置", "suggestion": "填写 Emby API Key 以启用入库刷新"}
        suggestions.append("配置 Emby API Key")

    # 5. 自动化配置
    total += 1
    if config.automation.enabled and config.automation.scan_paths:
        checks["automation"] = {"pass": True, "message": f"自动化已启用，{len(config.automation.scan_paths)} 个扫描路径"}
        score += 1
    elif config.automation.enabled:
        checks["automation"] = {"pass": False, "message": "自动化已启用但未配置扫描路径", "suggestion": "添加扫描路径以自动检测无字幕影片"}
        suggestions.append("配置自动化扫描路径")
    else:
        checks["automation"] = {"pass": True, "message": "自动化未启用（可选）"}
        score += 1

    percentage = round(score / total * 100) if total > 0 else 0

    return {
        "score": percentage,
        "checks": checks,
        "suggestions": suggestions,
    }


@app.get("/api/logs", tags=["系统状态"])
async def api_get_logs(lines: int = 100):
    """抓取服务器最新运行日志用于控制台显示"""
    from pathlib import Path
    log_path = Path("./data/ssubb.log")
    if not log_path.exists():
        return {"logs": ["尚未生成任何日志。"]}

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            last_lines = deque(f, lines)
        return {"logs": list(last_lines)}
    except Exception as e:
        return {"logs": [f"读取日志失败: {e}"]}


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """WebSocket 实时日志流"""
    await websocket.accept()
    history, queue = log_broadcaster.subscribe()
    try:
        # 先发送历史日志
        for line in history:
            await websocket.send_text(line)
        # 实时流
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        log_broadcaster.unsubscribe(queue)


# =============================================================================
# 监控 API
# =============================================================================

@app.get("/api/monitor/llm", tags=["系统监控"])
async def llm_monitor():
    """所有 Worker 的 LLM 健康状态"""
    if not task_manager or not hasattr(task_manager, 'registry'):
        return {}
    results = {}
    for client, status, _ in task_manager.registry.get_online_workers():
        try:
            llm_health = await client.get_llm_health()
            results[status.worker_id or status.url] = llm_health
        except Exception as e:
            results[status.worker_id or status.url] = [{"error": str(e)}]
    return results


@app.get("/api/monitor/scans", tags=["系统监控"])
async def scan_history():
    """最近 10 次扫描结果"""
    if not task_manager:
        return []
    try:
        return task_manager.store.get_scan_history(limit=10)
    except Exception:
        return []


# =============================================================================
# 配置管理 API
# =============================================================================

class ConfigUpdateRequest(BaseModel):
    """部分配置更新"""
    workers: Optional[list] = None
    subtitle: Optional[dict] = None
    automation: Optional[dict] = None
    checker: Optional[dict] = None
    emby: Optional[dict] = None
    llm_providers: Optional[list] = None
    translate: Optional[dict] = None
    optimize: Optional[dict] = None


@app.get("/api/config", tags=["配置"])
async def get_config():
    """获取当前配置 (敏感字段脱敏)"""
    cfg = config.model_dump()
    if cfg.get("emby", {}).get("api_key"):
        cfg["emby"]["api_key"] = "***"
    for w in cfg.get("workers", []):
        pass  # workers 无敏感字段
    return cfg


@app.put("/api/config", tags=["配置"])
async def update_config(req: ConfigUpdateRequest):
    """更新配置并热重载 (带并发锁)"""
    global config

    async with _config_lock:
        from .config import save_config
        cfg_dict = config.model_dump()

        if req.workers is not None:
            cfg_dict["workers"] = req.workers
        if req.subtitle is not None:
            cfg_dict["subtitle"].update(req.subtitle)
        if req.automation is not None:
            cfg_dict["automation"].update(req.automation)
        if req.checker is not None:
            cfg_dict["checker"].update(req.checker)
        if req.emby is not None:
            if req.emby.get("api_key") == "***":
                req.emby.pop("api_key")
            cfg_dict["emby"].update(req.emby)
        if req.llm_providers is not None:
            cfg_dict["llm_providers"] = req.llm_providers
        if req.translate is not None:
            cfg_dict.setdefault("translate", {}).update(req.translate)
        if req.optimize is not None:
            cfg_dict.setdefault("optimize", {}).update(req.optimize)

        save_config(cfg_dict)
        config = load_config()
        _init_services()

        # 推送全局配置到在线 Worker
        global_config = {}
        if req.llm_providers is not None:
            global_config["llm_providers"] = req.llm_providers
        if req.translate is not None:
            global_config["translate"] = req.translate
        if req.optimize is not None:
            global_config["optimize"] = req.optimize
        if global_config and task_manager and hasattr(task_manager, 'registry'):
            await _push_config_to_workers(global_config)

    return APIResponse(success=True, message="配置已保存并热重载")


# =============================================================================
# WebUI (静态文件挂载)
# =============================================================================
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

# 判断并创建静态文件目录
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# 挂载 /static 目录
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root_webui():
    """根路径返回酷炫 WebUI 页面或配置引导页面"""
    if SETUP_REQUIRED:
        setup_file = STATIC_DIR / "setup.html"
        if setup_file.exists():
            return FileResponse(str(setup_file))
        return {"message": "Please configure config.yaml first. (setup.html not found)"}
        
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "service": f"{PROJECT_NAME} Coordinator",
        "version": VERSION,
        "docs": "/docs",
        "message": "WebUI is under construction"
    }

class SetupRequest(BaseModel):
    worker_url: str
    output_mode: str = "bilingual"
    output_format: str = "ass"
    emby_server: str = ""
    emby_api_key: str = ""
    enable_automation: bool = False
    scan_paths: list[str] = []

@app.post("/api/setup", tags=["配置"])
async def apply_setup(req: SetupRequest):
    """保存配置并热启动系统"""
    global SETUP_REQUIRED, config
    
    if not SETUP_REQUIRED:
        return {"code": 0, "msg": "系统已配置，无需重复初始化"}
        
    # 生成 coordinator 配置字典
    from .config import save_config, load_config
    
    cfg = {
        "host": "0.0.0.0",
        "port": 8787,
        "db_path": "./data/ssubb.db",
        "audio": {
            "format": "flac",
            "sample_rate": 16000,
            "channels": 1,
            "temp_dir": "./data/audio_temp"
        },
        "worker": {
            "url": req.worker_url,
            "heartbeat_interval": 30,
            "heartbeat_timeout": 300
        },
        "workers": [
            {"url": req.worker_url, "weight": 1, "enabled": True}
        ],
        "emby": {
            "server": req.emby_server,
            "api_key": req.emby_api_key
        },
        "subtitle": {
            "target_language": "zh",
            "naming_format": "{video_name}.{lang}.srt",
            "backup_existing": True,
            "output_mode": req.output_mode,
            "output_format": req.output_format
        },
        "checker": {
            "min_coverage": 0.7,
            "min_density": 2.0,
            "check_language": True
        },
        "retry": {
            "max_retries": 3,
            "backoff_base": 60,
            "backoff_multiplier": 2
        },
        "stage_timeout": {
            "extracting": 600,
            "uploading": 600,
            "transcribing": 3600,
            "translating": 1800,
            "default": 1800
        },
        "automation": {
            "enabled": req.enable_automation,
            "scan_paths": req.scan_paths,
            "scan_recursive": True,
            "scan_recent_days": 7,
            "schedule_start": "02:00",
            "schedule_end": "06:00",
            "scan_interval": 30,
            "max_tasks_per_scan": 5,
            "require_worker_idle": True,
            "preheat_next_episode": True
        }
    }
    
    # 保存并重新加载
    save_config(cfg)
    config = load_config()
    
    # 启动核心服务
    _init_services()
    SETUP_REQUIRED = False
    
    return {"code": 0, "msg": "配置已保存，系统已热启动！刷新页面即可"}


# =============================================================================
# 启动入口
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "coordinator.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )
