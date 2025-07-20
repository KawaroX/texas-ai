import os
import asyncio
import httpx
import logging

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

logger = logging.getLogger(__name__)


async def call_openrouter(
    messages, model="cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    try:
        logger.info(f"🔄 正在使用模型: {model}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_BASE_URL, headers=headers, json=payload
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
        else:
            logger.error(f"❌ OpenRouter调用失败 (状态码 {e.response.status_code}): {e}")
        return ""
    except Exception as e:
        logger.error(f"❌ OpenRouter调用失败: {e}")
        return ""


async def stream_ai_chat(messages: list) -> str:
    """
    流式调用 AI 生成对话回复。
    """
    # 假设 call_openrouter 已经支持流式输出，或者这里进行模拟
    # 目前 call_openrouter 返回的是完整回复，所以这里需要模拟流式
    full_reply = await call_openrouter(messages)
    
    logger.info(f"🤖️ OpenRouter回复: {full_reply}")

    if not full_reply.strip():
        yield "[自动回复]正在开车，等会回复"
        return

    # 模拟流式输出，按字符或小段返回
    for char in full_reply:
        yield char
        await asyncio.sleep(0.01)  # 模拟延迟


async def call_ai_summary(prompt: str) -> str:
    """
    调用 AI 生成摘要，默认使用 llama-4-maverick 模型。
    """
    messages = [{"role": "user", "content": prompt}]
    return await call_openrouter(messages, model="meta-llama/llama-4-maverick")
