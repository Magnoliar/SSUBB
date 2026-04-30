"""SSUBB 局域网自动发现服务 (Coordinator 端)

通过 UDP 广播实现 Coordinator 与 Worker 的互相发现。
Worker 启动后广播自身信息，Coordinator 收到后自动注册。
"""

import asyncio
import json
import logging
from typing import Callable, Optional

from shared.constants import VERSION, DISCOVERY_PORT

logger = logging.getLogger("ssubb.discovery")


class UDPDiscoveryService:
    """Coordinator 端 UDP 发现服务"""

    BROADCAST_INTERVAL = 30  # 秒

    def __init__(
        self,
        coordinator_url: str,
        port: int = DISCOVERY_PORT,
        auto_register: bool = True,
        on_worker_discovered: Optional[Callable] = None,
    ):
        self._coordinator_url = coordinator_url
        self._port = port
        self._auto_register = auto_register
        self._on_discovered = on_worker_discovered
        self._known_peers: dict[str, float] = {}  # url -> last_seen timestamp
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional[asyncio.DatagramProtocol] = None
        self._broadcast_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 UDP 监听和广播"""
        try:
            loop = asyncio.get_event_loop()
            # 监听
            self._transport, self._protocol = await loop.create_datagram_endpoint(
                lambda: _DiscoveryProtocol(self._handle_message),
                local_addr=("0.0.0.0", self._port),
                allow_broadcast=True,
            )
            # 广播
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            logger.info(f"发现服务已启动 (端口 {self._port}, 自动注册={self._auto_register})")
        except OSError as e:
            logger.warning(f"发现服务启动失败 (端口 {self._port} 可能被占用): {e}")
        except Exception as e:
            logger.error(f"发现服务启动异常: {e}")

    async def stop(self):
        """停止服务"""
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        if self._transport:
            self._transport.close()
        logger.info("发现服务已停止")

    def get_discovered_peers(self) -> dict:
        """返回已发现的节点列表"""
        import time
        now = time.time()
        return {
            url: {
                "last_seen_ago": int(now - ts),
                "stale": now - ts > 120,
            }
            for url, ts in self._known_peers.items()
        }

    async def register_worker(self, url: str) -> bool:
        """手动注册一个 Worker"""
        if self._on_discovered:
            return await self._on_discovered(url)
        return False

    def _handle_message(self, data: dict, addr: tuple):
        """处理收到的 UDP 消息"""
        import time
        msg_type = data.get("type")

        if msg_type == "worker_announce":
            worker_id = data.get("worker_id", "unknown")
            worker_port = data.get("port", 8788)
            sender_ip = addr[0]
            url = f"http://{sender_ip}:{worker_port}"

            if url not in self._known_peers:
                logger.info(f"发现新 Worker: {worker_id} @ {url}")
                self._known_peers[url] = time.time()

                if self._auto_register and self._on_discovered:
                    asyncio.create_task(self._safe_register(url, worker_id))
            else:
                self._known_peers[url] = time.time()

    async def _safe_register(self, url: str, worker_id: str):
        """安全地注册 Worker（捕获异常）"""
        try:
            if self._on_discovered:
                await self._on_discovered(url)
        except Exception as e:
            logger.error(f"自动注册 Worker {worker_id} 失败: {e}")

    async def _broadcast_loop(self):
        """定期广播 Coordinator 信息"""
        while True:
            try:
                msg = json.dumps({
                    "type": "coordinator_announce",
                    "url": self._coordinator_url,
                    "version": VERSION,
                }).encode()

                if self._transport:
                    self._transport.sendto(msg, ("255.255.255.255", self._port))
            except Exception as e:
                logger.debug(f"广播发送失败: {e}")

            await asyncio.sleep(self.BROADCAST_INTERVAL)


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """UDP 协议处理器"""

    def __init__(self, on_message):
        self._on_message = on_message

    def connection_made(self, transport):
        pass

    def datagram_received(self, data: bytes, addr: tuple):
        try:
            msg = json.loads(data.decode())
            self._on_message(msg, addr)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # 忽略无效数据包

    def error_received(self, exc):
        logger.debug(f"UDP 错误: {exc}")
