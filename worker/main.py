"""SSUBB Worker - FastAPI 入口

公司 GPU 端的 HTTP 服务，接收 Coordinator 分发的任务，执行转写/翻译流水线。
"""

import asyncio
import json
import logging
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from shared.constants import VERSION, PROJECT_NAME
from shared.models import (
    APIResponse,
    WorkerHeartbeat,
    WorkerTaskRequest,
    WorkerTaskResult,
    TaskConfig,
)

from .config import load_worker_config
from .health import build_heartbeat
from .task_executor import TaskExecutor
from .env_check import run_full_check, print_check_report
from .model_manager import ModelManager

# =============================================================================
# 日志配置
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("ssubb.worker")

# =============================================================================
# 应用初始化
# =============================================================================

config = load_worker_config()
executor: Optional[TaskExecutor] = None
task_queue: asyncio.Queue = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None


async def _process_queue():
    """后台任务处理循环"""
    while True:
        task_data = await task_queue.get()
        try:
            task_id = task_data["task_id"]
            audio_path = task_data["audio_path"]
            task_config = task_data["config"]

            logger.info(f"[{task_id}] 开始处理...")
            result = await executor.execute(task_id, audio_path, task_config)

            # 回调 Coordinator
            if config.coordinator_url:
                await _callback_result(result)

            # 清理临时音频
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception:
                pass

        except Exception as e:
            logger.exception(f"队列处理异常: {e}")
        finally:
            task_queue.task_done()


async def _callback_result(result: WorkerTaskResult):
    """回调处理结果给 Coordinator"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
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
    global executor, _worker_task

    # 启动环境检查
    logger.info("执行环境检查...")
    check_results = run_full_check(config)
    print_check_report(check_results)
    failed = [r for r in check_results if not r.passed and r.required]
    if failed:
        logger.warning(f"环境检查有 {len(failed)} 项必要检查未通过，部分功能可能不可用")

    executor = TaskExecutor(config)
    _worker_task = asyncio.create_task(_process_queue())
    
    logger.info(f"SSUBB Worker v{VERSION} 启动")
    logger.info(f"  Worker ID: {config.worker_id}")
    logger.info(f"  Coordinator: {config.coordinator_url or '未配置'}")
    logger.info(f"  模型: {config.transcribe.model} ({config.transcribe.device})")
    logger.info(f"  翻译: {config.translate.service} → {config.translate.target_language}")
    yield
    if _worker_task:
        _worker_task.cancel()
    logger.info("SSUBB Worker 关闭")


app = FastAPI(
    title=f"{PROJECT_NAME} Worker",
    version=VERSION,
    lifespan=lifespan,
)


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
        
        import hashlib
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
            import shutil
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
    """取消任务 (仅对队列中的任务有效)"""
    # 简单实现: 标记取消，执行器检查
    logger.info(f"收到取消请求: {task_id}")
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
