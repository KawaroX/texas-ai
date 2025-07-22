import os
import httpx
import logging
import json
import asyncio
from typing import AsyncGenerator, Optional

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

YUNWU_AI_KEY = os.getenv("YUNWU_AI_KEY")
YUNWU_AI_BASE_URL = "https://yunwu.ai/v1/chat/completions"
YUNWU_AI_MODEL = "claude-3-7-sonnet-20250219"

logger = logging.getLogger(__name__)


async def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0):
    """
    重试机制，支持指数退避
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 遇到429错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error("❌ 达到最大重试次数，放弃重试")
                    raise
            else:
                # 其他HTTP错误直接抛出，不重试
                raise
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"⚠️ 遇到未知错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error("❌ 达到最大重试次数，放弃重试")
                raise


async def stream_openrouter(
    messages, model="deepseek/deepseek-chat-v3-0324:free"
) -> AsyncGenerator[str, None]:
    """
    流式调用OpenRouter API，返回异步生成器。
    """
    logger.info(f"🔄 正在使用模型进行 stream_openrouter(): {model}")
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "stream": True}

    async def _stream_request():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", OPENROUTER_BASE_URL, headers=headers, json=payload
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

    # 对于流式请求，我们直接处理重试逻辑，不使用 retry_with_backoff
    max_retries = 3
    base_delay = 1.0

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
                        error_content.decode("utf-8") if error_content else "未知错误"
                    )
                except Exception:
                    error_text = "无法读取错误详情"

                logger.error(
                    f"❌ OpenRouter流式调用失败: HTTP错误: {status_code} - {error_text}"
                )
                yield f"❌ API调用失败 (错误代码: {status_code})"
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


async def stream_reply_ai(messages, model=YUNWU_AI_MODEL) -> AsyncGenerator[str, None]:
    """
    流式调用 Reply AI API (支持 OpenAI 协议)，返回异步生成器。
    """
    logger.info(f"🔄 正在使用模型进行 stream_reply_ai(): {model}")
    headers = {
        "Authorization": f"Bearer {YUNWU_AI_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "stream": True}

    async def _stream_request():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", YUNWU_AI_BASE_URL, headers=headers, json=payload
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
                                f"❌ Reply AI流式调用失败: JSON解析错误: {json_err}. 原始数据: '{chunk}'"
                            )
                            continue
                    elif chunk.startswith("event:"):
                        # 跳过如 event: end 之类的事件行
                        continue
                    else:
                        # 跳过未知行，不再记录warning
                        continue

    # 对于流式请求，我们直接处理重试逻辑，不使用 retry_with_backoff
    max_retries = 3
    base_delay = 1.0

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
                        "❌ Reply AI流式调用失败: API调用频率限制 (429 Too Many Requests)"
                    )
                    yield "⚠️ API调用频率限制，请稍后再试。"
                    return
            else:
                try:
                    error_content = await http_err.response.aread()
                    error_text = (
                        error_content.decode("utf-8") if error_content else "未知错误"
                    )
                except Exception:
                    error_text = "无法读取错误详情"

                logger.error(
                    f"❌ Reply AI流式调用失败: HTTP错误: {status_code} - {error_text}"
                )
                yield f"❌ API调用失败 (错误代码: {status_code})"
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
                logger.error(f"❌ Reply AI流式调用失败: 未知错误: {e}")
                yield ""
                return


async def stream_ai_chat(messages: list, model: Optional[str] = None):
    """
    流式生成AI回复，按分隔符分段输出。
    分隔符优先为 '==='，其次为换行符。
    """
    # 如���没有指定模型，或者指定的是 DeepSeek V3 模型，则使用 Reply AI 渠道
    if model is None or model == "deepseek/deepseek-chat-v3-0324:free":
        logger.info(f"🔄 正在使用 Reply AI 渠道进行 stream_ai_chat(): {YUNWU_AI_MODEL}")
        stream_func = stream_reply_ai
        actual_model = YUNWU_AI_MODEL
    else:
        # 否则，使用 OpenRouter 渠道
        logger.info(f"🔄 正在使用 OpenRouter 渠道进行 stream_ai_chat(): {model}")
        stream_func = stream_openrouter
        actual_model = model

    buffer = ""
    async for chunk in stream_func(messages, model=actual_model):
        buffer += chunk

        # 优先按 '===' 分段
        while True:
            sep_index = buffer.find("===")
            if sep_index != -1:
                segment = buffer[:sep_index].strip()
                if segment:
                    yield segment
                buffer = buffer[sep_index + 3 :]
                continue
            # 其次按换行符分段（可选，通常流式模型直接按===分）
            newline_index = buffer.find("\n")
            if newline_index != -1:
                segment = buffer[:newline_index].strip()
                if segment:
                    yield segment
                buffer = buffer[newline_index + 1 :]
                continue
            break

    # 最终剩余内容
    if buffer.strip():
        yield buffer.strip()


async def call_openrouter(
    messages, model="nousresearch/deephermes-3-llama-3-8b-preview:free"
) -> str:
    """
    非流式调用（用于摘要等场景）
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
    }

    async def _call_request():
        logger.info(f"🔄 正在使用模型进行 call_openrouter(): {model}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_BASE_URL, headers=headers, json=payload
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    try:
        return await retry_with_backoff(_call_request)
    except httpx.HTTPStatusError as http_err:
        status_code = http_err.response.status_code
        if status_code == 429:
            logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
            return "⚠️ API调用频率限制，请稍后再试。"
        else:
            logger.error(
                f"❌ OpenRouter调用失败: HTTP错误: {status_code} - {http_err.response.text}"
            )
            return f"❌ API调用失败 (错误代码: {status_code})"
    except Exception as e:
        logger.error(f"❌ OpenRouter调用失败: 未知错误: {e}")
        return ""


async def call_ai_summary(prompt: str) -> str:
    """
    调用 AI 生成摘要，可用于 context_merger.py。
    """
    messages = [{"role": "user", "content": prompt}]
    model = "nousresearch/deephermes-3-llama-3-8b-preview:free"
    logger.info(f"🔄 正在使用模型进行 call_ai_summary(): {model}")
    # 你可以根据需求自由切换模型名
    return await call_openrouter(messages, model)
