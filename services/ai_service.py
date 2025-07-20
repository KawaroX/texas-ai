import os
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


async def call_ai_chat(
    system_prompt: str, chat_history: list, latest_input: str
) -> list[str]:
    """
    调用 AI 生成对话回复，支持多段（用===分割）。
    默认使用对话模型。
    """
    messages = (
        [{"role": "system", "content": system_prompt}]
        + chat_history
        + [{"role": "user", "content": latest_input}]
    )
    full_reply = await call_openrouter(messages)

    if not full_reply.strip():
        return ["[系统未返回内容]"]

    return [seg.strip() for seg in full_reply.split("===") if seg.strip()]


async def call_ai_summary(prompt: str) -> str:
    """
    调用 AI 生成摘要，默认使用 llama-4-maverick 模型。
    """
    messages = [{"role": "user", "content": prompt}]
    return await call_openrouter(messages, model="meta-llama/llama-4-maverick")
