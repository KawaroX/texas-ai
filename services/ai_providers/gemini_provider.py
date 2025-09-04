"""
Gemini AI服务提供商

支持Google Gemini 2.5 Pro等模型调用。
"""

import os
import json
import httpx
import logging
from typing import AsyncGenerator, Dict, Any, Optional

from .base import AIProviderBase
from .utils import summarize_payload_for_log, retry_with_backoff
from ..ai_config.gemini_config import GeminiConfigManager

logger = logging.getLogger(__name__)

# 配置常量
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = "https://gemini-v.kawaro.space/v1beta/models"


class GeminiProvider(AIProviderBase):
    """Gemini AI服务提供商"""
    
    def __init__(self):
        self.config_manager = GeminiConfigManager()
    
    def get_provider_name(self) -> str:
        return "Gemini"
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置"""
        required_keys = ["model"]
        return all(key in config for key in required_keys)
    
    def _build_headers(self) -> Dict[str, str]:
        """构建请求头"""
        headers = {"Content-Type": "application/json"}
        
        if GEMINI_API_KEY2:
            logger.debug("使用 GEMINI_API_KEY2")
            headers["x-goog-api-key"] = f"{GEMINI_API_KEY},{GEMINI_API_KEY2}"
        else:
            headers["x-goog-api-key"] = GEMINI_API_KEY
        
        return headers
    
    def _convert_messages_to_gemini(self, messages: list) -> tuple:
        """将OpenAI格式的messages转换为Gemini格式"""
        system_instruction = {}
        gemini_contents = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "system":
                system_instruction["parts"] = [{"text": content}]
            elif role == "user":
                gemini_contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                gemini_contents.append({"role": "model", "parts": [{"text": content}]})
        
        return system_instruction, gemini_contents
    
    async def stream_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话"""
        cfg = await self.config_manager.load_config()
        model = model or cfg["model"]
        
        logger.debug(f"🔄 正在使用模型进行 Gemini 流式对话: {model}")
        
        headers = self._build_headers()
        system_instruction, gemini_contents = self._convert_messages_to_gemini(messages)
        
        logger.debug(f"转换后的 Gemini contents: {gemini_contents}")
        system_prompt = system_instruction.get("parts", [{"text": ""}])[0].get("text", "")[:100]
        logger.debug(f"system prompt: {system_prompt}...")
        
        payload = {
            "system_instruction": system_instruction,
            "contents": gemini_contents,
            "generationConfig": {
                "stopSequences": cfg["stop_sequences"],
                "responseMimeType": cfg["response_mime_type"],
                "thinkingConfig": {
                    "thinkingBudget": cfg["thinking_budget"],
                    "includeThoughts": cfg["include_thoughts"],
                },
            },
        }
        
        # Compact log: show per-field previews (<=20 chars) and approx token counts
        _payload_summary = summarize_payload_for_log(payload, preview_len=20)
        logger.debug(
            f"\n发送给 Gemini API 的 payload(摘要): {json.dumps(_payload_summary, indent=2, ensure_ascii=False)}\n"
        )
        
        # 调整策略：仅尝试一次 Gemini 流式
        max_retries = 0
        
        for retry_count in range(max_retries + 1):
            yielded_any = False
            try:
                full_url = f"{GEMINI_API_URL}/{model}:streamGenerateContent?alt=sse"
                if retry_count > 0:
                    logger.warning(f"🔄 第 {retry_count} 次重试请求: {full_url}")
                else:
                    logger.debug(f"🚀 开始向 Gemini API 发送请求: {full_url}")
                
                # 超时配置
                timeout = httpx.Timeout(
                    connect=cfg["connect_timeout"],
                    read=cfg["read_timeout"],
                    write=cfg["write_timeout"],
                    pool=cfg["pool_timeout"],
                )
                
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", full_url, headers=headers, json=payload
                    ) as response:
                        logger.debug(f"🌐 Gemini API 响应状态码: {response.status_code}")
                        response.raise_for_status()
                        
                        async for raw_line in response.aiter_lines():
                            line = (raw_line or "").strip()
                            if not line:
                                continue  # 跳过空行
                            if line.startswith(":"):
                                continue  # 跳过 SSE 注释
                            if line.startswith("event:"):
                                logger.debug(f"跳过事件行: {line}")
                                continue
                            if not line.startswith("data:"):
                                logger.debug(f"跳过未知行: {line}")
                                continue
                            
                            data_part = line[5:].strip()
                            if data_part == "[DONE]":
                                logger.debug("接收到流结束标记 [DONE]")
                                break
                            
                            try:
                                data = json.loads(data_part)
                                if "candidates" in data and data["candidates"]:
                                    candidate = data["candidates"][0]
                                    if "content" in candidate and "parts" in candidate["content"]:
                                        parts = candidate["content"]["parts"]
                                        for part in parts:
                                            # 跳过思考内容
                                            if part.get("thought"):
                                                logger.debug(f"Skipping thought content: {part.get('text', '')[:50]}...")
                                                continue
                                            if "text" in part:
                                                text_chunk = part["text"]
                                                if text_chunk:
                                                    yielded_any = True
                                                    yield text_chunk
                                
                            except json.JSONDecodeError as json_err:
                                logger.error(
                                    f"❌ Gemini流式调用失败: JSON解析错误: {json_err}. 原始数据: '{data_part}'"
                                )
                                continue
                        
                        if yielded_any:
                            logger.debug("✅ Gemini流式调用成功完成")
                            return
                        else:
                            logger.warning("⚠️ Gemini流式调用未产生任何输出")
                            yield ""
                            return
                            
            except httpx.HTTPStatusError as http_err:
                status_code = http_err.response.status_code
                try:
                    error_content = await http_err.response.aread()
                    error_text = error_content.decode("utf-8") if error_content else "无响应内容"
                except Exception as read_err:
                    error_text = f"无法读取错误详情: {read_err}"
                
                logger.error(
                    f"❌ Gemini流式调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
                )
                yield f"[自动回复] 在忙，有事请留言 ({status_code})"
                return
                
            except Exception as e:
                logger.error(f"❌ Gemini流式调用失败: 未知错误: {e}")
                yield ""
                return
    
    async def call_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> str:
        """非流式对话"""
        model = model or "gemini-2.5-flash"
        
        headers = self._build_headers()
        _, gemini_contents = self._convert_messages_to_gemini(messages)
        
        payload = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": 0.75,
                "responseMimeType": "text/plain",
                "thinkingConfig": {
                    "thinkingBudget": 32768,
                    "includeThoughts": False,
                },
            },
        }
        
        async def _call_request():
            logger.info(f"🔄 正在使用模型进行 Gemini 非流式调用: {model}")
            async with httpx.AsyncClient(timeout=60) as client:
                full_url = f"{GEMINI_API_URL}/{model}:generateContent"
                response = await client.post(
                    full_url,
                    headers=headers,
                    json=payload,
                )
                logger.debug(f"[Gemini] 状态码: {response.status_code}")
                logger.debug(f"[Gemini] 返回内容: {response.text}")
                response.raise_for_status()
                # Gemini API 的响应结构
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        
        try:
            return await retry_with_backoff(_call_request)
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
                    f"❌ Gemini 调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
                )
                return f"[自动回复] 在忙，有事请留言 ({status_code})"
        except Exception as e:
            logger.error(f"❌ Gemini 调用失败: 未知错误: {e}")
            return ""