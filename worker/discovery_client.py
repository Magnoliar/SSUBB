"""SSUBB 局域网自动发现客户端 (Worker 端)

Worker 启动后通过 UDP 广播自身信息，同时监听 Coordinator 的广播。
如果未配置 coordinator_url，收到 Coordinator 广播后自动写入配置。
"""

import asyncio
import json
import logging
from typing import Optional

from shared.constants import VERSION, DISCOVERY_PORT

logger = logging.getLogger("ssubb.discovery_client")


class UDPDiscoveryClient:
    """Worker 端 UDP 发现客户端"""

    BROADCAST_INTERVAL = 30  # 秒

    def __init__(
        self,
        worker_id: str,
        worker_port: int = 8788,
        port: int = DISCOVERY_PORT,
        on_coordinator_discovered: Optional[callable] = None,
    ):
        self._worker_id = worker_id
        self._worker_port = worker_port
        self._port = port
        self._on_discovered = on_coordinator_discovered
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._broadcast_task: Optional[asyncio.Task] = None
        self._coordinator_url: Optional[str] = None

    @property
    def coordinator_url(self) -> Optional[str]:
        return self._coordinator_url

    async def start(self):
        """启动 UDP 广播和监听"""
        try:
            loop = asyncio.get_event_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _ClientProtocol(self._handle_message),
                local_addr=("0.0.0.0", self._port),
                allow_broadcast=True,
            )
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            logger.info(f"发现客户端已启动 (端口 {self._port})")
        except OSError as e:
            logger.warning(f"发现客户端启动失败 (端口 {self._port} 可能被占用): {e}")
        except Exception as e:
            logger.error(f"发现客户端启动异常: {e}")

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
        logger.info("发现客户端已停止")

    def _handle_message(self, data: dict, addr: tuple):
        """处理收到的 UDP 消息"""
        msg_type = data.get("type")

        if msg_type == "coordinator_announce" and not self._coordinator_url:
            url = data.get("url")
            version = data.get("version", "unknown")
            if url:
                self._coordinator_url = url
                logger.info(f"发现 Coordinator: {url} (v{version})")
                if self._on_discovered:
                    asyncio.create_task(self._safe_notify(url))

    async def _safe_notify(self, url: str):
        """安全地通知回调"""
        try:
            if self._on_discovered:
                await self._on_discovered(url)
        except Exception as e:
            logger.error(f"通知回调失败: {e}")

    async def _broadcast_loop(self):
        """定期广播 Worker 信息"""
        while True:
            try:
                msg = json.dumps({
                    "type": "worker_announce",
                    "worker_id": self._worker_id,
                    "port": self._worker_port,
                    "version": VERSION,
                }).encode()

                if self._transport:
                    self._transport.sendto(msg, ("255.255.255.255", self._port))
            except Exception as e:
                logger.debug(f"广播发送失败: {e}")

            await asyncio.sleep(self.BROADCAST_INTERVAL)


class _ClientProtocol(asyncio.DatagramProtocol):
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
            pass

    def error_received(self, exc):
        logger.debug(f"UDP 错误: {exc}")
