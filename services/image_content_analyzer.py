import os
import httpx
import logging
import base64
import hashlib
import redis
import asyncio
from typing import Optional
from datetime import datetime
from app.config import settings

logger = logging.getLogger(__name__)

# API 配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = "https://gemini-v.kawaro.space/v1beta/models/gemini-2.5-flash-lite:generateContent"

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)

# 通知配置 - 你需要指定一个专门接收通知的频道ID
NOTIFICATION_CHANNEL_ID = "eqgikba1opnpupiy3w16icdxoo"  # 请替换为实际的频道ID


async def send_analysis_notification(
    image_path: str, 
    success: bool, 
    description: Optional[str] = None, 
    error: Optional[str] = None
):
    """
    发送图片分析结果通知到Mattermost频道
    
    Args:
        image_path: 图片文件路径
        success: 是否成功
        description: 成功时的图片描述
        error: 失败时的错误信息
    """
    try:
        # 获取图片基本信息
        image_name = os.path.basename(image_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if success and description:
            # 成功消息
            message = f"""## 🎉 图片内容分析成功

**📸 图片文件:** `{image_name}`  
**⏰ 分析时间:** `{timestamp}`  
**🔍 分析结果:**

> {description}

**📊 状态:** ✅ **成功完成**  
**🚀 功能:** 智能占位符已生效，AI对话将能够理解图片内容
            
---
*💡 此图片的描述已缓存24小时，用于提升对话体验*"""

        else:
            # 失败消息
            error_display = error[:200] + "..." if error and len(error) > 200 else error or "未知错误"
            
            message = f"""## ⚠️ 图片内容分析失败

**📸 图片文件:** `{image_name}`  
**⏰ 分析时间:** `{timestamp}`  
**❌ 错误信息:**

```
{error_display}
```

**📊 状态:** 🔴 **分析失败**  
**🛡️ 保障机制:** 已自动降级到默认占位符 `[图片已发送]`，不影响正常功能

---
*🔧 请检查API密钥配置和网络连接*"""

        # 发送消息到Mattermost
        mattermost_url = "https://prts.kawaro.space/api/v4/posts"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer 8or4yqexc3r6brji6s4acp1ycr"
        }
        
        payload = {
            "channel_id": NOTIFICATION_CHANNEL_ID,
            "message": message
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(mattermost_url, headers=headers, json=payload)
            
            if response.status_code == 201:
                logger.debug(f"[image_analyzer] ✅ 通知消息发送成功: {image_name}")
            else:
                logger.warning(f"⚠️ [image_analyzer] 通知消息发送失败: {response.status_code} - {response.text}")
                
    except Exception as e:
        logger.error(f"❌ [image_analyzer] 发送通知消息时出错: {e}")


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
            error_msg = "没有可用的Gemini API密钥"
            logger.error(f"❌ [image_analyzer] {error_msg}")
            
            # 🆕 发送失败通知
            try:
                await send_analysis_notification(image_path, success=False, error=error_msg)
            except Exception as notify_error:
                logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
            
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
                        
                        # 🆕 发送成功通知
                        try:
                            await send_analysis_notification(image_path, success=True, description=description)
                        except Exception as notify_error:
                            logger.warning(f"⚠️ [image_analyzer] 发送成功通知失败（不影响主功能）: {notify_error}")
                        
                        return description
                    else:
                        error_msg = "API返回空描述"
                        logger.warning(f"⚠️ [image_analyzer] {error_msg}")
                        
                        # 🆕 发送失败通知
                        try:
                            await send_analysis_notification(image_path, success=False, error=error_msg)
                        except Exception as notify_error:
                            logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
                        
                        return None
                else:
                    error_msg = f"API响应格式异常: {response_json}"
                    logger.warning(f"⚠️ [image_analyzer] {error_msg}")
                    
                    # 🆕 发送失败通知
                    try:
                        await send_analysis_notification(image_path, success=False, error=error_msg)
                    except Exception as notify_error:
                        logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
                    
                    return None
                    
            except httpx.TimeoutException:
                error_msg = "API请求超时"
                logger.error(f"❌ [image_analyzer] {error_msg}")
                
                # 🆕 发送失败通知
                try:
                    await send_analysis_notification(image_path, success=False, error=error_msg)
                except Exception as notify_error:
                    logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
                
                return None
            except httpx.HTTPStatusError as e:
                error_msg = f"API请求失败: {e.response.status_code} - {e.response.text}"
                logger.error(f"❌ [image_analyzer] {error_msg}")
                
                # 🆕 发送失败通知
                try:
                    await send_analysis_notification(image_path, success=False, error=error_msg)
                except Exception as notify_error:
                    logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
                
                return None
                
    except FileNotFoundError:
        error_msg = f"图片文件未找到: {image_path}"
        logger.error(f"❌ [image_analyzer] {error_msg}")
        
        # 🆕 发送失败通知
        try:
            await send_analysis_notification(image_path, success=False, error=error_msg)
        except Exception as notify_error:
            logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
        
        return None
    except Exception as e:
        error_msg = f"分析图片时发生未知错误: {str(e)}"
        logger.error(f"❌ [image_analyzer] {error_msg}")
        
        # 🆕 发送失败通知
        try:
            await send_analysis_notification(image_path, success=False, error=error_msg)
        except Exception as notify_error:
            logger.warning(f"⚠️ [image_analyzer] 发送失败通知失败（不影响主功能）: {notify_error}")
        
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