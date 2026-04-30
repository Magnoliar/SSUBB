"""SSUBB Worker - LLM 多端点容灾客户端

按优先级尝试多个 LLM 提供商，首个成功即返回。
追踪每个 provider 的健康状态和延迟。
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import json_repair
from openai import AsyncOpenAI
import httpx

from shared.models import LLMProviderConfig, LLMHealthStatus

logger = logging.getLogger("ssubb.llm")


class LLMClient:
    """多 LLM 提供商容灾客户端"""

    def __init__(self, providers: list[LLMProviderConfig]):
        # 按 priority 排序，过滤 enabled
        self._providers = sorted(
            [p for p in providers if p.enabled],
            key=lambda p: p.priority,
        )
        # 每个 provider 创建独立 AsyncOpenAI 实例
        self._clients: Dict[str, AsyncOpenAI] = {}
        for p in self._providers:
            api_base = p.api_base.rstrip("/")
            api_key = p.api_key or "EMPTY"
            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            self._clients[p.label] = AsyncOpenAI(
                api_key=api_key,
                base_url=api_base,
                http_client=http_client,
            )
        # 健康状态追踪
        self._health: Dict[str, LLMHealthStatus] = {}
        for p in self._providers:
            self._health[p.label] = LLMHealthStatus(
                provider_label=p.label,
                healthy=True,
            )

    @property
    def providers(self) -> list[LLMProviderConfig]:
        return list(self._providers)

    @property
    def model(self) -> str:
        """返回最高优先级 provider 的模型名（向后兼容）"""
        return self._providers[0].model if self._providers else ""

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        response_format: Optional[Dict[str, str]] = None,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """按优先级尝试所有 provider，首个成功即返回"""
        for provider in self._providers:
            client = self._clients[provider.label]
            use_model = model or provider.model
            try:
                start = time.monotonic()
                kwargs: Dict[str, Any] = {
                    "model": use_model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if response_format:
                    kwargs["response_format"] = response_format
                response = await client.chat.completions.create(**kwargs)
                latency = (time.monotonic() - start) * 1000
                self._health[provider.label] = LLMHealthStatus(
                    provider_label=provider.label,
                    healthy=True,
                    latency_ms=round(latency, 1),
                    last_check=datetime.now().isoformat(),
                )
                return response.choices[0].message.content
            except Exception as e:
                self._health[provider.label] = LLMHealthStatus(
                    provider_label=provider.label,
                    healthy=False,
                    last_error=str(e),
                    last_check=datetime.now().isoformat(),
                )
                logger.warning(f"[{provider.label}] LLM 调用失败，尝试下一个: {e}")
                continue
        logger.error("所有 LLM 提供商均不可用")
        return None

    async def call_with_json_validation(
        self,
        messages: List[Dict[str, str]],
        expected_keys: set,
        max_retries: int = 3,
    ) -> Optional[Dict[str, str]]:
        """带有 JSON 解析和键值验证的 LLM Agent Loop"""
        current_messages = list(messages)
        last_result = None

        for attempt in range(max_retries):
            # 1. 调用 LLM（内部已有容灾）
            content = await self.chat_completion(current_messages, temperature=0.2)
            if not content:
                logger.warning(f"第 {attempt + 1} 次调用的返回为空")
                continue

            # 2. 尝试修复并解析 JSON
            try:
                parsed = json_repair.loads(content)
                if not isinstance(parsed, dict):
                    error_msg = f"期望 JSON 字典，实际返回类型: {type(parsed).__name__}"
                    logger.warning(error_msg)
                    self._add_feedback(current_messages, content, error_msg)
                    continue
                result_dict = parsed
                last_result = result_dict
            except Exception as e:
                error_msg = f"JSON 解析失败: {e}"
                logger.warning(error_msg)
                self._add_feedback(current_messages, content, error_msg)
                continue

            # 3. 验证键值匹配
            actual_keys = set(str(k) for k in result_dict.keys())
            expected_keys_str = set(str(k) for k in expected_keys)

            if expected_keys_str != actual_keys:
                missing = expected_keys_str - actual_keys
                extra = actual_keys - expected_keys_str
                error_parts = []
                if missing:
                    error_parts.append(f"Missing keys: {sorted(missing)}")
                if extra:
                    error_parts.append(f"Extra keys: {sorted(extra)}")
                error_msg = (
                    "; ".join(error_parts) +
                    f"\nPlease return the complete valid JSON dictionary with EXACTLY ALL {len(expected_keys_str)} keys."
                )
                logger.warning(f"第 {attempt + 1} 次验证失败: {error_msg}")
                self._add_feedback(current_messages, content, error_msg)
                continue

            # 验证通过
            return {str(k): str(v) for k, v in result_dict.items()}

        logger.error(f"达到最大重试次数 ({max_retries})，但未能获得完全匹配的 JSON。")
        return last_result

    async def check_health(self) -> list[LLMHealthStatus]:
        """检测所有 provider 的连通性（轻量请求）"""
        results = []
        for provider in self._providers:
            client = self._clients[provider.label]
            try:
                start = time.monotonic()
                await client.chat.completions.create(
                    model=provider.model,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                )
                latency = (time.monotonic() - start) * 1000
                status = LLMHealthStatus(
                    provider_label=provider.label,
                    healthy=True,
                    latency_ms=round(latency, 1),
                    last_check=datetime.now().isoformat(),
                )
            except Exception as e:
                status = LLMHealthStatus(
                    provider_label=provider.label,
                    healthy=False,
                    last_error=str(e),
                    last_check=datetime.now().isoformat(),
                )
            self._health[provider.label] = status
            results.append(status)
        return results

    def get_health_snapshot(self) -> list[LLMHealthStatus]:
        """返回当前缓存的健康状态（不发起网络请求）"""
        return [self._health[p.label] for p in self._providers]

    async def close(self):
        """关闭所有 httpx 客户端，释放连接资源"""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass

    def _add_feedback(self, messages: List[Dict[str, str]], assistant_content: str, error_msg: str):
        """向上下文中添加错误反馈"""
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": f"Validation failed: {error_msg}\nFix the errors and output ONLY valid JSON format."})

    @classmethod
    def from_single_config(cls, llm_config) -> "LLMClient":
        """向后兼容：从旧单配置创建"""
        return cls([LLMProviderConfig(
            api_base=llm_config.api_base,
            api_key=llm_config.api_key,
            model=llm_config.model,
            priority=1,
            enabled=True,
            label="默认",
        )])
