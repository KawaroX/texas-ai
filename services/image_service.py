import os
import httpx
import logging
import json
import asyncio
import base64
from typing import Optional

# --- 从 ai_service.py 借鉴的配置 ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = os.getenv("GEMINI_API_URL111", "https://yunwu.ai/v1beta/models/")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logger = logging.getLogger(__name__)


async def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0):
    """
    重试机制，支持指数退避 (从 ai_service.py 移植)
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
                logger.warning(f"{e}")
                logger.warning(
                    f"⚠️ 遇到未知错误{type(e)}，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error("❌ 达到最大重试次数，放弃重试")
                raise


async def get_image_description(
    image_data: bytes,
    mime_type: str,
    prompt: str = (
        "请为这张图片提供一份详细而简洁的描述，用于聊天机器人的上下文。"
        "请识别出主要对象、他们的外观、动作以及周围的环境。"
        "注意图片中可能包含的文字、重要物品或整体氛围。请让你的回答条理清晰。"
    ),
) -> str:
    """
    使用 Gemini Pro Vision 模型为图片生成文本描述 (非流式)。

    Args:
        image_data: 图片的二进制数据.
        mime_type: 图片的MIME类型 (例如 "image/jpeg", "image/png").
        prompt: 指导模型生成描述的文本提示.

    Returns:
        str: AI生成的图片描述.
    """
    model = "gemini-2.5-flash-lite"
    logger.info(f"[image_service] 开始使用模型 {model} 生成图片描述")

    headers = {
        "Content-Type": "application/json",
    }

    # 将图片数据进行Base64编码
    encoded_image = base64.b64encode(image_data).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_image,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.5,
            "topK": 32,
            "topP": 1,
            "maxOutputTokens": 4096,
            "stopSequences": [],
            "thinkingConfig": {
                "includeThoughts": True,
                "thinkingBudget": 24576,
            },
        },
        "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
        ],
    }

    async def _call_request():
        logger.info(f"🔄 正在使用模型进行 get_image_description(): {model}")
        async with httpx.AsyncClient(timeout=120) as client:
            full_url = f"{GEMINI_API_URL}{model}:generateContent?key={OPENAI_API_KEY}"
            response = await client.post(
                full_url,
                headers=headers,
                json=payload,
            )
            logger.debug(f"[image_service] 状态码: {response.status_code}")
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"[image_service] 返回内容: {response.text}")
            response.raise_for_status()

            response_json = response.json()

            # 检查是否有候选内容以及parts
            if not response_json.get("candidates"):
                logger.error(
                    f"❌ Gemini Vision API 响应中缺少 'candidates'。响应: {response_json}"
                )
                # 检查是否有 block reason
                prompt_feedback = response_json.get("promptFeedback", {})
                if prompt_feedback.get("blockReason"):
                    reason = prompt_feedback.get("blockReason")
                    safety_ratings = prompt_feedback.get("safetyRatings", [])
                    return f"图片描述生成失败，内容可能不安全。原因: {reason}, 详情: {safety_ratings}"
                return "图片描述生成失败，API未返回有效内容。"

            return response_json["candidates"][0]["content"]["parts"][0]["text"]

    try:
        return await retry_with_backoff(_call_request)
    except httpx.HTTPStatusError as http_err:
        status_code = http_err.response.status_code
        error_text = http_err.response.text
        logger.error(
            f"❌ Gemini Vision 调用失败: HTTP错误: {status_code} - {error_text}"
        )
        return f"[图片处理失败: HTTP {status_code}]"
    except Exception as e:
        logger.error(f"❌ Gemini Vision 调用失败: 未知错误: {e}")
        return "[图片处理失败: 未知错误]"
