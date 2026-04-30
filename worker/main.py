"""SSUBB Worker - FastAPI 入口

公司 GPU 端的 HTTP 服务，接收 Coordinator 分发的任务，执行转写/翻译流水线。
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile

from shared.constants import VERSION, PROJECT_NAME
from shared.models import (
    APIResponse,
    WorkerHeartbeat,
    WorkerTaskRequest,
    WorkerTaskResult,
    TaskConfig,
)

from .config import load_worker_config, save_worker_config
from .health import build_heartbeat, get_llm_health
from .llm_client import LLMClient
from .task_executor import TaskExecutor
from .env_check import run_full_check, print_check_report
from .model_manager import ModelManager

# =============================================================================
# 日志配置
# =============================================================================

from logging.handlers import RotatingFileHandler

LOG_DIR = Path("./data")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "worker.log"

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

if root_logger.hasHandlers():
    root_logger.handlers.clear()

_formatter = logging.Formatter(
    fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 终端输出
_console = logging.StreamHandler(sys.stderr)
_console.setFormatter(_formatter)
root_logger.addHandler(_console)

# 文件输出 (10MB 轮转，保留 3 个备份)
_file = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file.setFormatter(_formatter)
root_logger.addHandler(_file)

logger = logging.getLogger("ssubb.worker")

# =============================================================================
# 应用初始化
# =============================================================================

config = load_worker_config()
executor: Optional[TaskExecutor] = None
_llm_client: Optional[LLMClient] = None  # 共享 LLM 容灾客户端（健康检查 + 可复用）
task_queue: asyncio.Queue = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None
_active_tasks: dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task (用于取消)
_http_client: Optional[httpx.AsyncClient] = None


async def _process_queue():
    """后台任务处理循环"""
    global _active_tasks
    while True:
        task_data = await task_queue.get()
        task_id = task_data["task_id"]
        audio_path = task_data["audio_path"]
        task_config = task_data["config"]

        # 注册活跃任务 (支持取消)
        current = asyncio.current_task()
        _active_tasks[task_id] = current

        try:
            logger.info(f"[{task_id}] 开始处理...")
            result = await executor.execute(task_id, audio_path, task_config)

            # 回调 Coordinator
            if config.coordinator_url:
                await _callback_result(result)

        except asyncio.CancelledError:
            logger.info(f"[{task_id}] 任务被取消")
        except Exception as e:
            logger.exception(f"队列处理异常: {e}")
            # 通知 Coordinator 任务失败，避免 Coordinator 永久等待
            if config.coordinator_url:
                fail_result = WorkerTaskResult(
                    task_id=task_id,
                    status="failed",
                    error=f"Worker 队列处理异常: {e}",
                )
                await _callback_result(fail_result)
        finally:
            # 清理临时音频 (无论成功/失败/取消)
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception:
                pass
            # 清理任务临时目录
            task_temp = Path(config.temp_dir) / f"{task_id}_chunks"
            if task_temp.exists():
                shutil.rmtree(task_temp, ignore_errors=True)
            _active_tasks.pop(task_id, None)
            task_queue.task_done()


async def _callback_result(result: WorkerTaskResult):
    """回调处理结果给 Coordinator"""
    global _http_client
    try:
        if _http_client is None:
            _http_client = httpx.AsyncClient(timeout=30)
        response = await _http_client.post(
            f"{config.coordinator_url}/api/result",
            json=result.model_dump(),
        )
        if response.status_code == 200:
            logger.info(f"[{result.task_id}] 结果已回调")
        else:
            logger.warning(f"[{result.task_id}] 回调失败: {response.status_code}")
    except Exception as e:
        logger.error(f"[{result.task_id}] 回调异常: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global executor, _worker_task, _http_client, _llm_client

    # 启动环境检查
    logger.info("执行环境检查...")
    check_results = run_full_check(config)
    print_check_report(check_results)
    failed = [r for r in check_results if not r.passed and r.required]
    if failed:
        logger.warning(f"环境检查有 {len(failed)} 项必要检查未通过，部分功能可能不可用")

    executor = TaskExecutor(config)
    _llm_client = LLMClient(config.llm_providers)
    _http_client = httpx.AsyncClient(timeout=30)
    _worker_task = asyncio.create_task(_process_queue())

    # 自动发现：如果未配置 coordinator_url，尝试局域网发现
    discovery_client = None
    if not config.coordinator_url:
        from .discovery_client import UDPDiscoveryClient

        async def _on_coordinator_found(url: str):
            """发现 Coordinator 时自动写入配置"""
            from .config import save_worker_config
            config.coordinator_url = url
            cfg = config.model_dump()
            save_worker_config(cfg)
            logger.info(f"自动发现 Coordinator: {url}，已写入配置")

        discovery_client = UDPDiscoveryClient(
            worker_id=config.worker_id,
            worker_port=config.port,
            on_coordinator_discovered=_on_coordinator_found,
        )
        await discovery_client.start()
        logger.info("未配置 Coordinator 地址，已启动自动发现")

    logger.info(f"SSUBB Worker v{VERSION} 启动")
    logger.info(f"  Worker ID: {config.worker_id}")
    logger.info(f"  Coordinator: {config.coordinator_url or '未配置 (等待自动发现)'}")
    logger.info(f"  模型: {config.transcribe.model} ({config.transcribe.device})")
    logger.info(f"  翻译: {config.translate.service} → {config.translate.target_language}")
    yield
    if discovery_client:
        await discovery_client.stop()
    if _worker_task:
        _worker_task.cancel()
    if _llm_client:
        await _llm_client.close()
    if executor:
        await executor.close()
    if _http_client:
        await _http_client.aclose()
    logger.info("SSUBB Worker 关闭")


app = FastAPI(
    title=f"{PROJECT_NAME} Worker",
    version=VERSION,
    lifespan=lifespan,
)


# =============================================================================
# 认证中间件
# =============================================================================

# 需要认证保护的写操作路径
_PROTECTED_PATHS = {
    "/api/task/upload_chunk",
    "/api/config",
    "/api/task/reoptimize",
}
# DELETE 方法总是需要认证
_PROTECTED_PREFIXES_DELETE = ("/api/task/", "/api/models/")


@app.middleware("http")
async def verify_worker_token(request: Request, call_next):
    """验证 Coordinator 请求的 Token (仅保护写操作)"""
    token = config.security.worker_token
    if not token:
        return await call_next(request)

    method = request.method
    path = request.url.path

    needs_auth = False
    if method == "PUT" and path == "/api/config":
        needs_auth = True
    elif method == "POST" and (path in _PROTECTED_PATHS or path.startswith("/api/task/upload_chunk")):
        needs_auth = True
    elif method == "DELETE":
        needs_auth = True

    if needs_auth:
        req_token = request.headers.get("X-Worker-Token", "")
        if req_token != token:
            return HTTPException(status_code=401, detail="Unauthorized")

    return await call_next(request)


# =============================================================================
# 任务 API (按块接收)
# =============================================================================

@app.get("/api/task/upload_status/{task_id}")
async def get_upload_status(task_id: str):
    """查询分块上传状态 (用于断点续传)"""
    temp_dir = Path(config.temp_dir)
    chunks_received = []
    
    # 查找临时的 .part 文件夹中的 chunk 文件
    chunk_dir = temp_dir / f"{task_id}_chunks"
    if chunk_dir.exists():
        for chunk_file in chunk_dir.glob("chunk_*"):
            try:
                chunk_index = int(chunk_file.name.split("_")[1])
                chunks_received.append(chunk_index)
            except ValueError:
                pass
                
    return {"received_chunks": sorted(chunks_received)}


from fastapi import Request

@app.post("/api/task/upload_chunk")
async def upload_chunk(request: Request):
    headers = request.headers
    task_id = headers.get("X-Task-ID")
    chunk_index = int(headers.get("X-Chunk-Index", 0))
    total_chunks = int(headers.get("X-Total-Chunks", 1))
    file_hash = headers.get("X-File-Hash", "")
    file_name = headers.get("X-File-Name", "audio.flac")
    task_config_str = headers.get("X-Config", "")

    if not task_id:
        raise HTTPException(status_code=400, detail="Missing X-Task-ID")

    # 文件名净化: 防止路径遍历
    file_name = os.path.basename(file_name)
    if not file_name or '..' in file_name or len(file_name) > 255:
        file_name = "audio.flac"
        
    temp_dir = Path(config.temp_dir)
    chunk_dir = temp_dir / f"{task_id}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    
    chunk_path = chunk_dir / f"chunk_{chunk_index}"
    
    # 将请求体写入 chunk 文件
    try:
        with open(chunk_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
    except Exception as e:
        logger.error(f"[{task_id}] 写入 chunk {chunk_index} 失败: {e}")
        raise HTTPException(status_code=500, detail="写入失败")
        
    # 如果是最后一块到达，检查是否所有分块都已集齐
    chunks_present = len(list(chunk_dir.glob("chunk_*")))
    
    if chunks_present == total_chunks:
        # 合并文件
        final_audio_path = temp_dir / f"{task_id}_{file_name}"
        logger.info(f"[{task_id}] 分块全部集齐，开始合并组装...")

        sha256_hash = hashlib.sha256()
        
        try:
            with open(final_audio_path, "wb") as outfile:
                for i in range(total_chunks):
                    idx_path = chunk_dir / f"chunk_{i}"
                    with open(idx_path, "rb") as infile:
                        data = infile.read()
                        outfile.write(data)
                        sha256_hash.update(data)
                        
            # SHA-256 校验防丢包或乱码
            calculated_hash = sha256_hash.hexdigest()
            if file_hash and calculated_hash != file_hash:
                logger.error(f"[{task_id}] ❌ SHA-256 校验失败 (预期: {file_hash}, 实际: {calculated_hash})")
                final_audio_path.unlink()
                raise HTTPException(status_code=400, detail="Hash Mismatch")
                
            logger.info(f"[{task_id}] ✅ SHA-256 校验通过，文件完好无损 ({final_audio_path.stat().st_size/1024/1024:.1f}MB)")
            
            # 清理 chunks 目录
            shutil.rmtree(chunk_dir, ignore_errors=True)
            
            # 压入任务队列
            task_config = TaskConfig(**json.loads(task_config_str)) if task_config_str else TaskConfig()
            
            await task_queue.put({
                "task_id": task_id,
                "audio_path": str(final_audio_path),
                "config": task_config,
            })
            
            return APIResponse(
                success=True,
                message="合并并校验完成，进入队列",
                data={"queue_position": task_queue.qsize()}
            )
            
        except HTTPException as he:
            raise he
        except Exception as e:
            logger.error(f"合并文件失败: {e}")
            raise HTTPException(status_code=500, detail="合并失败")
            
    return APIResponse(success=True, message=f"Chunk {chunk_index} received")

@app.delete("/api/task/{task_id}")
async def cancel_task(task_id: str):
    """取消正在执行的任务"""
    task = _active_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"[{task_id}] 任务已取消")
        return APIResponse(success=True, message="任务已取消")
    logger.info(f"取消请求: {task_id} (未找到活跃任务)")
    return APIResponse(success=True, message="取消请求已记录")


# =============================================================================
# 状态 API
# =============================================================================

@app.get("/api/status")
async def worker_status() -> WorkerHeartbeat:
    """Worker 状态 (GPU 信息 + 队列状态)"""
    return build_heartbeat(
        worker_id=config.worker_id,
        queue_length=task_queue.qsize(),
        current_task_id=executor.current_task_id if executor else None,
        current_progress=executor.current_progress if executor else 0,
    )


@app.get("/")
async def root():
    return {
        "service": f"{PROJECT_NAME} Worker",
        "version": VERSION,
        "worker_id": config.worker_id,
        "docs": "/docs",
    }


# =============================================================================
# 模型管理 API (V0.5)
# =============================================================================

@app.get("/api/models")
async def list_models():
    """列出所有可用 Whisper 模型及安装状态"""
    mgr = ModelManager(config.transcribe.model_dir)
    return {
        "status": mgr.get_status(),
        "models": mgr.list_models(),
    }


@app.post("/api/models/{model_name}/download")
async def download_model(model_name: str):
    """下载指定 Whisper 模型"""
    mgr = ModelManager(config.transcribe.model_dir)
    if mgr.is_installed(model_name):
        return APIResponse(success=True, message=f"模型 {model_name} 已安装")
    success = mgr.download_model(model_name)
    if success:
        return APIResponse(success=True, message=f"模型 {model_name} 下载完成")
    return APIResponse(success=False, message=f"模型下载失败，请手动下载或检查网络")


@app.delete("/api/models/{model_name}")
async def delete_model(model_name: str):
    """删除本地 Whisper 模型"""
    mgr = ModelManager(config.transcribe.model_dir)
    if mgr.delete_model(model_name):
        return APIResponse(success=True, message=f"已删除 {model_name}")
    return APIResponse(success=False, message=f"删除失败")


@app.get("/api/env")
async def env_check():
    """运行环境检查"""
    results = run_full_check(config)
    return {
        "passed": all(r.passed for r in results if r.required),
        "checks": [
            {
                "name": r.name,
                "passed": r.passed,
                "detail": r.detail,
                "required": r.required,
            }
            for r in results
        ],
    }


# =============================================================================
# LLM 健康检查 API
# =============================================================================

@app.get("/api/llm/health")
async def llm_health():
    """所有 LLM 提供商的健康状态"""
    if _llm_client is None:
        return []
    health = await get_llm_health(_llm_client)
    return [h.model_dump() for h in health]


# =============================================================================
# 配置接收 API (Coordinator 推送)
# =============================================================================

@app.post("/api/task/reoptimize")
async def reoptimize_segments(request: Request):
    """对指定段落重新优化（供 Coordinator 调用）"""
    body = await request.json()
    entries = body.get("entries", [])
    segment_indices = body.get("segment_indices", [])

    if not entries or not segment_indices:
        raise HTTPException(status_code=400, detail="entries 和 segment_indices 不能为空")

    from .optimizer import SubtitleOptimizer, _build_system_prompt
    from .srt_parser import SubtitleSegment
    from .config import OptimizeConfig

    # 使用共享的 _llm_client 实例（避免每次创建新客户端）
    llm = _llm_client or LLMClient(config.llm_providers)
    optimizer = SubtitleOptimizer(llm)

    # 构建 SubtitleSegment 列表
    segments = []
    for i, entry in enumerate(entries):
        seg = SubtitleSegment(
            index=i + 1,
            start_time="00:00:00,000",
            end_time="00:00:00,000",
            text=entry.get("text", ""),
        )
        segments.append(seg)

    # 只优化选中的段落（带上下文）
    target_segments = [segments[i] for i in segment_indices if i < len(segments)]
    if not target_segments:
        return {"repaired_segments": []}

    try:
        system_prompt = _build_system_prompt(OptimizeConfig())
        repaired = await optimizer._optimize_chunk(target_segments, system_prompt)
        result = [{"index": s.index, "timecode": entries[segment_indices[i]]["timecode"], "text": s.text}
                  for i, s in enumerate(repaired)]
        return {"repaired_segments": result}
    except Exception as e:
        logger.error(f"重新优化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/config")
async def receive_config(config_data: dict):
    """接收 Coordinator 推送的配置更新

    只更新全局配置字段：llm_providers, translate, optimize
    不覆盖节点配置：transcribe, vram
    """
    global _llm_client, config

    # 读取现有完整配置
    existing = config.model_dump()

    # 只更新允许的字段
    if "llm_providers" in config_data:
        existing["llm_providers"] = config_data["llm_providers"]
    if "translate" in config_data:
        existing["translate"] = {**existing.get("translate", {}), **config_data["translate"]}
    if "optimize" in config_data:
        existing["optimize"] = {**existing.get("optimize", {}), **config_data["optimize"]}

    # 先验证，再持久化（防止无效配置写入磁盘）
    from .config import WorkerConfig
    try:
        config = WorkerConfig(**existing)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"配置验证失败: {e}")

    save_worker_config(existing)

    # 热重载 LLM 客户端
    if config.llm_providers:
        if _llm_client:
            await _llm_client.close()
        _llm_client = LLMClient(config.llm_providers)
        logger.info("配置已更新，LLM 客户端已热重载")

    return APIResponse(success=True, message="配置已更新")


# =============================================================================
# 启动入口
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "worker.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )
