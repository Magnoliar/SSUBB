"""SSUBB Coordinator - FastAPI 入口

NAS 端的 HTTP 服务，接收 MoviePilot/Emby/手动请求，管理任务生命周期。
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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

from .config import load_config
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
# 应用初始化
# =============================================================================

config = load_config()
task_manager: Optional[TaskManager] = None
auto_scheduler = None  # AutoScheduler 实例
SETUP_REQUIRED = not bool(config.worker.url)  # 如果没有 worker url，说明需要配置


@asynccontextmanager
async def lifespan(app: FastAPI):
    global task_manager, auto_scheduler
    logger.info(f"SSUBB Coordinator v{VERSION} 启动")

    if SETUP_REQUIRED:
        logger.warning("未检测到配置文件或 Worker 配置，进入 Setup 引导模式")
    else:
        _init_services()

    yield
    if auto_scheduler:
        auto_scheduler.stop()
    logger.info("SSUBB Coordinator 关闭")

def _init_services():
    """初始化核心调度服务 (可热启动)"""
    global task_manager, auto_scheduler, config
    if task_manager is None:
        task_manager = TaskManager(config)
        task_manager.start_watcher()

        from .scanner import MediaScanner
        from .scheduler import AutoScheduler
        scanner = MediaScanner(task_manager.checker, task_manager.store)
        auto_scheduler = AutoScheduler(config, task_manager, scanner)
        task_manager.scheduler = auto_scheduler
        auto_scheduler.start()

        logger.info(f"  Worker: {config.worker.url or '未配置'}")
        logger.info(f"  Emby: {config.emby.server or '未配置'}")
        logger.info(f"  数据库: {config.db_path}")
        logger.info(f"  自动化: {'已启用' if config.automation.enabled else '已关闭'}")
        if config.automation.enabled and config.automation.scan_paths:
            logger.info(f"  扫描路径: {config.automation.scan_paths}")


app = FastAPI(
    title=f"{PROJECT_NAME} Coordinator",
    version=VERSION,
    lifespan=lifespan,
)


# =============================================================================
# 任务 API
# =============================================================================

@app.post("/api/task", response_model=TaskInfo)
async def create_task(req: TaskCreate):
    """创建字幕任务 (MoviePilot / 手动触发)"""
    if SETUP_REQUIRED:
        raise HTTPException(status_code=503, detail="系统未配置，请访问控制台完成初始化")
    task = await task_manager.create_task(req)
    return task


@app.post("/api/task/force")
async def force_regenerate(media_path: str, target_lang: str = "zh"):
    """强制重新生成字幕 (忽略所有跳过逻辑)"""
    if SETUP_REQUIRED:
        raise HTTPException(status_code=503, detail="系统未配置，请访问控制台完成初始化")
    task = await task_manager.force_regenerate(media_path, target_lang)
    return task


@app.get("/api/task/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str):
    """查询单个任务状态"""
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/task/{task_id}/detail")
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


@app.post("/api/task/{task_id}/retry")
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


@app.get("/api/tasks", response_model=TaskListResponse)
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
# Worker 回调
# =============================================================================

@app.post("/api/result")
async def receive_result(result: WorkerTaskResult):
    """接收 Worker 的任务结果回调"""
    success = await task_manager.handle_result(result)
    return APIResponse(success=success, message="OK" if success else "处理失败")


@app.post("/api/progress")
async def receive_progress(update: WorkerProgressUpdate):
    """接收 Worker 的进度更新"""
    task_manager.update_progress(update.task_id, update.status, update.progress)
    return APIResponse(success=True)


# =============================================================================
# Emby Webhook
# =============================================================================

@app.post("/emby")
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
# 系统状态
# =============================================================================

@app.get("/api/status", response_model=SystemStatus)
async def system_status():
    """系统状态检查"""
    if SETUP_REQUIRED:
        from shared.models import AutomationStatus
        return SystemStatus(
            version=VERSION,
            uptime_seconds=0,
            active_tasks=0,
            pending_tasks=0,
            total_tasks=0,
            worker=None,
            automation=AutomationStatus(enabled=False, next_scan_time=None)
        )
        
    from .worker_client import WorkerClient
    from shared.models import WorkerStatus, WorkerHeartbeat
    worker_status = None
    if task_manager.worker:
        worker_status = WorkerStatus(
            worker_id="unknown",
            url=task_manager.worker.base_url,
            online=False,
        )
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                res = await client.get(f"{task_manager.worker.base_url}/api/status")
                if res.status_code == 200:
                    health = WorkerHeartbeat(**res.json())
                    worker_status.online = True
                    worker_status.worker_id = health.worker_id
                    worker_status.heartbeat = health
        except Exception:
            pass

    stats = task_manager.get_stats()
    
    # 统计活跃任务数
    active_count = sum(
        stats.get(s, 0) for s in TaskStatus.ACTIVE if s != TaskStatus.PENDING
    )

    return SystemStatus(
        version=VERSION,
        coordinator_online=True,
        worker=worker_status,
        tasks_pending=stats.get(TaskStatus.PENDING, 0),
        tasks_active=active_count,
        tasks_completed=stats.get(TaskStatus.COMPLETED, 0),
        tasks_failed=stats.get(TaskStatus.FAILED, 0),
    )

@app.get("/api/fs")
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

@app.get("/api/automation/status")
async def automation_status():
    """查询自动化调度器状态"""
    if auto_scheduler is None:
        return {"enabled": False, "message": "调度器未初始化"}
    return auto_scheduler.get_status()


@app.post("/api/automation/scan")
async def trigger_scan():
    """手动触发一次媒体库扫描"""
    if auto_scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    result = await auto_scheduler.trigger_scan()
    return APIResponse(success=True, message="扫描完成", data=result)


@app.post("/api/automation/toggle")
async def toggle_automation(enabled: bool = True):
    """开关自动化调度"""
    if auto_scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    auto_scheduler.enabled = enabled
    return APIResponse(
        success=True,
        message=f"自动化已{'\u542f\u7528' if enabled else '\u5173\u95ed'}",
    )


@app.get("/api/logs")
async def api_get_logs(lines: int = 100):
    """抓取服务器最新运行日志用于控制台显示"""
    from pathlib import Path
    log_path = Path("./data/ssubb.log")
    if not log_path.exists():
        return {"logs": ["尚未生成任何日志。"]}
    
    try:
        # 使用快速的队尾读取机制 (如果日志不大可以直接读取)
        # 对于生产级可以用 collections.deque 或尾部 seek，此处简单处理
        import collections
        with open(log_path, "r", encoding="utf-8") as f:
            last_lines = collections.deque(f, lines)
        return {"logs": list(last_lines)}
    except Exception as e:
        return {"logs": [f"读取日志失败: {e}"]}


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

from pydantic import BaseModel
class SetupRequest(BaseModel):
    worker_url: str
    output_mode: str = "bilingual"
    output_format: str = "ass"
    emby_server: str = ""
    emby_api_key: str = ""
    enable_automation: bool = False
    scan_paths: list[str] = []

@app.post("/api/setup")
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
