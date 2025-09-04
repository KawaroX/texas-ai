import os
import httpx
import logging
import base64
import hashlib
import redis
import asyncio
from typing import Optional, Tuple
from datetime import datetime
from PIL import Image
import io
from app.config import settings

logger = logging.getLogger(__name__)

# API 配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = "https://gemini-v.kawaro.space/v1beta/models/gemini-2.5-flash-lite:generateContent"

# Redis 客户端
from utils.redis_manager import get_redis_client
redis_client = get_redis_client()

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


def compress_image_if_needed(image_data: bytes, max_size_mb: float = 3.0) -> Tuple[bytes, str]:
    """
    如果图片超过指定大小，则压缩图片
    
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
                logger.debug(f"[image_analyzer] 图片大小 {current_size_mb:.2f}MB，无需压缩")
                return image_data, mime_type
            except Exception:
                return image_data, "image/png"
        
        logger.info(f"[image_analyzer] 图片大小 {current_size_mb:.2f}MB 超过限制，开始压缩...")
        
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
                logger.info(f"[image_analyzer] ✅ 压缩成功：{current_size_mb:.2f}MB → {compressed_size_mb:.2f}MB（质量:{quality}）")
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
                logger.info(f"[image_analyzer] ✅ 极限压缩成功：{current_size_mb:.2f}MB → {compressed_size_mb:.2f}MB（缩放:{scale}）")
                return compressed_data, "image/jpeg"
        
        # 实在压缩不下去，返回最后一次尝试的结果
        logger.warning(f"⚠️ [image_analyzer] 压缩后仍然较大：{compressed_size_mb:.2f}MB，但已尽力压缩")
        return compressed_data, "image/jpeg"
        
    except Exception as e:
        logger.error(f"❌ [image_analyzer] 图片压缩失败：{e}")
        return image_data, "image/png"


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
        
        # 🆕 压缩图片（如果需要）
        compressed_data, mime_type = compress_image_if_needed(image_data, max_size_mb=3.0)
        
        # 图片转base64
        encoded_image = base64.b64encode(compressed_data).decode("utf-8")
        
        # 构建请求payload
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,  # 使用动态检测的MIME类型
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