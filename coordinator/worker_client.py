"""SSUBB Coordinator - Worker HTTP 客户端

通过 Tailscale 与远程 GPU Worker 通信。
"""

import logging
from pathlib import Path
from typing import Optional

import httpx

from shared.models import (
    WorkerHeartbeat,
    WorkerTaskRequest,
    WorkerTaskResult,
    TaskConfig,
)

logger = logging.getLogger("ssubb.worker_client")

# 超时配置 (秒)
UPLOAD_TIMEOUT = 300    # 音频上传 5 分钟
STATUS_TIMEOUT = 10     # 状态查询 10 秒
HEARTBEAT_TIMEOUT = 10  # 心跳 10 秒


class WorkerClient:
    """GPU Worker HTTP 客户端"""

    def __init__(self, worker_url: str):
        self.worker_url = worker_url.rstrip("/")
        self.base_url = self.worker_url

    async def submit_task(
        self,
        task_id: str,
        audio_path: str,
        config: TaskConfig,
        source_lang: str,
        target_lang: str,
    ) -> bool:
        """分块上传任务与音频到 Worker

        增加了: SHA-256 校验, 断点续传和重试机制
        """
        import hashlib
        import asyncio
        from pathlib import Path
        import math
        import json
        
        file_path = Path(audio_path)
        if not file_path.exists():
            return False

        # 计算完整文件的 SHA-256
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        file_hash = sha256_hash.hexdigest()

        # 分块参数 (5MB / chunk)
        chunk_size = 5 * 1024 * 1024
        file_size = file_path.stat().st_size
        total_chunks = math.ceil(file_size / chunk_size)
        
        logger.info(f"[{task_id}] 开始分块上传 (大小: {file_size/1024/1024:.1f}MB, 块数: {total_chunks})")

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. 查询已上传分块 (断点续传)
            received_chunks = []
            try:
                res = await client.get(f"{self.base_url}/api/task/upload_status/{task_id}")
                if res.status_code == 200:
                    received_chunks = res.json().get("received_chunks", [])
                    if received_chunks:
                        logger.info(f"[{task_id}] 断点续传，跳过块: {received_chunks}")
            except Exception as e:
                logger.debug(f"[{task_id}] 无法获取上传状态: {e}")

            # 2. 逐块上传
            with open(file_path, "rb") as f:
                for chunk_index in range(total_chunks):
                    f.seek(chunk_index * chunk_size)
                    chunk_data = f.read(chunk_size)
                    
                    if chunk_index in received_chunks:
                        continue # 已送达
                        
                    uploaded_success = False
                    # 某个分块最多重传 3 次
                    for attempt in range(3):
                        try:
                            headers = {
                                "X-Task-ID": task_id,
                                "X-Chunk-Index": str(chunk_index),
                                "X-Total-Chunks": str(total_chunks),
                                "X-File-Hash": file_hash,  # 仅在最后一块时 Worker 验证
                                "X-File-Name": file_path.name,
                            }
                            # 如果是最后一块，带上任务配置参数
                            if chunk_index == total_chunks - 1:
                                headers["X-Config"] = json.dumps(config.model_dump())
                                
                            upload_res = await client.post(
                                f"{self.base_url}/api/task/upload_chunk",
                                headers=headers,
                                content=chunk_data
                            )
                            if upload_res.status_code == 200:
                                uploaded_success = True
                                break
                            else:
                                logger.warning(f"块 {chunk_index} 失败，HTTP {upload_res.status_code}")
                        except Exception as e:
                            logger.warning(f"块 {chunk_index} 网络异常: {e}")
                            
                        await asyncio.sleep(2 * (attempt + 1)) # 指数退避退避机制
                        
                    if not uploaded_success:
                        logger.error(f"[{task_id}] 传输中断，网络错误")
                        return False

        logger.info(f"[{task_id}] 文件完整并成功分发！")
        return True

    async def get_status(self) -> Optional[WorkerHeartbeat]:
        """查询 Worker 状态"""
        try:
            async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
                response = await client.get(f"{self.worker_url}/api/status")
                if response.status_code == 200:
                    return WorkerHeartbeat(**response.json())
        except Exception as e:
            logger.debug(f"Worker 状态查询失败: {e}")
        return None

    async def check_health(self) -> bool:
        """检查 Worker 是否在线"""
        status = await self.get_status()
        return status is not None

    async def cancel_task(self, task_id: str) -> bool:
        """取消 Worker 上的任务"""
        try:
            async with httpx.AsyncClient(timeout=STATUS_TIMEOUT) as client:
                response = await client.delete(
                    f"{self.worker_url}/api/task/{task_id}"
                )
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"取消任务失败: {e}")
            return False
