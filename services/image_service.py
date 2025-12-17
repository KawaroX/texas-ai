"""
通用图片处理工具服务 (General Image Processing Utility Service)

主要功能:
- 基于Gemini Vision API的图片内容描述生成
- 支持重试机制和错误处理
- 图片到文本的AI识别和描述
- 图片压缩和优化处理 (迁移自 image_content_analyzer.py)
- 图片描述缓存管理 (迁移自 image_content_analyzer.py)

服务关系:
- 独立的图片分析工具,可被其他服务调用
- 整合了原 image_content_analyzer.py 的工具函数
- 被 mattermost_client.py 调用提供图片占位符功能

核心方法:
- get_image_description(): 生成图片的自然语言描述
- retry_with_backoff(): 带指数退避的重试机制
- get_image_description_by_path(): 从Redis获取缓存的图片描述 (迁移)
- compress_image_if_needed(): 智能图片压缩处理 (迁移)
- get_image_path_hash(): SHA256路径哈希生成 (迁移)

技术特点:
- 使用Gemini 2.5 Flash Lite模型
- Base64图片编码传输
- 支持多种图片格式(JPEG, PNG等)
- 配置化的安全设置和生成参数
- Redis缓存机制避免重复分析
- 多级图片压缩策略

输入: 图片二进制数据 + MIME类型 + 可选提示词
输出: AI生成的图片描述文本
"""

import os
import httpx
import logging
from utils.logging_config import get_logger

logger = get_logger(__name__)
import json
import asyncio
import base64
import hashlib
import io
from typing import Optional, Tuple
from PIL import Image

# --- 从 ai_service.py 借鉴的配置 ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = os.getenv("GEMINI_API_URL111", "https://yunwu.ai/v1beta/models/")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# Redis 客户端 - 迁移自 image_content_analyzer.py
from utils.redis_manager import get_redis_client
redis_client = get_redis_client()


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
                    logger.error("达到最大重试次数，放弃重试")
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
                logger.error("达到最大重试次数，放弃重试")
                raise


async def get_image_description(
    image_data: bytes,
    mime_type: str,
    prompt: str = (
        "请用流畅的自然语言描述这张图片的内容，保证在准确描述图片主要内容的前提下，不能遗漏任何细节"
        "注意图片中可能包含的文字、重要物品或整体氛围。"
        "务必注意你的回答只需要描述图片的内容，不要有其他任何额外的说明。"
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
                "includeThoughts": False,
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
        logger.info(f"正在使用模型进行 get_image_description(): {model}")
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
        logger.error(f"Gemini Vision 调用失败: 未知错误: {e}")
        return "[图片处理失败: 未知错误]"


# ==========================================
# 以下函数迁移自 image_content_analyzer.py
# ==========================================

def get_image_path_hash(image_path: str) -> str:
    """
    生成图片路径的SHA256哈希值，用作Redis键名。
    
    迁移自 image_content_analyzer.py
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        str: SHA256哈希值
    """
    return hashlib.sha256(image_path.encode('utf-8')).hexdigest()


def compress_image_if_needed(image_data: bytes, max_size_mb: float = 3.0) -> Tuple[bytes, str]:
    """
    如果图片超过指定大小，则压缩图片
    
    迁移自 image_content_analyzer.py
    
    Args:
        image_data: 原始图片数据
        max_size_mb: 最大允许大小（MB）
        
    Returns:
        Tuple[bytes, str]: (压缩后的图片数据, MIME类型)
    """
    try:
        current_size_mb = len(image_data) / (1024 * 1024)
        
        if current_size_mb <= max_size_mb:
            # 判断原图片格式
            try:
                img = Image.open(io.BytesIO(image_data))
                mime_type = f"image/{img.format.lower()}" if img.format else "image/png"
                logger.debug(f"[image_service] 图片大小 {current_size_mb:.2f}MB，无需压缩")
                return image_data, mime_type
            except Exception:
                return image_data, "image/png"
        
        logger.info(f"[image_service] 图片大小 {current_size_mb:.2f}MB 超过限制，开始压缩...")
        
        # 打开图片
        img = Image.open(io.BytesIO(image_data))
        
        # 转换为RGB模式（如果需要）
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # 计算压缩比例
        target_ratio = max_size_mb / current_size_mb
        scale_factor = min(0.9, target_ratio ** 0.5)  # 保守压缩
        
        # 调整尺寸
        new_width = int(img.width * scale_factor)
        new_height = int(img.height * scale_factor)
        img_resized = img.resize((new_width, new_height), Image.Lanczos)
        
        # 尝试不同的质量设置
        for quality in [85, 75, 65, 55]:
            output = io.BytesIO()
            img_resized.save(output, format='JPEG', quality=quality, optimize=True)
            compressed_data = output.getvalue()
            compressed_size_mb = len(compressed_data) / (1024 * 1024)
            
            if compressed_size_mb <= max_size_mb:
                logger.info(f"[image_service] 压缩成功：{current_size_mb:.2f}MB → {compressed_size_mb:.2f}MB（质量:{quality}）")
                return compressed_data, "image/jpeg"
        
        # 如果还是太大，再次缩小尺寸
        for scale in [0.8, 0.6, 0.4]:
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)
            img_small = img.resize((new_width, new_height), Image.Lanczos)
            
            output = io.BytesIO()
            img_small.save(output, format='JPEG', quality=60, optimize=True)
            compressed_data = output.getvalue()
            compressed_size_mb = len(compressed_data) / (1024 * 1024)
            
            if compressed_size_mb <= max_size_mb:
                logger.info(f"[image_service] 极限压缩成功：{current_size_mb:.2f}MB → {compressed_size_mb:.2f}MB（缩放:{scale}）")
                return compressed_data, "image/jpeg"
        
        # 实在压缩不下去，返回最后一次尝试的结果
        logger.warning(f"[image_service] 压缩后仍然较大：{compressed_size_mb:.2f}MB，但已尽力压缩")
        return compressed_data, "image/jpeg"
        
    except Exception as e:
        logger.error(f"[image_service] 图片压缩失败：{e}")
        return image_data, "image/png"


async def get_image_description_by_path(image_path: str) -> Optional[str]:
    """
    根据图片路径获取缓存的描述。
    
    迁移自 image_content_analyzer.py
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        Optional[str]: 缓存的图片描述，没有时返回None
    """
    try:
        path_hash = get_image_path_hash(image_path)
        redis_key = f"image_desc:{path_hash}"
        description = redis_client.get(redis_key)
        
        if description:
            logger.debug(f"[image_service] 获取到图片描述: {image_path}")
            return description
        else:
            logger.debug(f"[image_service] 未找到图片描述: {image_path}")
            return None
            
    except Exception as e:
        logger.error(f"[image_service] 获取图片描述时出错: {e}")
        return None
