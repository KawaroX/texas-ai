import os
import httpx
import logging
import base64
import hashlib
import redis
import asyncio
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

# API 配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = "https://gemini-v.kawaro.space/v1beta/models/gemini-2.5-flash-lite:generateContent"

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


def get_image_path_hash(image_path: str) -> str:
    """
    生成图片路径的SHA256哈希值，用作Redis键名。
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        str: SHA256哈希值
    """
    return hashlib.sha256(image_path.encode('utf-8')).hexdigest()


async def analyze_generated_image(image_path: str) -> Optional[str]:
    """
    分析生成的图片内容，返回德克萨斯视角的描述。
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        Optional[str]: 图片描述，失败时返回None
    """
    if not os.path.exists(image_path):
        logger.warning(f"⚠️ [image_analyzer] 图片文件不存在: {image_path}")
        return None
    
    try:
        # 生成Redis键名
        path_hash = get_image_path_hash(image_path)
        redis_key = f"image_desc:{path_hash}"
        
        # 检查是否已有缓存
        cached_desc = redis_client.get(redis_key)
        if cached_desc:
            logger.debug(f"[image_analyzer] 使用缓存描述: {image_path}")
            return cached_desc
        
        # 读取图片文件
        with open(image_path, "rb") as f:
            image_data = f.read()
        
        # 图片转base64
        encoded_image = base64.b64encode(image_data).decode("utf-8")
        
        # 构建请求payload
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",  # 大部分生成的图片都是PNG
                                "data": encoded_image
                            }
                        },
                        {
                            "text": "你现在扮演\"德克萨斯\"在翻看照片，请讲述你看到的照片内容。\n如果图片中出现了黑发兽耳的女孩，这是你自己\"德克萨斯\"，你可以称其为\"我\"，一般是你在自拍。如果出现红色头发天使形象的女孩，称其为\"能天使\"，如果出现黄色头发开朗的女孩，称其为\"空\"，如果出现橙色头发的女孩，称其为\"可颂\"，如果出现企鹅，称其为\"大帝\"如果出现白色头发兽耳的女孩，称其为\"拉普兰德\"。"
                        },
                        {
                            "text": "描述这张照片的主要内容，重点说明场景、人物和主要活动。不要有多余的解释或分析。"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "thinkingConfig": {
                    "thinkingBudget": 0,
                },
                "maxOutputTokens": 200  # 限制输出长度
            },
        }
        
        # 决定使用哪个API key
        api_key = GEMINI_API_KEY if GEMINI_API_KEY else GEMINI_API_KEY2
        if not api_key:
            logger.error("❌ [image_analyzer] 没有可用的Gemini API密钥")
            return None
        
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        
        logger.info(f"[image_analyzer] 开始分析图片内容: {os.path.basename(image_path)}")
        
        # 发送API请求
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(
                    GEMINI_API_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                response_json = response.json()
                
                # 提取响应内容
                if (response_json.get("candidates") and 
                    len(response_json["candidates"]) > 0 and
                    response_json["candidates"][0].get("content") and
                    response_json["candidates"][0]["content"].get("parts") and
                    len(response_json["candidates"][0]["content"]["parts"]) > 0):
                    
                    description = response_json["candidates"][0]["content"]["parts"][0].get("text", "").strip()
                    
                    if description:
                        # 缓存结果到Redis，24小时过期
                        redis_client.setex(redis_key, 86400, description)
                        logger.info(f"[image_analyzer] ✅ 分析成功: {description[:50]}...")
                        return description
                    else:
                        logger.warning("⚠️ [image_analyzer] API返回空描述")
                        return None
                else:
                    logger.warning(f"⚠️ [image_analyzer] API响应格式异常: {response_json}")
                    return None
                    
            except httpx.TimeoutException:
                logger.error("❌ [image_analyzer] API请求超时")
                return None
            except httpx.HTTPStatusError as e:
                logger.error(f"❌ [image_analyzer] API请求失败: {e.response.status_code} - {e.response.text}")
                return None
                
    except FileNotFoundError:
        logger.error(f"❌ [image_analyzer] 图片文件未找到: {image_path}")
        return None
    except Exception as e:
        logger.error(f"❌ [image_analyzer] 分析图片时发生未知错误: {e}")
        return None


async def get_image_description_by_path(image_path: str) -> Optional[str]:
    """
    根据图片路径获取缓存的描述。
    
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
            logger.debug(f"[image_analyzer] 获取到图片描述: {image_path}")
            return description
        else:
            logger.debug(f"[image_analyzer] 未找到图片描述: {image_path}")
            return None
            
    except Exception as e:
        logger.error(f"❌ [image_analyzer] 获取图片描述时出错: {e}")
        return None


async def retry_with_backoff(func, max_retries: int = 2, base_delay: float = 1.0):
    """
    重试机制，支持指数退避
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"⚠️ [image_analyzer] 第{attempt + 1}次尝试失败，{delay}秒后重试: {e}")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"❌ [image_analyzer] 达到最大重试次数，放弃: {e}")
                raise