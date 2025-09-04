"""
OpenAI AI服务提供商

支持OpenAI协议的多种模型调用，包括GPT、Claude等。
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://yunwu.ai/v1/chat/completions"
OPENAI_API_MODEL = "claude-3-7-sonnet-20250219"  # 默认模型

SUMMARY_API_KEY = os.getenv("SUMMARY_API_KEY")
SUMMARY_API_URL = os.getenv(
    "SUMMARY_API_URL", "https://api.openai.com/v1/chat/completions"
)

STRUCTURED_API_KEY = os.getenv("STRUCTURED_API_KEY")
STRUCTURED_API_URL = os.getenv("STRUCTURED_API_URL", OPENAI_API_URL)
STRUCTURED_API_MODEL = os.getenv("STRUCTURED_API_MODEL", "gemini-2.5-pro")


class OpenAIProvider(ConfigurableProvider):
    """OpenAI兼容API服务提供商"""
    
    def _load_default_config(self) -> Dict[str, Any]:
        return {
            "api_key": OPENAI_API_KEY,
            "api_url": OPENAI_API_URL,
            "default_model": OPENAI_API_MODEL,
            "timeout": 60,
            "max_retries": 3,
            "base_delay": 1.0,
            "summary_api_key": SUMMARY_API_KEY,
            "summary_api_url": SUMMARY_API_URL,
            "structured_api_key": STRUCTURED_API_KEY,
            "structured_api_url": STRUCTURED_API_URL,
            "structured_model": STRUCTURED_API_MODEL,
        }
    
    def get_provider_name(self) -> str:
        return "OpenAI"
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置"""
        required_keys = ["api_key", "api_url"]
        return all(key in config and config[key] for key in required_keys)
    
    def _build_payload_for_model(self, messages: list, model: str, stream: bool = True) -> Dict[str, Any]:
        """根据不同模型构建不同的payload"""
        base_payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        
        if model == "gemini-2.5-pro":
            base_payload.update({
                "frequency_penalty": 0.3,
                "temperature": 0.75,
                "presence_penalty": 0.3,
                "top_p": 0.95,
                "extra_body": {
                    "google": {
                        "thinking_config": {
                            "thinking_budget": 32768,
                            "include_thoughts": False,
                        }
                    }
                },
            })
        elif model == "gpt-5-2025-08-07":
            base_payload.update({
                "reasoning_effort": "high",
                "verbosity": "medium",
                "frequency_penalty": 0.3,
                "temperature": 0.75,
                "presence_penalty": 0.3,
                "max_tokens": 512,
            })
        else:
            base_payload.update({
                "frequency_penalty": 0.3,
                "temperature": 0.75,
                "presence_penalty": 0.3,
                "top_p": 0.95,
                "max_tokens": 512,
            })
        
        return base_payload
    
    async def stream_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话"""
        model = model or self._config["default_model"]
        logger.info(f"[OpenAI] 开始流式对话，模型={model}")
        
        headers = {
            "Authorization": f"Bearer {self._config['api_key']}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload_for_model(messages, model, stream=True)

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
                                    f"❌ OpenAI流式调用失败: JSON解析错误: {json_err}. 原始数据: '{chunk}'"
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
                            "❌ OpenAI流式调用失败: API调用频率限制 (429 Too Many Requests)"
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
                        f"❌ OpenAI流式调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
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
                    logger.error(f"❌ OpenAI流式调用失败: 未知错误: {e}")
                    yield ""
                    return

    async def call_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> str:
        """非流式对话"""
        model = model or "gpt-4o-mini"
        
        # 判断使用哪个API配置
        use_summary = kwargs.get("use_summary", False)
        if use_summary:
            api_key = self._config["summary_api_key"]
            api_url = self._config["summary_api_url"]
        else:
            api_key = self._config["api_key"]
            api_url = self._config["api_url"]
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = self._build_payload_for_model(messages, model, stream=False)

        async def _call_request():
            logger.info(f"[OpenAI] 开始非流式调用，模型={model}")
            async with httpx.AsyncClient(timeout=self._config["timeout"]) as client:
                response = await client.post(
                    api_url, headers=headers, json=payload
                )
                logger.debug(f"[OpenAI] 状态码: {response.status_code}")
                logger.debug(f"[OpenAI] 返回内容: {response.text}")
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
                try:
                    error_content = await http_err.response.aread()
                    error_text = (
                        error_content.decode("utf-8") if error_content else "无响应内容"
                    )
                except Exception as read_err:
                    error_text = f"无法读取错误详情: {read_err}"

                logger.error(
                    f"❌ OpenAI 调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
                )
                return f"[自动回复] 在忙，有事请留言 ({status_code})"
        except Exception as e:
            logger.error(f"❌ OpenAI 调用失败: 未知错误: {e}")
            return ""
    
    async def call_structured_generation(self, messages: list, max_retries: int = 3) -> dict:
        """结构化生成调用"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._config['structured_api_key']}",
        }
        payload = self._build_payload_for_model(messages, self._config["structured_model"], stream=False)

        async def _call_request():
            logger.info(f"[OpenAI] 开始结构化生成，模型={self._config['structured_model']}")
            async with httpx.AsyncClient(timeout=self._config["timeout"]) as client:
                response = await client.post(
                    self._config["structured_api_url"], headers=headers, json=payload
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                
                # 尝试解析JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("⚠️ 结构化生成返回的不是有效JSON，返回原始内容")
                    return {"raw_content": content}

        try:
            return await retry_with_backoff(_call_request, max_retries, self._config["base_delay"])
        except Exception as e:
            logger.error(f"❌ 结构化生成失败: {e}")
            return {"error": str(e)}