"""SSUBB Coordinator - 通用通知分发器

支持多渠道 Webhook 通知 (Bark / PushPlus / Gotify / 通用)。
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from .config import NotificationChannel

logger = logging.getLogger("ssubb.notifier")


# 各渠道默认 Body 模板
_CHANNEL_TEMPLATES = {
    "bark": {
        "title": "SSUBB 通知",
        "body": "{message}",
        "group": "SSUBB",
    },
    "pushplus": {
        "template": "txt",
        "title": "SSUBB 通知",
        "content": "{message}",
    },
    "gotify": {
        "title": "SSUBB",
        "message": "{message}",
        "priority": 5,
    },
}

# 事件中文名映射
_EVENT_LABELS = {
    "task_completed": "任务完成",
    "task_failed": "任务失败",
    "worker_offline": "Worker 离线",
    "scan_result": "扫描结果",
}


class Notifier:
    """通用通知分发器"""

    def __init__(self, channels: list[NotificationChannel]):
        self._channels = [c for c in channels if c.enabled and c.url]
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=10)
        return self._http

    async def notify(self, event: str, data: dict):
        """向订阅了该事件的所有渠道发送通知"""
        if not self._channels:
            return
        for channel in self._channels:
            if event in channel.events:
                try:
                    await self._send(channel, event, data)
                except Exception as e:
                    logger.warning(f"通知发送失败 [{channel.name}]: {e}")

    async def _send(self, channel: NotificationChannel, event: str, data: dict):
        """发送到单个渠道"""
        message = self._format_message(event, data)
        body = self._build_body(channel, event, data, message)
        headers = {"Content-Type": "application/json", **channel.headers}

        client = await self._get_client()
        resp = await client.post(channel.url, json=body, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                f"通知 [{channel.name}] 返回 {resp.status_code}: {resp.text[:200]}"
            )
        else:
            logger.info(f"通知 [{channel.name}] 已发送: {_EVENT_LABELS.get(event, event)}")

    def _format_message(self, event: str, data: dict) -> str:
        """格式化通知消息文本"""
        label = _EVENT_LABELS.get(event, event)
        if event == "task_completed":
            title = data.get("media_title", "未知")
            lang = data.get("target_lang", "")
            dur = data.get("duration", 0)
            return f"✅ {label}: {title} ({lang}) — 耗时 {dur:.0f}s"
        elif event == "task_failed":
            title = data.get("media_title", "未知")
            error = data.get("error", "未知错误")
            return f"❌ {label}: {title} — {error}"
        elif event == "worker_offline":
            wid = data.get("worker_id", "未知")
            return f"⚠️ {label}: {wid}"
        elif event == "scan_result":
            count = data.get("new_tasks", 0)
            return f"🔍 {label}: 新增 {count} 个任务"
        return f"[{label}] {data}"

    def _build_body(
        self,
        channel: NotificationChannel,
        event: str,
        data: dict,
        message: str,
    ) -> dict:
        """构建请求 Body"""
        # 用户自定义模板
        if channel.template:
            try:
                text = channel.template.format(message=message, event=event, **data)
                return {"text": text}
            except Exception:
                return {"text": message}

        # 按渠道类型构建
        tpl = _CHANNEL_TEMPLATES.get(channel.channel_type)
        if tpl:
            body = {}
            for k, v in tpl.items():
                if isinstance(v, str):
                    body[k] = v.format(message=message, event=event)
                else:
                    body[k] = v
            return body

        # generic: 通用 JSON
        return {
            "event": event,
            "event_label": _EVENT_LABELS.get(event, event),
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()
