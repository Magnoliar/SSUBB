"""SSUBB Worker - LLM 客户端

使用 OpenAI 兼容 API 调用各大 LLM 提供商 (如 DeepSeek)。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import json_repair
from openai import AsyncOpenAI
import httpx

from .config import LLMConfig

logger = logging.getLogger("ssubb.llm")


class LLMClient:
    """包装 OpenAI AsyncClient，处理带重试和错误恢复的调用"""

    def __init__(self, config: LLMConfig):
        self.config = config
        
        # 兼容处理 base_url 和 api_key
        api_base = config.api_base.rstrip("/")
        api_key = config.api_key or "EMPTY"
        
        # 自定义 Http Client 以支持代理和重试
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            http_client=http_client,
        )
        self.model = config.model

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """发起 LLM 聊天完成请求"""
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format
                
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM API 调用失败: {e}")
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
            # 1. 调用 LLM
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

        logger.error(f"达到最大重试次数 ({max_retries})，但未能获得完全匹配的 JSON。返回最后的结果或空。")
        return last_result

    def _add_feedback(self, messages: List[Dict[str, str]], assistant_content: str, error_msg: str):
        """向上下文中添加错误反馈"""
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": f"Validation failed: {error_msg}\nFix the errors and output ONLY valid JSON format."})
