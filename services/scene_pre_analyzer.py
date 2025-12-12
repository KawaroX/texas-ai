import os
import httpx
from utils.logging_config import get_logger

logger = get_logger(__name__)
import json
import hashlib
import redis
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime


# API 配置 - 🆕 使用和生成日程完全相同的 API 方式
STRUCTURED_API_KEY = os.getenv("STRUCTURED_API_KEY")
STRUCTURED_API_URL = os.getenv("STRUCTURED_API_URL", "https://yunwu.ai/v1/chat/completions")
STRUCTURED_API_MODEL = os.getenv("STRUCTURED_API_MODEL", "gemini-2.5-flash")

# 🆕 根据生成日程的模型，自动选择对应的 lite 版本
def get_scene_analyzer_model(base_model: str) -> str:
    """
    根据生成日程的模型，返回用于场景分析的模型。

    规则：
    - 如果是 gemini-2.5-flash，返回 gemini-2.5-flash-lite
    - 如果是其他 gemini 模型，尝试返回对应的 lite 版本
    - 如果不是 gemini 模型，返回原模型
    """
    if "gemini" in base_model.lower():
        # 如果已经是 lite 版本，直接返回
        if "-lite" in base_model.lower():
            return base_model
        # 否则，尝试添加 -lite 后缀
        # 例如：gemini-2.5-flash -> gemini-2.5-flash-lite
        #       gemini-2.5-pro -> gemini-2.5-pro-lite
        if base_model.endswith("-flash"):
            return base_model + "-lite"
        elif base_model.endswith("-pro"):
            # pro 系列可能没有 lite 版本，直接用 flash-lite
            return base_model.replace("-pro", "-flash-lite")
        else:
            # 兜底：添加 -lite
            return base_model + "-lite"
    else:
        # 非 gemini 模型，保持一致
        return base_model

SCENE_ANALYZER_MODEL = get_scene_analyzer_model(STRUCTURED_API_MODEL)

logger.info(f"[scene_analyzer] 场景分析配置：URL={STRUCTURED_API_URL}, 生成日程模型={STRUCTURED_API_MODEL}，场景分析模型={SCENE_ANALYZER_MODEL}")

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
                logger.debug(f"[scene_analyzer] 通知消息发送成功: {scene_id}")
            else:
                logger.warning(f"[scene_analyzer] 通知消息发送失败: {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"[scene_analyzer] 发送通知消息时出错: {e}")


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

        # 🆕 构建 OpenAI 兼容格式的提示词
        scene_json_str = json.dumps(scene_data, ensure_ascii=False, indent=2)

        if is_selfie:
            user_prompt = f"""你现在正在扮演德克萨斯，你正在处于下面的这个场景中，并有着下面这样的想法：

{scene_json_str}

你在此时拿出手机拍了一张自拍照片，请分析这张自拍照的内容会是怎样的？

要求：
1. 这是自拍照片，必须包含德克萨斯本人，请确保在角色列表中包含"德克萨斯"
2. 分析画面构图、光线、色彩、氛围等视觉要素
3. 根据场景推测可能出现的其他角色及其表情
4. 考虑德克萨斯的性格特点：内敛温和，表情平静安详，常有淡淡的微笑或温和的神情
5. **🎨 创意性视觉效果分析**：根据场景特点，主动建议适合的高级视觉效果（如：浴室场景→水雾+镜面反射，室外场景→景深+逆光，夜晚场景→霓虹灯光+光晕效果等）
6. **📸 摄影艺术指导**：为这张自拍提供专业的摄影建议（构图技巧、光影运用、氛围营造等）
7. **💃 姿态和表现力**：根据场景氛围，建议更有表现力、更大胆、更性感的姿态和服装细节，展现角色的魅力和自信

请严格按照以下 JSON 格式输出，不要包含任何其他文本：
{{
  "description": "详细的场景描述",
  "characters": ["德克萨斯", "其他角色..."],
  "location": "地点",
  "time_atmosphere": "时间氛围",
  "emotional_state": "情感状态",
  "weather_context": "天气背景",
  "activity_background": "活动背景",
  "lighting_mood": "光线氛围",
  "composition_style": "构图风格",
  "color_tone": "色彩基调",
  "scene_focus": "场景焦点",
  "visual_effects": "特殊视觉效果（如：水雾、镜面反射、光束、雨滴、蒸汽、玻璃折射、bokeh散景、光晕、逆光轮廓、长曝光光轨等），根据场景自然融入",
  "photographic_technique": "摄影技巧（如：浅景深、大光圈bokeh、逆光剪影、HDR、长曝光、仰拍/俯拍、三分构图、对角线构图、框架构图等）",
  "artistic_style": "整体艺术风格（如：电影感、时尚杂志风、Instagram网红风、复古胶片质感、赛博朋克、梦幻柔焦、高对比度等）",
  "pose_suggestion": "姿态建议（自拍专用：更有表现力、更大胆、更性感的姿态，如：撩发、回眸、侧身展现曲线、慵懒姿态、自信站姿等，展现角色魅力）",
  "clothing_details": "服装细节建议（根据场景氛围，建议更有魅力、更时尚、更性感的服装细节，如：露肩、V领、开叉、透视元素、贴身剪裁等，符合角色性格但更大胆）",
  "character_expressions": [
    {{"name": "角色名", "expression": "表情描述"}}
  ]
}}"""
        else:
            user_prompt = f"""你现在正在扮演德克萨斯，你正在处于下面的这个场景中，并有着下面这样的想法：

{scene_json_str}

你在此时拿出手机以第一人称视角拍摄了一张场景照片，请分析这张照片的内容会是怎样的？

要求：
1. 这是第一人称视角拍摄，通常不会包含德克萨斯自己（除非镜子反射等特殊情况）
2. 重点分析环境场景、可能出现的其他角色
3. 分析画面构图、光线、色彩、氛围等视觉要素
4. 如果场景中有其他角色，请分析他们的表情和状态
5. **🎨 创意性视觉效果分析**：根据场景特点，主动建议适合的高级视觉效果（如：雨天→雨滴+地面倒影，咖啡店→景深+暖色光晕，夜景→霓虹灯+长曝光光轨，室内→阳光透过窗帘的光束等）
6. **📸 摄影艺术指导**：为这张场景照提供专业的摄影建议（构图技巧、光影运用、氛围营造等）

请严格按照以下 JSON 格式输出，不要包含任何其他文本：
{{
  "description": "详细的场景描述",
  "characters": ["场景中的角色..."],
  "location": "地点",
  "time_atmosphere": "时间氛围",
  "emotional_state": "情感状态",
  "weather_context": "天气背景",
  "activity_background": "活动背景",
  "lighting_mood": "光线氛围",
  "composition_style": "构图风格",
  "color_tone": "色彩基调",
  "scene_focus": "场景焦点",
  "visual_effects": "特殊视觉效果（如：水雾、镜面反射、光束、雨滴、蒸汽、玻璃折射、bokeh散景、光晕、逆光轮廓、长曝光光轨、地面倒影等），根据场景自然融入",
  "photographic_technique": "摄影技巧（如：浅景深、大光圈bokeh、逆光剪影、HDR、长曝光、仰拍/俯拍、三分构图、对角线构图、框架构图、前景虚化等）",
  "artistic_style": "整体艺术风格（如：电影感、纪实摄影风、Instagram网红风、复古胶片质感、赛博朋克、梦幻柔焦、高对比度、Cinematic等）",
  "character_expressions": [
    {{"name": "角色名", "expression": "表情描述"}}
  ]
}}"""

        # 🆕 构建 OpenAI 兼容格式的 payload
        payload = {
            "model": SCENE_ANALYZER_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            "response_format": {"type": "json_object"},
            "stream": False
        }

        # 🆕 使用 STRUCTURED_API_KEY
        if not STRUCTURED_API_KEY:
            error_msg = "没有可用的Gemini API密钥"
            logger.error(f"[scene_analyzer] {error_msg}")

            # 🆕 发送失败通知
            try:
                await send_scene_analysis_notification(
                    scene_data, is_selfie, success=False, error=error_msg
                )
            except Exception as notify_error:
                logger.warning(f"[scene_analyzer] 发送失败通知失败: {notify_error}")

            return None

        # 🆕 使用 OpenAI 兼容的 Authorization header
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {STRUCTURED_API_KEY}"
        }

        scene_id = scene_data.get('id', 'unknown')
        mode = "自拍" if is_selfie else "场景"
        logger.info(f"[scene_analyzer] 开始{mode}模式场景分析: {scene_id}")

        # 🆕 发送 OpenAI 兼容格式的 API 请求
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(
                    STRUCTURED_API_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

                response_json = response.json()

                # 🆕 提取响应内容 (OpenAI 格式: choices[0].message.content)
                if (response_json.get("choices") and
                    len(response_json["choices"]) > 0 and
                    response_json["choices"][0].get("message") and
                    response_json["choices"][0]["message"].get("content")):

                    result_text = response_json["choices"][0]["message"]["content"].strip()

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
                                        "expression": "平静温和的表情，面带淡淡微笑"
                                    })
                                    result["character_expressions"] = expressions

                            # 缓存结果到Redis，48小时过期（与图片元数据映射保持一致）
                            redis_client.setex(cache_key, 172800, json.dumps(result, ensure_ascii=False))
                            logger.info(f"[scene_analyzer] {mode}场景分析成功: {len(result.get('characters', []))}个角色")

                            # 🆕 发送成功通知到Mattermost
                            try:
                                await send_scene_analysis_notification(
                                    scene_data, is_selfie, success=True, analysis_result=result
                                )
                            except Exception as notify_error:
                                logger.warning(f"[scene_analyzer] 发送成功通知失败（不影响主功能）: {notify_error}")

                            return result
                        except json.JSONDecodeError as e:
                            logger.error(f"[scene_analyzer] JSON解析失败: {e}")
                            logger.debug(f"原始响应: {result_text}")
                            return None
                    else:
                        logger.warning(f"[scene_analyzer] API返回空内容")
                        return None
                else:
                    logger.warning(f"[scene_analyzer] API响应格式异常: {response_json}")
                    return None

            except httpx.TimeoutException:
                error_msg = "API请求超时"
                logger.error(f"[scene_analyzer] {error_msg}")

                # 🆕 发送失败通知
                try:
                    await send_scene_analysis_notification(
                        scene_data, is_selfie, success=False, error=error_msg
                    )
                except Exception as notify_error:
                    logger.warning(f"[scene_analyzer] 发送失败通知失败: {notify_error}")

                return None
            except httpx.HTTPStatusError as e:
                error_msg = f"API请求失败: {e.response.status_code} - {e.response.text}"
                logger.error(f"[scene_analyzer] {error_msg}")

                # 🆕 发送失败通知
                try:
                    await send_scene_analysis_notification(
                        scene_data, is_selfie, success=False, error=error_msg
                    )
                except Exception as notify_error:
                    logger.warning(f"[scene_analyzer] 发送失败通知失败: {notify_error}")

                return None

    except Exception as e:
        logger.error(f"[scene_analyzer] 分析场景时发生未知错误: {str(e)}")

        # 🆕 发送失败通知到Mattermost
        try:
            await send_scene_analysis_notification(
                scene_data, is_selfie, success=False, error=str(e)
            )
        except Exception as notify_error:
            logger.warning(f"[scene_analyzer] 发送失败通知失败: {notify_error}")

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
        logger.error(f"[scene_analyzer] 获取缓存场景分析时出错: {e}")
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
                logger.warning(f"[scene_analyzer] 第{attempt + 1}次尝试失败，{delay}秒后重试: {e}")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"[scene_analyzer] 达到最大重试次数，放弃: {e}")
                raise
