"""SSUBB Coordinator - 多 Worker 注册中心

管理多个 WorkerClient 实例、后台心跳轮询，
为任务调度器提供 Worker 选择查询接口。
"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Optional

from .config import CoordinatorConfig
from .worker_client import WorkerClient
from shared.models import WorkerStatus

logger = logging.getLogger("ssubb.worker_registry")


class WorkerRegistry:
    """多 Worker 管理与健康监控"""

    # 自适应权重：记录最近 N 次任务性能
    _PERF_HISTORY_SIZE = 20

    def __init__(self, config: CoordinatorConfig):
        self._config = config
        self._workers: dict[str, WorkerClient] = {}     # url -> client
        self._statuses: dict[str, WorkerStatus] = {}    # url -> status
        self._weights: dict[str, int] = {}              # url -> weight
        self._performance: dict[str, deque] = {}        # url -> deque of (media_min, wall_sec)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._init_from_config()

    def _init_from_config(self):
        """根据配置创建 WorkerClient 实例"""
        self._workers.clear()
        self._statuses.clear()
        self._weights.clear()

        for w in self._config.workers:
            if w.enabled and w.url:
                url = w.url.rstrip("/")
                self._workers[url] = WorkerClient(url)
                self._weights[url] = w.weight
                self._statuses[url] = WorkerStatus(
                    worker_id=w.worker_id or url,
                    url=url,
                    online=False,
                    weight=w.weight,
                )
                logger.info(f"注册 Worker: {url} (weight={w.weight})")
                if url not in self._performance:
                    self._performance[url] = deque(maxlen=self._PERF_HISTORY_SIZE)

    async def start_heartbeat(self):
        """启动后台心跳轮询"""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_sweep())
            logger.info(f"心跳轮询已启动 ({len(self._workers)} 个 Worker)")

    async def stop_heartbeat(self):
        """停止心跳轮询"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_sweep(self):
        """定期并行轮询所有 Worker 健康状态"""
        interval = self._config.worker.heartbeat_interval
        timeout = self._config.worker.heartbeat_timeout

        while True:
            await asyncio.sleep(interval)
            now = datetime.utcnow()

            # 并行检查所有 Worker
            async def _check_one(url: str, client: WorkerClient):
                try:
                    hb = await client.get_status()
                    return url, hb, None
                except Exception as e:
                    return url, None, e

            checks = [
                _check_one(url, client)
                for url, client in list(self._workers.items())
            ]
            results = await asyncio.gather(*checks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    continue
                url, hb, err = result
                status = self._statuses.get(url)
                if status is None:
                    continue

                if hb:
                    was_offline = not status.online
                    status.online = True
                    status.worker_id = hb.worker_id
                    status.heartbeat = hb
                    status.last_heartbeat = now
                    if was_offline:
                        logger.info(f"Worker {hb.worker_id} ({url}) 恢复上线")
                else:
                    was_online = status.online
                    status.online = False
                    if was_online:
                        reason = "连接异常" if err else "无响应"
                        logger.warning(f"Worker {url} 离线 ({reason})")

            # 检查心跳超时
            for url, status in self._statuses.items():
                if status.online and status.last_heartbeat:
                    elapsed = (now - status.last_heartbeat).total_seconds()
                    if elapsed > timeout:
                        status.online = False
                        logger.warning(f"Worker {status.worker_id} ({url}) 心跳超时 ({elapsed:.0f}s)")

    # =========================================================================
    # 查询接口
    # =========================================================================

    def get_all_statuses(self) -> list[WorkerStatus]:
        """返回所有 Worker 状态 (按配置顺序)"""
        return [self._statuses[url] for url in self._workers if url in self._statuses]

    def get_online_workers(self) -> list[tuple[WorkerClient, WorkerStatus, int]]:
        """返回在线的 Worker: (client, status, weight)"""
        result = []
        for url, client in self._workers.items():
            status = self._statuses.get(url)
            if status and status.online:
                result.append((client, status, self._weights.get(url, 1)))
        return result

    def get_client_by_url(self, url: str) -> Optional[WorkerClient]:
        """按 URL 获取 WorkerClient"""
        return self._workers.get(url.rstrip("/"))

    def is_any_worker_online(self) -> bool:
        """是否有任何在线 Worker"""
        return any(s.online for s in self._statuses.values())

    def record_performance(self, worker_url: str, media_duration_min: float, wall_time_sec: float):
        """记录一次任务的处理性能

        Args:
            worker_url: Worker URL
            media_duration_min: 媒体时长 (分钟)
            wall_time_sec: 实际耗时 (秒)
        """
        url = worker_url.rstrip("/")
        if url not in self._performance:
            self._performance[url] = deque(maxlen=self._PERF_HISTORY_SIZE)
        if wall_time_sec > 0 and media_duration_min > 0:
            rate = media_duration_min / (wall_time_sec / 60)  # 媒体分钟/实际分钟
            self._performance[url].append(rate)
            logger.debug(f"Worker {url} 性能记录: rate={rate:.2f} (媒体{media_duration_min:.1f}min / 耗时{wall_time_sec:.0f}s)")

    def get_adaptive_weight(self, worker_url: str) -> int:
        """根据历史性能计算自适应权重

        逻辑:
        - 取最近 N 次任务的平均处理速率
        - 与全局平均速率比较，计算 factor
        - 返回 config_weight * factor (clamped to 1-10)
        """
        url = worker_url.rstrip("/")
        config_weight = self._weights.get(url, 1)

        perf = self._performance.get(url)
        if not perf or len(perf) < 2:
            return config_weight  # 数据不足，使用配置权重

        # 计算全局平均速率
        all_rates = []
        for rates in self._performance.values():
            all_rates.extend(rates)
        if not all_rates:
            return config_weight

        global_avg = sum(all_rates) / len(all_rates)
        worker_avg = sum(perf) / len(perf)

        if global_avg <= 0:
            return config_weight

        # factor: worker_avg / global_avg, clamped to [0.5, 2.0]
        factor = max(0.5, min(2.0, worker_avg / global_avg))
        adaptive = max(1, min(10, round(config_weight * factor)))
        return adaptive

    def get_performance_stats(self) -> dict:
        """获取所有 Worker 的性能统计 (供 API 展示)"""
        stats = {}
        for url, rates in self._performance.items():
            if rates:
                stats[url] = {
                    "samples": len(rates),
                    "avg_rate": round(sum(rates) / len(rates), 2),
                    "config_weight": self._weights.get(url, 1),
                    "adaptive_weight": self.get_adaptive_weight(url),
                }
        return stats

    def reload_config(self, config: CoordinatorConfig):
        """热重载: 重新初始化，保留 URL 匹配的现有客户端"""
        old_urls = set(self._workers.keys())
        self._config = config
        self._init_from_config()
        new_urls = set(self._workers.keys())

        added = new_urls - old_urls
        removed = old_urls - new_urls
        if added:
            logger.info(f"Worker 新增: {added}")
        if removed:
            logger.info(f"Worker 移除: {removed}")
