"""
OpenRouter AI服务提供商

支持OpenRouter平台的多种开源模型调用。
"""

import os
import json
import httpx
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, Optional

from .base import ConfigurableProvider
from .utils import retry_with_backoff

logger = logging.getLogger(__name__)

# 配置常量
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "z-ai/glm-4.5-air:free"


class OpenRouterProvider(ConfigurableProvider):
    """OpenRouter AI服务提供商"""
    
    def _load_default_config(self) -> Dict[str, Any]:
        return {
            "api_key": OPENROUTER_API_KEY,
            "api_url": OPENROUTER_API_URL,
            "default_model": DEFAULT_MODEL,
            "timeout": 60,
            "max_retries": 3,
            "base_delay": 1.0,
        }
    
    def get_provider_name(self) -> str:
        return "OpenRouter"
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置"""
        required_keys = ["api_key", "api_url"]
        return all(key in config and config[key] for key in required_keys)
    
    async def stream_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话"""
        model = model or self._config["default_model"]
        logger.info(f"[OpenRouter] 开始流式对话，模型={model}")
        
        headers = {
            "Authorization": f"Bearer {self._config['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, "stream": True}

        async def _stream_request():
            async with httpx.AsyncClient(timeout=self._config["timeout"]) as client:
                async with client.stream(
                    "POST", self._config["api_url"], headers=headers, json=payload
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_lines():
                        chunk = chunk.strip()
                        if chunk == "":
                            continue  # 跳过空行
                        if chunk.startswith(":"):
                            # 跳过SSE注释行
                            continue
                        if chunk.startswith("data:"):
                            data_part = chunk[5:].strip()
                            if data_part == "[DONE]":
                                # 跳过流结束标记
                                continue
                            try:
                                data = json.loads(data_part)
                                if "choices" in data and data["choices"]:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        yield delta["content"]
                            except json.JSONDecodeError as json_err:
                                logger.error(
                                    f"❌ OpenRouter流式调用失败: JSON解析错误: {json_err}. 原始数据: '{chunk}'"
                                )
                                continue
                        elif chunk.startswith("event:"):
                            # 跳过如 event: end 之类的事件行
                            continue
                        else:
                            # 跳过未知行，不再记录warning
                            continue

        # 流式请求的重试逻辑
        max_retries = self._config["max_retries"]
        base_delay = self._config["base_delay"]

        for attempt in range(max_retries):
            try:
                async for chunk in _stream_request():
                    yield chunk
                return  # 成功完成，退出重试循环
            except httpx.HTTPStatusError as http_err:
                status_code = http_err.response.status_code
                if status_code == 429:
                    logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            f"⚠️ 遇到429错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(
                            "❌ OpenRouter流式调用失败: API调用频率限制 (429 Too Many Requests)"
                        )
                        yield "⚠️ API调用频率限制，请稍后再试。"
                        return
                else:
                    try:
                        error_content = await http_err.response.aread()
                        error_text = (
                            error_content.decode("utf-8") if error_content else "无响应内容"
                        )
                    except Exception as read_err:
                        error_text = f"无法读取错误详情: {read_err}"

                    logger.error(
                        f"❌ OpenRouter流式调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
                    )
                    yield f"[自动回复] 在忙，有事请留言 ({status_code})"
                    return
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 遇到未知错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"❌ OpenRouter流式调用失败: 未知错误: {e}")
                    yield ""
                    return

    async def call_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> str:
        """非流式对话"""
        model = model or self._config["default_model"]
        
        headers = {
            "Authorization": f"Bearer {self._config['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
        }

        async def _call_request():
            logger.info(f"[OpenRouter] 开始非流式调用，模型={model}")
            async with httpx.AsyncClient(timeout=self._config["timeout"]) as client:
                response = await client.post(
                    self._config["api_url"], headers=headers, json=payload
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]

        try:
            return await retry_with_backoff(_call_request, self._config["max_retries"], self._config["base_delay"])
        except httpx.HTTPStatusError as http_err:
            status_code = http_err.response.status_code
            if status_code == 429:
                logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
                return "⚠️ API调用频率限制，请稍后再试。"
            else:
                logger.error(
                    f"❌ OpenRouter调用失败: HTTP错误: {status_code} - {http_err.response.text}"
                )
                return f"[自动回复] 在忙，有事请留言 ({status_code})"
        except Exception as e:
            logger.error(f"❌ OpenRouter调用失败: 未知错误: {e}")
            return ""