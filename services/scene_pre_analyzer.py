import os
import httpx
import logging
import json
import hashlib
import redis
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# API 配置 - 复用image_content_analyzer的配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = "https://gemini-v.kawaro.space/v1beta/models/gemini-2.5-flash-lite:generateContent"

# Redis 客户端
from utils.redis_manager import get_redis_client
redis_client = get_redis_client()

# 通知配置 - 复用image_content_analyzer的通知系统
NOTIFICATION_CHANNEL_ID = "eqgikba1opnpupiy3w16icdxoo"  # 预分析通知频道


async def send_scene_analysis_notification(
    scene_data: Dict[str, Any],
    is_selfie: bool,
    success: bool,
    analysis_result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
):
    """
    发送场景预分析结果通知到Mattermost频道

    Args:
        scene_data: 原始场景数据
        is_selfie: 是否为自拍模式
        success: 是否成功
        analysis_result: 成功时的分析结果
        error: 失败时的错误信息
    """
    try:
        # 获取场景基本信息
        scene_id = scene_data.get('id', 'unknown')
        content_preview = scene_data.get('content', '')[:50] + "..." if scene_data.get('content') else "N/A"
        mode = "自拍模式" if is_selfie else "场景模式"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if success and analysis_result:
            # 成功消息
            characters = analysis_result.get('characters', [])
            character_count = len(characters)
            scene_desc = analysis_result.get('description', 'N/A')[:100] + "..."

            # 构建角色表情信息
            expressions_info = ""
            if analysis_result.get('character_expressions'):
                expressions = []
                for expr in analysis_result['character_expressions']:
                    name = expr.get('name', '')
                    expression = expr.get('expression', '')
                    if name and expression:
                        expressions.append(f"• {name}: {expression}")
                if expressions:
                    expressions_info = "\n\n**🎭 角色表情分析:**\n" + "\n".join(expressions)

            message = f"""## 🎉 AI场景预分析成功 ({mode})

**🆔 场景ID:** `{scene_id}`
**⏰ 分析时间:** `{timestamp}`
**📝 原始内容:** {content_preview}

**🔍 分析结果:**
• **场景描述:** {scene_desc}
• **检测角色:** {characters} ({character_count}个)
• **地点设定:** {analysis_result.get('location', 'N/A')}
• **时间氛围:** {analysis_result.get('time_atmosphere', 'N/A')}
• **情感状态:** {analysis_result.get('emotional_state', 'N/A')}
• **光线效果:** {analysis_result.get('lighting_mood', 'N/A')}
• **色彩基调:** {analysis_result.get('color_tone', 'N/A')}{expressions_info}

**📊 状态:** ✅ **分析成功**
**🚀 功能:** AI增强提示词已生效，图片生成将使用高质量描述

---
*💡 此分析结果已缓存2小时，用于优化图片生成质量*"""

        else:
            # 失败消息
            error_display = error[:200] + "..." if error and len(error) > 200 else error or "未知错误"

            message = f"""## ⚠️ AI场景预分析失败 ({mode})

**🆔 场景ID:** `{scene_id}`
**⏰ 分析时间:** `{timestamp}`
**📝 原始内容:** {content_preview}
**❌ 错误信息:**

```
{error_display}
```

**📊 状态:** 🔴 **分析失败**
**🛡️ 保障机制:** 已自动降级到传统角色检测和描述构建，不影响图片生成功能

---
*🔧 请检查Gemini API配置和网络连接*"""

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
                logger.debug(f"[scene_analyzer] ✅ 通知消息发送成功: {scene_id}")
            else:
                logger.warning(f"⚠️ [scene_analyzer] 通知消息发送失败: {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"❌ [scene_analyzer] 发送通知消息时出错: {e}")


def get_scene_hash(scene_data: Dict[str, Any]) -> str:
    """
    生成场景数据的SHA256哈希值，用作Redis键名。

    Args:
        scene_data: 场景数据字典

    Returns:
        str: SHA256哈希值
    """
    scene_str = json.dumps(scene_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(scene_str.encode('utf-8')).hexdigest()


async def analyze_scene(scene_data: Dict[str, Any], is_selfie: bool = False) -> Optional[Dict[str, Any]]:
    """
    使用AI分析场景数据，返回结构化的场景描述和角色信息。

    Args:
        scene_data: 包含经历信息的字典数据
        is_selfie: 是否为自拍模式

    Returns:
        Optional[Dict[str, Any]]: 分析结果，失败时返回None
    """
    try:
        # 生成Redis键名用于缓存
        scene_hash = get_scene_hash(scene_data)
        cache_key = f"scene_analysis:{scene_hash}:{'selfie' if is_selfie else 'scene'}"

        # 检查是否已有缓存
        cached_result = redis_client.get(cache_key)
        if cached_result:
            logger.debug(f"[scene_analyzer] 使用缓存的场景分析结果")
            return json.loads(cached_result)

        # 构建提示词
        scene_json_str = json.dumps(scene_data, ensure_ascii=False, indent=2)

        if is_selfie:
            prompt = f"""你现在正在扮演德克萨斯，你正在处于下面的这个场景中，并有着下面这样的想法：

{scene_json_str}

你在此时拿出手机拍了一张自拍照片，请分析这张自拍照的内容会是怎样的？

要求：
1. 这是自拍照片，必须包含德克萨斯本人，请确保在角色列表中包含"德克萨斯"
2. 分析画面构图、光线、色彩、氛围等视觉要素
3. 根据场景推测可能出现的其他角色及其表情
4. 考虑德克萨斯的性格特点：高冷内敛，表情通常淡漠，但面对信任的人会有细微的温和神情

请用中文详细分析并填写所有字段。"""
        else:
            prompt = f"""你现在正在扮演德克萨斯，你正在处于下面的这个场景中，并有着下面这样的想法：

{scene_json_str}

你在此时拿出手机以第一人称视角拍摄了一张场景照片，请分析这张照片的内容会是怎样的？

要求：
1. 这是第一人称视角拍摄，通常不会包含德克萨斯自己（除非镜子反射等特殊情况）
2. 重点分析环境场景、可能出现的其他角色
3. 分析画面构图、光线、色彩、氛围等视觉要素
4. 如果场景中有其他角色，请分析他们的表情和状态

请用中文详细分析并填写所有字段。"""

        # 构建请求payload
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "thinkingConfig": {
                    "thinkingBudget": -1,
                },
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string"
                        },
                        "characters": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            }
                        },
                        "location": {
                            "type": "string"
                        },
                        "time_atmosphere": {
                            "type": "string"
                        },
                        "emotional_state": {
                            "type": "string"
                        },
                        "weather_context": {
                            "type": "string"
                        },
                        "activity_background": {
                            "type": "string"
                        },
                        "lighting_mood": {
                            "type": "string"
                        },
                        "composition_style": {
                            "type": "string"
                        },
                        "color_tone": {
                            "type": "string"
                        },
                        "scene_focus": {
                            "type": "string"
                        },
                        "character_expressions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string"
                                    },
                                    "expression": {
                                        "type": "string"
                                    }
                                },
                                "required": ["name", "expression"]
                            }
                        }
                    },
                    "required": [
                        "description",
                        "characters",
                        "location",
                        "time_atmosphere",
                        "emotional_state",
                        "weather_context",
                        "activity_background",
                        "lighting_mood",
                        "composition_style",
                        "color_tone",
                        "scene_focus",
                        "character_expressions"
                    ]
                }
            }
        }

        # 决定使用哪个API key
        api_key = GEMINI_API_KEY if GEMINI_API_KEY else GEMINI_API_KEY2
        if not api_key:
            error_msg = "没有可用的Gemini API密钥"
            logger.error(f"❌ [scene_analyzer] {error_msg}")

            # 🆕 发送失败通知
            try:
                await send_scene_analysis_notification(
                    scene_data, is_selfie, success=False, error=error_msg
                )
            except Exception as notify_error:
                logger.warning(f"⚠️ [scene_analyzer] 发送失败通知失败: {notify_error}")

            return None

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        scene_id = scene_data.get('id', 'unknown')
        mode = "自拍" if is_selfie else "场景"
        logger.info(f"[scene_analyzer] 开始{mode}模式场景分析: {scene_id}")

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

                    result_text = response_json["candidates"][0]["content"]["parts"][0].get("text", "").strip()

                    if result_text:
                        try:
                            result = json.loads(result_text)

                            # 自拍模式确保包含德克萨斯
                            if is_selfie and "德克萨斯" not in result.get("characters", []):
                                result["characters"].append("德克萨斯")
                                # 也添加到character_expressions中
                                expressions = result.get("character_expressions", [])
                                has_texas_expression = any(expr.get("name") == "德克萨斯" for expr in expressions)
                                if not has_texas_expression:
                                    expressions.append({
                                        "name": "德克萨斯",
                                        "expression": "淡漠中透露着细微的情感波动"
                                    })
                                    result["character_expressions"] = expressions

                            # 缓存结果到Redis，48小时过期（与图片元数据映射保持一致）
                            redis_client.setex(cache_key, 172800, json.dumps(result, ensure_ascii=False))
                            logger.info(f"[scene_analyzer] ✅ {mode}场景分析成功: {len(result.get('characters', []))}个角色")

                            # 🆕 发送成功通知到Mattermost
                            try:
                                await send_scene_analysis_notification(
                                    scene_data, is_selfie, success=True, analysis_result=result
                                )
                            except Exception as notify_error:
                                logger.warning(f"⚠️ [scene_analyzer] 发送成功通知失败（不影响主功能）: {notify_error}")

                            return result
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ [scene_analyzer] JSON解析失败: {e}")
                            logger.debug(f"原始响应: {result_text}")
                            return None
                    else:
                        logger.warning(f"⚠️ [scene_analyzer] API返回空内容")
                        return None
                else:
                    logger.warning(f"⚠️ [scene_analyzer] API响应格式异常: {response_json}")
                    return None

            except httpx.TimeoutException:
                error_msg = "API请求超时"
                logger.error(f"❌ [scene_analyzer] {error_msg}")

                # 🆕 发送失败通知
                try:
                    await send_scene_analysis_notification(
                        scene_data, is_selfie, success=False, error=error_msg
                    )
                except Exception as notify_error:
                    logger.warning(f"⚠️ [scene_analyzer] 发送失败通知失败: {notify_error}")

                return None
            except httpx.HTTPStatusError as e:
                error_msg = f"API请求失败: {e.response.status_code} - {e.response.text}"
                logger.error(f"❌ [scene_analyzer] {error_msg}")

                # 🆕 发送失败通知
                try:
                    await send_scene_analysis_notification(
                        scene_data, is_selfie, success=False, error=error_msg
                    )
                except Exception as notify_error:
                    logger.warning(f"⚠️ [scene_analyzer] 发送失败通知失败: {notify_error}")

                return None

    except Exception as e:
        logger.error(f"❌ [scene_analyzer] 分析场景时发生未知错误: {str(e)}")

        # 🆕 发送失败通知到Mattermost
        try:
            await send_scene_analysis_notification(
                scene_data, is_selfie, success=False, error=str(e)
            )
        except Exception as notify_error:
            logger.warning(f"⚠️ [scene_analyzer] 发送失败通知失败: {notify_error}")

        return None


async def get_cached_scene_analysis(scene_data: Dict[str, Any], is_selfie: bool = False) -> Optional[Dict[str, Any]]:
    """
    仅获取缓存的场景分析结果，不发起新的API请求。

    Args:
        scene_data: 场景数据
        is_selfie: 是否为自拍模式

    Returns:
        Optional[Dict[str, Any]]: 缓存的分析结果，没有时返回None
    """
    try:
        scene_hash = get_scene_hash(scene_data)
        cache_key = f"scene_analysis:{scene_hash}:{'selfie' if is_selfie else 'scene'}"
        cached_result = redis_client.get(cache_key)

        if cached_result:
            return json.loads(cached_result)
        else:
            return None

    except Exception as e:
        logger.error(f"❌ [scene_analyzer] 获取缓存场景分析时出错: {e}")
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
                logger.warning(f"⚠️ [scene_analyzer] 第{attempt + 1}次尝试失败，{delay}秒后重试: {e}")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"❌ [scene_analyzer] 达到最大重试次数，放弃: {e}")
                raise
