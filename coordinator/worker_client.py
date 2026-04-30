"""SSUBB Coordinator - Worker HTTP 客户端

通过 Tailscale 与远程 GPU Worker 通信。
"""

import asyncio
import hashlib
import json
import logging
import math
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

    def __init__(self, worker_url: str, worker_token: str = ""):
        self.worker_url = worker_url.rstrip("/")
        self.base_url = self.worker_url
        self.worker_token = worker_token
        self._http: Optional[httpx.AsyncClient] = None

    def _auth_headers(self) -> dict:
        """返回认证头"""
        if self.worker_token:
            return {"X-Worker-Token": self.worker_token}
        return {}

    def _get_client(self, timeout: float = STATUS_TIMEOUT) -> httpx.AsyncClient:
        """获取或创建共享 httpx 客户端"""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=timeout)
        return self._http

    async def close(self):
        """关闭 httpx 客户端，释放连接"""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

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

        client = self._get_client(timeout=60.0)
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
                    continue  # 已送达

                uploaded_success = False
                # 某个分块最多重传 3 次
                for attempt in range(3):
                    try:
                        headers = {
                            "X-Task-ID": task_id,
                            "X-Chunk-Index": str(chunk_index),
                            "X-Total-Chunks": str(total_chunks),
                            "X-File-Hash": file_hash,
                            "X-File-Name": file_path.name,
                            **self._auth_headers(),
                        }
                        if chunk_index == total_chunks - 1:
                            headers["X-Config"] = json.dumps(config.model_dump())

                        upload_res = await client.post(
                            f"{self.base_url}/api/task/upload_chunk",
                            headers=headers,
                            content=chunk_data,
                        )
                        if upload_res.status_code == 200:
                            uploaded_success = True
                            break
                        else:
                            logger.warning(f"块 {chunk_index} 失败，HTTP {upload_res.status_code}")
                    except Exception as e:
                        logger.warning(f"块 {chunk_index} 网络异常: {e}")

                    await asyncio.sleep(2 * (attempt + 1))

                if not uploaded_success:
                    logger.error(f"[{task_id}] 传输中断，网络错误")
                    return False

        logger.info(f"[{task_id}] 文件完整并成功分发！")
        return True

    async def get_status(self) -> Optional[WorkerHeartbeat]:
        """查询 Worker 状态"""
        try:
            client = self._get_client(STATUS_TIMEOUT)
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
            client = self._get_client(STATUS_TIMEOUT)
            response = await client.delete(
                f"{self.worker_url}/api/task/{task_id}",
                headers=self._auth_headers(),
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"取消任务失败: {e}")
            return False

    async def get_llm_health(self) -> list[dict]:
        """代理请求 Worker 的 /api/llm/health"""
        try:
            client = self._get_client(STATUS_TIMEOUT)
            response = await client.get(f"{self.worker_url}/api/llm/health")
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"LLM 健康查询失败: {e}")
        return []

    async def push_config(self, config_data: dict) -> bool:
        """推送配置更新到 Worker"""
        try:
            client = self._get_client(STATUS_TIMEOUT)
            response = await client.put(
                f"{self.worker_url}/api/config",
                json=config_data,
                headers=self._auth_headers(),
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"推送配置到 Worker 失败: {e}")
            return False

    async def reoptimize_segments(
        self, entries: list[dict], segment_indices: list[int]
    ) -> Optional[list[dict]]:
        """请求 Worker 对指定段落重新优化"""
        try:
            client = self._get_client(120)
            response = await client.post(
                f"{self.worker_url}/api/task/reoptimize",
                json={
                    "entries": entries,
                    "segment_indices": segment_indices,
                },
                headers=self._auth_headers(),
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("repaired_segments")
        except Exception as e:
            logger.warning(f"段落重新优化请求失败: {e}")
        return None
