"""SSUBB Worker - GPU 健康检查

获取 GPU 状态信息 (NVIDIA)。
"""

import logging
import subprocess
import time
from typing import Optional

from shared.constants import VERSION
from shared.models import WorkerHeartbeat, LLMHealthStatus

logger = logging.getLogger("ssubb.health")

_start_time = time.time()


def get_gpu_info() -> dict:
    """获取 NVIDIA GPU 信息"""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 4:
                return {
                    "gpu_name": parts[0].strip(),
                    "gpu_utilization": int(parts[1].strip()),
                    "vram_used_mb": int(parts[2].strip()),
                    "vram_total_mb": int(parts[3].strip()),
                }
    except Exception as e:
        logger.debug(f"GPU 信息获取失败: {e}")

    return {
        "gpu_name": "Unknown",
        "gpu_utilization": 0,
        "vram_used_mb": 0,
        "vram_total_mb": 0,
    }


def build_heartbeat(
    worker_id: str,
    queue_length: int = 0,
    current_task_id: Optional[str] = None,
    current_progress: int = 0,
) -> WorkerHeartbeat:
    """构建心跳数据"""
    gpu = get_gpu_info()
    return WorkerHeartbeat(
        worker_id=worker_id,
        version=VERSION,
        gpu_name=gpu["gpu_name"],
        gpu_utilization=gpu["gpu_utilization"],
        vram_used_mb=gpu["vram_used_mb"],
        vram_total_mb=gpu["vram_total_mb"],
        queue_length=queue_length,
        current_task_id=current_task_id,
        current_progress=current_progress,
        uptime_seconds=time.time() - _start_time,
    )


async def get_llm_health(llm_client) -> list[LLMHealthStatus]:
    """检测所有 LLM provider 的连通性"""
    return await llm_client.check_health()
