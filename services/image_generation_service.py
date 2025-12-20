"""
德克萨斯AI图片生成核心服务 (Texas AI Core Image Generation Service)

主要功能:
- 基于OpenAI API的AI图片生成 (场景图和自拍)
- 支持角色检测和多角色场景生成
- 天气感知的服装建议系统
- 图片编辑API集成(multipart/form-data)
- Redis缓存的每日底图选择机制

服务关系:
- 被 image_generation_tasks.py 调用执行具体的图片生成
- 使用 character_manager.py 进行角色检测
- 使用 scene_pre_analyzer.py 进行AI场景预分析
- 使用 bark_notifier.py 发送生成状态通知
- 使用 selfie_base_image_manager.py 管理自拍底图
- 生成的图片被 image_content_analyzer.py 分析内容

核心方法:
- generate_image_from_prompt(): 场景图生成
- generate_selfie(): 自拍图生成
- _generate_scene_with_characters(): 多角色场景生成
- _get_weather_based_clothing_prompt(): 天气感知着装建议

输入: 经历描述文本 + 可选的AI场景分析结果
输出: 生成的图片文件路径
"""

import httpx
from utils.logging_config import get_logger

logger = get_logger(__name__)
import os
import uuid
import redis
from datetime import datetime
from typing import List, Optional, Dict

from app.config import settings
# 修正：导入新的 Bark 推送服务
from .bark_notifier import bark_notifier
from .selfie_base_image_manager import selfie_manager
from .character_manager import character_manager
# 监控功能在 tasks 层使用，这里不需要导入
# from .image_generation_monitor import image_generation_monitor

# Mattermost 提示词日志频道配置
PROMPT_LOG_CHANNEL_ID = "eqgikba1opnpupiy3w16icdxoo"  # 使用与预分析相同的通知频道


async def send_prompt_log_to_mattermost(
    prompt: str,
    image_type: str,
    scene_analysis: Optional[Dict] = None,
    detected_characters: Optional[List[str]] = None,
    clothing_source: str = "未知"
):
    """
    发送图片生成提示词日志到Mattermost

    Args:
        prompt: 完整的生成提示词
        image_type: 图片类型（"自拍" 或 "场景图"）
        scene_analysis: AI场景分析结果（可选）
        detected_characters: 检测到的角色列表（可选）
        clothing_source: 服装建议来源（"AI预分析" 或 "默认建议" 或 "天气系统"）
    """
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 构建场景分析信息
        analysis_info = ""
        if scene_analysis:
            analysis_fields = []
            if scene_analysis.get("location"):
                analysis_fields.append(f"• 地点: {scene_analysis['location']}")
            if scene_analysis.get("time_atmosphere"):
                analysis_fields.append(f"• 时间: {scene_analysis['time_atmosphere']}")
            if scene_analysis.get("weather_context"):
                analysis_fields.append(f"• 天气: {scene_analysis['weather_context']}")

            # 🔍 关键：检查是否有服装建议
            has_clothing_details = "✅ 有" if scene_analysis.get("clothing_details") else "❌ 无"
            analysis_fields.append(f"• **服装建议字段**: {has_clothing_details}")

            if scene_analysis.get("clothing_details"):
                clothing_preview = scene_analysis['clothing_details'][:150] + "..." if len(scene_analysis.get('clothing_details', '')) > 150 else scene_analysis.get('clothing_details', '')
                analysis_fields.append(f"• 服装详情: {clothing_preview}")

            if analysis_fields:
                analysis_info = "\n\n**📊 AI预分析信息:**\n" + "\n".join(analysis_fields)

        # 构建角色信息
        characters_info = ""
        if detected_characters:
            characters_info = f"\n**🎭 检测到的角色:** {', '.join(detected_characters)}"

        # 截取提示词预览（防止过长）
        prompt_preview = prompt[:800] + "..." if len(prompt) > 800 else prompt

        # 服装建议来源标记
        clothing_badge = ""
        if clothing_source == "AI预分析":
            clothing_badge = "🤖 **服装来源:** AI场景预分析"
        elif clothing_source == "默认建议":
            clothing_badge = "⚠️ **服装来源:** 默认建议（预分析缺失）"
        elif clothing_source == "天气系统":
            clothing_badge = "🌤️ **服装来源:** 天气系统"
        else:
            clothing_badge = f"❓ **服装来源:** {clothing_source}"

        message = f"""## 📝 图片生成提示词日志 ({image_type})

**⏰ 生成时间:** `{timestamp}`{characters_info}
{clothing_badge}{analysis_info}

**📜 完整提示词:**
```
{prompt_preview}
```

---
*💡 此日志用于调试图片生成提示词，检查服装建议是否符合场景*"""

        # 发送消息到Mattermost
        mattermost_url = "https://prts.kawaro.space/api/v4/posts"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer 8or4yqexc3r6brji6s4acp1ycr"
        }

        payload = {
            "channel_id": PROMPT_LOG_CHANNEL_ID,
            "message": message
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(mattermost_url, headers=headers, json=payload)

            if response.status_code == 201:
                logger.debug(f"[prompt_log] 提示词日志发送成功")
            else:
                logger.warning(f"[prompt_log] 提示词日志发送失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[prompt_log] 发送提示词日志时出错: {e}")


# 导入图片生成 Provider
from .image_providers import (
    ImageGenerationRequest,
    ImageGenerationResponse,
    SeeDreamProvider,
    GeminiImageProvider,
    GPTImageProvider
)

# ============================================================
# 图片生成模型配置 - 混合模型策略
# ============================================================
# 不同场景使用不同的模型以优化成本和性能：
# - gpt-image: 纯文字生成和单图生图（成本更低，速度快）
# - seedream: 多图生图（支持多角色场景）
SINGLE_IMAGE_PROVIDER = "gpt-image"  # 单图生图和纯文字生成
MULTI_IMAGE_PROVIDER = "seedream"    # 多图生图
# ============================================================

IMAGE_SAVE_DIR = "/app/generated_content/images"  # 在 Docker 容器内的路径
os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)


class ImageGenerationService:
    def __init__(self):
        # 使用专用的图片生成API Key
        self.api_key = settings.IMAGE_GENERATION_API_KEY

        # 🆕 混合模型策略：根据场景使用不同的 Provider
        # 初始化单图/纯文字 Provider (GPT-Image-1.5-All)
        if SINGLE_IMAGE_PROVIDER == "gpt-image":
            self.single_image_provider = GPTImageProvider(
                api_key=self.api_key,
                api_url="https://yunwu.ai/v1"
            )
            logger.info("📸 单图/纯文字生成模型: GPT-Image-1.5-All")
        elif SINGLE_IMAGE_PROVIDER == "gemini":
            self.single_image_provider = GeminiImageProvider(
                api_key=self.api_key,
                api_url="https://yunwu.ai/v1beta"
            )
            logger.info("📸 单图/纯文字生成模型: Gemini-2.5-Flash-Image")
        elif SINGLE_IMAGE_PROVIDER == "seedream":
            self.single_image_provider = SeeDreamProvider(
                api_key=self.api_key,
                api_url="https://yunwu.ai/v1"
            )
            logger.info("📸 单图/纯文字生成模型: SeeDream")
        else:
            raise ValueError(f"未知的单图 Provider: {SINGLE_IMAGE_PROVIDER}")

        # 初始化多图 Provider (SeeDream)
        if MULTI_IMAGE_PROVIDER == "seedream":
            self.multi_image_provider = SeeDreamProvider(
                api_key=self.api_key,
                api_url="https://yunwu.ai/v1"
            )
            logger.info("📸 多图生成模型: SeeDream (doubao-seedream-4-5-251128)")
        elif MULTI_IMAGE_PROVIDER == "gemini":
            self.multi_image_provider = GeminiImageProvider(
                api_key=self.api_key,
                api_url="https://yunwu.ai/v1beta"
            )
            logger.info("📸 多图生成模型: Gemini-2.5-Flash-Image")
        else:
            raise ValueError(f"未知的多图 Provider: {MULTI_IMAGE_PROVIDER}")

        # 超时配置 (秒) - 保留用于其他操作
        self.generation_timeout = 300
        self.selfie_timeout = 480
        self.multi_character_timeout = 600
        self.download_timeout = 60

        from utils.redis_manager import get_redis_client
        self.redis_client = get_redis_client()

    async def _get_daily_base_image_path(self) -> Optional[str]:
        """获取当天的基础自拍图片本地路径，如果未选定则随机选择并存入Redis。"""
        today = datetime.now().strftime("%Y-%m-%d")
        redis_key = f"daily_selfie_base_path:{today}"

        cached_path = self.redis_client.get(redis_key)
        if cached_path:
            logger.info(f"📸 从Redis缓存中获取到今天的自拍底图路径: {cached_path}")
            return cached_path
        else:
            # 使用本地图片管理器随机选择底图
            new_path = selfie_manager.get_random_local_image()
            if not new_path:
                logger.error("没有可用的本地自拍底图")
                return None

            self.redis_client.set(redis_key, new_path, ex=90000)  # 25小时过期
            logger.info(f"📸 今天首次生成自拍，已选定新的底图路径: {new_path}")
            await bark_notifier.send_notification(
                title="德克萨斯AI-每日自拍底图已选定",
                body=f"今日用于自拍的基础图片已选定: {os.path.basename(new_path)}",
                group="TexasAIPics"
            )
            return new_path

    async def _get_weather_based_clothing_prompt(self) -> str:
        """根据实际天气和星期动态生成服装建议。"""
        try:
            # 获取今天的天气信息
            today = datetime.now().strftime('%Y-%m-%d')
            weather_key = f"life_system:{today}"
            daily_schedule_str = self.redis_client.hget(weather_key, "daily_schedule")

            if daily_schedule_str:
                import json, re
                daily_data = json.loads(daily_schedule_str)
                weather_str = daily_data.get('weather', '')

                # 解析温度范围，支持负数，例如 "气温-5~3" 或 "气温28~33"
                temp_match = re.search(r'气温(-?\d+).*?(-?\d+)', weather_str)
                if temp_match:
                    temp1 = int(temp_match.group(1))
                    temp2 = int(temp_match.group(2))
                    min_temp = min(temp1, temp2)
                    max_temp = max(temp1, temp2)
                    # 偏向更大的值：权重比例为 3:7 (最小值:最大值)
                    weighted_temp = int(min_temp * 0.3 + max_temp * 0.7)

                    # 发送Bark通知
                    await bark_notifier.send_notification(
                        "德克萨斯AI-天气解析",
                        f"采用: {weighted_temp}°C，温度范围: {min_temp}°C~{max_temp}°C",
                        "TexasAIWeather"
                    )
                    avg_temp = weighted_temp
                else:
                    avg_temp = 28  # 默认温度
                    await bark_notifier.send_notification(
                        "德克萨斯AI-天气解析",
                        f"未解析到温度信息: '{weather_str}'，使用默认28°C",
                        "TexasAIWeather"
                    )

                # 根据平均温度决定服装
                if avg_temp >= 28:
                    temp_suggestion = "穿着清凉舒适的夏日服装，比如薄T恤、短袖衫或轻薄连衣裙。"
                elif avg_temp >= 22:
                    temp_suggestion = "穿着舒适的轻便服装，比如薄长袖、衬衫或轻薄外套。"
                elif avg_temp >= 15:
                    temp_suggestion = "穿着适中的秋季服装，比如毛衣、薄外套或长袖衫。"
                elif avg_temp >= 7.5:
                    temp_suggestion = "穿着保暖的冬季服装，比如厚外套、毛衣或围巾。"
                else:
                    temp_suggestion = "穿着厚实的严寒服装，比如羽绒服、厚围巾和手套。"

                # 根据天气状况调整
                if '雨' in weather_str or '雷' in weather_str:
                    weather_suggestion = "考虑到雨天，可以搭配雨具或选择不易湿透的服装。"
                elif '雪' in weather_str:
                    weather_suggestion = "考虑到雪天，选择防寒保暖的服装。"
                elif '多云' in weather_str:
                    weather_suggestion = "天气较为温和，适合多种服装搭配。"
                else:
                    weather_suggestion = ""

                clothing_prompt = f"{temp_suggestion} {weather_suggestion}".strip()
            else:
                # 没有天气数据时使用默认逻辑
                month = datetime.now().month
                if month in [12, 1, 2]:
                    clothing_prompt = "穿着保暖的冬季服装，比如厚外套、毛衣或围巾。"
                elif month in [3, 4, 5]:
                    clothing_prompt = "穿着舒适的春季服装，比如衬衫或轻薄外套。"
                elif month in [6, 7, 8]:
                    clothing_prompt = "穿着清凉的夏日服装，比如T恤、短袖或连衣裙。"
                else: # 9, 10, 11
                    clothing_prompt = "穿着舒适的秋季服装，比如薄毛衣或轻便外套。"
        except Exception as e:
            logger.warning(f"获取天气信息失败，使用默认服装建议: {e}")
            clothing_prompt = "穿着舒适得体的日常服装。"

        # 星期判断
        weekday = datetime.now().weekday() # Monday is 0 and Sunday is 6
        if weekday >= 5: # Saturday or Sunday
            style_suggestion = "可以是时尚漂亮的周末私服，风格可以大胆一些。"
        else:
            style_suggestion = "根据当前场景设计合适的日常服装：工作场合可以是简洁的工装服配热裤等得体搭配，休闲时刻可以是舒适的日常服或热裤等轻松搭配。整体保持好看和有个性。"

        return f"{clothing_prompt} {style_suggestion}"

    def _convert_image_to_base64_url(self, image_data: bytes) -> str:
        """将图片二进制数据转换为base64 data URL格式，用于SeeDream API"""
        import base64
        base64_data = base64.b64encode(image_data).decode('utf-8')
        data_url = f"data:image/png;base64,{base64_data}"
        logger.info(f"已将图片转换为base64 data URL，长度: {len(data_url)} chars")
        return data_url

    async def _generate_with_provider(
        self,
        prompt: str,
        images: Optional[List[bytes]] = None,
        size: Optional[str] = None
    ) -> Optional[str]:
        """
        使用配置的 Provider 生成图片（混合模型策略）

        Args:
            prompt: 生成提示词
            images: 底图列表（可选，支持多图）
            size: 图片尺寸

        Returns:
            生成的图片文件路径，失败返回 None
        """
        request = ImageGenerationRequest(
            prompt=prompt,
            images=images,
            size=size,
            watermark=False
        )

        # 🆕 根据图片数量选择合适的 Provider
        if images and len(images) > 1:
            # 多图模式：使用多图 Provider
            logger.info(f"🎨 使用多图 Provider: {self.multi_image_provider.get_provider_name()}")
            provider = self.multi_image_provider
        else:
            # 单图或纯文字模式：使用单图 Provider
            logger.info(f"🎨 使用单图 Provider: {self.single_image_provider.get_provider_name()}")
            provider = self.single_image_provider

        response = await provider.generate_image(request)

        if response.success and response.image_data:
            filepath = self._save_image(response.image_data)
            return filepath
        else:
            logger.error(f"图片生成失败: {response.error}")
            return None

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片内容"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True, timeout=self.download_timeout)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            logger.error(f"下载图片失败 (HTTP Status): {e.response.status_code} for URL: {url}")
            return None
        except Exception as e:
            logger.error(f"下载图片时发生未知异常: {e} for URL: {url}")
            return None

    def _save_image(self, image_data: bytes, extension: str = "png") -> str:
        """将图片数据保存到本地文件"""
        today_dir = os.path.join(IMAGE_SAVE_DIR, datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(today_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}.{extension}"
        filepath = os.path.join(today_dir, filename)
        with open(filepath, "wb") as f:
            f.write(image_data)
        logger.info(f"🖼️ 图片已保存到: {filepath}")
        return filepath

    async def generate_image_from_prompt(self, experience_description: str, scene_analysis: Optional[Dict] = None) -> Optional[str]:
        """根据经历描述生成图片"""
        await bark_notifier.send_notification("德克萨斯AI-开始生成场景图", f"内容: {experience_description[:50]}...", "TexasAIPics")
        if not self.api_key:
            logger.warning("未配置 OPENAI_API_KEY，跳过图片生成。")
            await bark_notifier.send_notification("德克萨斯AI-生成场景图失败", "错误: 未配置OPENAI_API_KEY", "TexasAIPics")
            return None

        # 🆕 优先使用AI预分析的角色检测结果
        if scene_analysis:
            detected_characters = scene_analysis.get("characters", [])
            logger.info(f"使用AI预分析检测到的角色: {detected_characters}")
        else:
            # 回退到传统角色检测方法
            detected_characters = character_manager.detect_characters_in_text(experience_description)
            logger.info(f"使用传统方法检测到场景中的角色: {detected_characters}")

        # 如果检测到角色，尝试使用角色图片增强生成
        if detected_characters:
            return await self._generate_scene_with_characters(experience_description, detected_characters, scene_analysis)
        else:
            return await self._generate_scene_without_characters(experience_description, scene_analysis)

    async def _generate_scene_without_characters(self, experience_description: str, scene_analysis: Optional[Dict] = None) -> Optional[str]:
        """生成不包含特定角色的场景图（纯文字生成）"""
        # 🆕 使用AI预分析增强提示词 - 加入德克萨斯视角和明日方舟风格
        base_prompt = (
            f"请根据德克萨斯的第一人称视角和下面的场景描述，生成一张高质量的场景图片。"
            f"世界观：明日方舟-龙门都市，现代都市风格，带有科技感和未来感的城市景观。"
            f"氛围风格：冷静、疏离、都市感，德克萨斯独有的冷静观察视角，画面带有性冷淡的高级感。"
            f"视角要求：以德克萨斯的第一人称视角构图，展现她所看到的环境、场景和氛围，画面中不要出现拍摄者本人。"
            f"构图重点：突出场景环境、物品、建筑、风景等，营造冷艳都市的氛围感。如果场景中需要其他人物，应作为背景元素而非主体。"
            f"画面风格：都市、现代、简约、带有一丝疏离感和冷静氛围，符合德克萨斯的高冷性格特质。"
        )

        # 构建增强的场景描述
        if scene_analysis:
            enhanced_details = []
            if scene_analysis.get("location"):
                enhanced_details.append(f"地点设定: {scene_analysis['location']}")
            if scene_analysis.get("time_atmosphere"):
                enhanced_details.append(f"时间氛围: {scene_analysis['time_atmosphere']}")
            if scene_analysis.get("lighting_mood"):
                enhanced_details.append(f"光线效果: {scene_analysis['lighting_mood']}")
            if scene_analysis.get("color_tone"):
                enhanced_details.append(f"色彩基调: {scene_analysis['color_tone']}")
            if scene_analysis.get("composition_style"):
                enhanced_details.append(f"构图风格: {scene_analysis['composition_style']}")
            if scene_analysis.get("weather_context"):
                enhanced_details.append(f"天气环境: {scene_analysis['weather_context']}")

            # 🎨 新增：高级视觉效果
            if scene_analysis.get("visual_effects"):
                enhanced_details.append(f"✨ 特殊视觉效果: {scene_analysis['visual_effects']}")
            if scene_analysis.get("photographic_technique"):
                enhanced_details.append(f"📸 摄影技巧: {scene_analysis['photographic_technique']}")
            if scene_analysis.get("artistic_style"):
                enhanced_details.append(f"🎬 艺术风格: {scene_analysis['artistic_style']}")

            enhanced_desc = " | ".join(enhanced_details) if enhanced_details else experience_description
            prompt = f"{base_prompt}场景描述: {enhanced_desc}"
        else:
            prompt = f"{base_prompt}场景描述: {experience_description}"

        # 场景图：使用AI推荐的尺寸，默认16:9横屏4K
        recommended_size = scene_analysis.get("recommended_image_size", "3840x2160") if scene_analysis else "3840x2160"

        # 📝 发送提示词日志到Mattermost（用于调试）
        try:
            await send_prompt_log_to_mattermost(
                prompt=prompt,
                image_type="场景图（无角色）",
                scene_analysis=scene_analysis,
                detected_characters=None,
                clothing_source="不适用（无人物）"
            )
        except Exception as e:
            logger.warning(f"发送提示词日志失败（不影响图片生成）: {e}")

        # 🆕 使用新的 Provider 接口
        filepath = await self._generate_with_provider(prompt=prompt, images=None, size=recommended_size)

        if filepath:
            await bark_notifier.send_notification("德克萨斯AI-生成场景图成功", f"图片已保存到 {filepath}", "TexasAIPics")
            return filepath
        else:
            await bark_notifier.send_notification("德克萨斯AI-生成场景图失败", "错误: 图片生成失败", "TexasAIPics")
            return None

    async def _generate_scene_with_characters(self, experience_description: str, detected_characters: List[str], scene_analysis: Optional[Dict] = None) -> Optional[str]:
        """生成包含特定角色的场景图（支持多图输入）"""
        logger.info(f"🎭 使用角色增强生成场景图: {detected_characters}")

        # 🆕 读取所有检测到的角色图片（支持多图输入）
        character_images = []
        character_image_paths = []

        for char_name in detected_characters:
            char_image_path = character_manager.get_character_image_path(char_name)
            if char_image_path:
                try:
                    with open(char_image_path, 'rb') as f:
                        char_image_data = f.read()
                    character_images.append(char_image_data)
                    character_image_paths.append(char_image_path)
                    logger.info(f"✅ 成功读取角色图片: {char_name} -> {char_image_path}")
                except Exception as e:
                    logger.warning(f"⚠️ 无法读取角色图片 {char_name}: {e}")
            else:
                logger.warning(f"⚠️ 未找到角色 {char_name} 的本地图片")

        # 如果没有成功读取任何角色图片，回退到普通场景生成
        if not character_images:
            logger.warning(f"未能读取任何角色图片，回退到普通场景生成")
            return await self._generate_scene_without_characters(experience_description, scene_analysis)

        logger.info(f"📸 共读取 {len(character_images)} 张角色图片，将使用多图生成模式")
        main_character = detected_characters[0]

        # 🆕 构建增强的提示词，结合AI预分析和传统方法
        base_prompt = (
            f"请将这张角色图片作为基础，根据以下场景描述，生成一张高质量的二次元风格多角色场景图片。"
            f"艺术风格要求：保持明日方舟游戏的二次元动漫画风，避免过于写实的三次元风格，色彩明亮，构图富有故事感。"
        )

        # 构建角色信息
        character_descriptions = self._build_character_descriptions(detected_characters, main_character)
        character_prompt = f"角色信息：{character_descriptions}"

        # 🆕 使用AI预分析的角色表情或回退到传统表情描述
        if scene_analysis and scene_analysis.get("character_expressions"):
            expressions = scene_analysis["character_expressions"]
            expression_descriptions = []
            for expr in expressions:
                char_name = expr.get("name", "")
                char_expr = expr.get("expression", "")
                if char_name and char_expr:
                    expression_descriptions.append(f"{char_name}（{char_expr}）")

            if expression_descriptions:
                expression_prompt = f"神态表情要求：{', '.join(expression_descriptions)}。表情要贴合当前场景情境。"
            else:
                expression_prompt = f"神态表情要求：根据各角色性格特点设计表情神态 - 德克萨斯（平静温和的微笑或安详表情），能天使（活泼开朗的笑容），可颂（慵懒随意的神情），空（安静温和的表情），拉普兰德（略带野性的神态），大帝（威严中带着亲和）等。神态要贴合当前场景情境。"
        else:
            expression_prompt = f"神态表情要求：根据各角色性格特点设计表情神态 - 德克萨斯（平静温和的微笑或安详表情），能天使（活泼开朗的笑容），可颂（慵懒随意的神情），空（安静温和的表情），拉普兰德（略带野性的神态），大帝（威严中带着亲和）等。神态要贴合当前场景情境。"

        # 🆕 服装建议：结合AI预分析和天气系统
        clothing_parts = []
        clothing_source = "未知"  # 记录服装建议来源

        # 🎨 优先使用AI预分析的服装细节建议
        if scene_analysis and scene_analysis.get("clothing_details"):
            clothing_parts.append(f"💃 AI建议服装细节: {scene_analysis['clothing_details']}")
            clothing_source = "AI预分析"
        else:
            # 如果没有AI建议，使用天气系统建议
            clothing_source = "天气系统"

        # 添加天气情况描述（来自AI预分析）
        if scene_analysis and scene_analysis.get("weather_context"):
            clothing_parts.append(f"天气情况: {scene_analysis['weather_context']}")

        # 添加具体着装建议（来自天气系统）
        traditional_clothing = await self._get_weather_based_clothing_prompt()
        clothing_parts.append(traditional_clothing)

        clothing_parts.append("每个角色的服装应该体现其个性特色并与场景氛围协调")
        clothing_prompt = f"服装设计要求：所有角色都需要重新设计符合当前场景的服装，不要直接沿用底图原有服装。{' '.join(clothing_parts)}"

        # 🆕 构建增强的场景描述
        if scene_analysis:
            scene_details = []
            if scene_analysis.get("location"):
                scene_details.append(f"地点: {scene_analysis['location']}")
            if scene_analysis.get("time_atmosphere"):
                scene_details.append(f"时间氛围: {scene_analysis['time_atmosphere']}")
            if scene_analysis.get("lighting_mood"):
                scene_details.append(f"光线效果: {scene_analysis['lighting_mood']}")
            if scene_analysis.get("color_tone"):
                scene_details.append(f"色彩基调: {scene_analysis['color_tone']}")
            if scene_analysis.get("composition_style"):
                scene_details.append(f"构图风格: {scene_analysis['composition_style']}")
            if scene_analysis.get("emotional_state"):
                scene_details.append(f"场景氛围: {scene_analysis['emotional_state']}")

            # 🎨 新增：高级视觉效果
            if scene_analysis.get("visual_effects"):
                scene_details.append(f"✨ 特殊视觉效果: {scene_analysis['visual_effects']}")
            if scene_analysis.get("photographic_technique"):
                scene_details.append(f"📸 摄影技巧: {scene_analysis['photographic_technique']}")
            if scene_analysis.get("artistic_style"):
                scene_details.append(f"🎬 艺术风格: {scene_analysis['artistic_style']}")

            enhanced_scene_desc = " | ".join(scene_details) if scene_details else experience_description
        else:
            enhanced_scene_desc = experience_description

        # 组合完整提示词
        prompt = f"{base_prompt}{character_prompt}{clothing_prompt}{expression_prompt}动作姿态要求：角色的动作和姿态要自然融入场景，展现真实的互动感和生活感。避免死板的pose，要有生动的肢体语言和场景互动，体现角色间的关系。场景融合要求：确保所有角色都真实自然地参与到场景中，服装、动作、表情都要与环境完美匹配，营造生动的生活画面。场景描述: {enhanced_scene_desc}"

        # 场景图（含角色）：使用AI推荐的尺寸，默认16:9横屏4K
        recommended_size = scene_analysis.get("recommended_image_size", "3840x2160") if scene_analysis else "3840x2160"

        # 📝 发送提示词日志到Mattermost（用于调试）
        try:
            await send_prompt_log_to_mattermost(
                prompt=prompt,
                image_type="场景图（含角色）",
                scene_analysis=scene_analysis,
                detected_characters=detected_characters,
                clothing_source=clothing_source
            )
        except Exception as e:
            logger.warning(f"发送提示词日志失败（不影响图片生成）: {e}")

        # 🆕 使用新的 Provider 接口（支持多图输入）
        filepath = await self._generate_with_provider(prompt=prompt, images=character_images, size=recommended_size)

        if filepath:
            await bark_notifier.send_notification("德克萨斯AI-多角色场景图成功", f"包含角色: {', '.join(detected_characters)}", "TexasAIPics")
            return filepath
        else:
            await bark_notifier.send_notification("德克萨斯AI-多角色场景图失败", "错误: 图片生成失败", "TexasAIPics")
            return None

    def _build_character_descriptions(self, characters: List[str], main_character: str) -> str:
        """构建角色描述信息"""
        descriptions = []

        # 角色特征描述
        character_traits = {
            "能天使": "活泼开朗的天使族女孩，红色头发，头顶有光圈，多个长三角形组成的光翼，充满活力",
            "可颂": "乐观开朗活泼的企鹅物流成员，橙色头发",
            "空": "活泼开朗的干员，黄色头发，明快的表情",
            "拉普兰德": "过于开朗特别活泼的狼族干员，白色头发，狼耳朵，古灵精怪略带病娇的笑容",
            "大帝": "喜欢说唱的帝企鹅，戴着墨镜和大金链子，西海岸嘻哈风格，企鹅形态而非人形"
        }

        descriptions.append(f"主要角色：{main_character}（{character_traits.get(main_character, '明日方舟角色')}）")

        if len(characters) > 1:
            other_chars = [char for char in characters if char != main_character]
            other_descriptions = [f"{char}（{character_traits.get(char, '明日方舟角色')}）" for char in other_chars]
            descriptions.append(f"其他角色：{', '.join(other_descriptions)}")

        return " ".join(descriptions)

    async def generate_selfie(self, experience_description: str, scene_analysis: Optional[Dict] = None) -> Optional[str]:
        """根据经历描述和每日基础图片生成自拍，并加入季节性服装要求。"""
        await bark_notifier.send_notification("德克萨斯AI-开始生成自拍", f"内容: {experience_description[:50]}...", "TexasAIPics")
        if not self.api_key:
            logger.warning("未配置 OPENAI_API_KEY，跳过自拍生成。")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", "错误: 未配置OPENAI_API_KEY", "TexasAIPics")
            return None

        base_image_path = await self._get_daily_base_image_path()
        if not base_image_path:
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", "错误: 无法获取本地自拍底图", "TexasAIPics")
            return None

        # 读取本地底图文件
        try:
            with open(base_image_path, 'rb') as f:
                base_image_data = f.read()
            logger.info(f"成功读取本地底图: {base_image_path}")
        except Exception as e:
            logger.error(f"无法读取本地基础自拍图片: {e}")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", f"错误: 无法读取底图文件 {base_image_path}", "TexasAIPics")
            return None

        # 🆕 优先使用AI预分析的角色检测结果
        if scene_analysis:
            detected_characters = scene_analysis.get("characters", [])
            # 自拍模式确保包含德克萨斯（预分析中应该已处理，这里做双重保险）
            if "德克萨斯" not in detected_characters:
                detected_characters.append("德克萨斯")
            logger.info(f"使用AI预分析检测到的自拍角色: {detected_characters}")
        else:
            # 回退到传统角色检测
            detected_characters = character_manager.detect_characters_in_text(experience_description)
            # 自拍模式确保包含德克萨斯
            if "德克萨斯" not in detected_characters:
                detected_characters.append("德克萨斯")
            logger.info(f"使用传统方法检测到的自拍角色: {detected_characters}")

        # 构建其他角色描述（排除德克萨斯）
        other_characters = [char for char in detected_characters if char != "德克萨斯"]
        other_characters_desc = ""
        if other_characters:
            character_traits = {
                "能天使": "活泼开朗的天使族女孩，红色头发，头顶有光圈，多个长三角形组成的光翼，充满活力",
                "可颂": "乐观开朗活泼的企鹅物流成员，橙色头发",
                "空": "活泼开朗的干员，黄色头发，明快的表情",
                "拉普兰德": "过于开朗特别活泼的狼族干员，白色头发，狼耳朵，古灵精怪略带病娇的笑容",
                "大帝": "喜欢说唱的帝企鹅，戴着墨镜和大金链子，西海岸嘻哈风格，企鹅形态而非人形"
            }
            char_descriptions = [f"{char}（{character_traits.get(char, '明日方舟角色')}）" for char in other_characters]
            other_characters_desc = f"场景中的其他角色：{', '.join(char_descriptions)}。"

        # 💃 服装建议：结合AI预分析、天气系统和性感元素
        clothing_parts = []
        clothing_source = "未知"  # 记录服装建议来源

        # 🎨 优先使用AI预分析的服装细节建议（包含性感元素）
        if scene_analysis and scene_analysis.get("clothing_details"):
            clothing_parts.append(f"💃 AI建议服装细节: {scene_analysis['clothing_details']}")
            clothing_source = "AI预分析"
        else:
            # 如果没有AI建议，使用更开放大胆的默认建议
            clothing_parts.append("服装风格：展现身材曲线的时尚服装，可以包含露肩、开叉、贴身剪裁等性感元素，体现自信魅力")
            clothing_source = "默认建议"

        # 添加天气情况描述（来自AI预分析）
        if scene_analysis and scene_analysis.get("weather_context"):
            clothing_parts.append(f"天气情况: {scene_analysis['weather_context']}")

        # 添加具体着装建议（来自天气系统）
        traditional_clothing = await self._get_weather_based_clothing_prompt()
        clothing_parts.append(traditional_clothing)

        clothing_parts.append("整体风格：时尚、性感、自信，同时保持角色的高冷气质")
        clothing_prompt = f"服装设计要求：{' '.join(clothing_parts)}"

        # 💃 构建增强的自拍提示词 - 版本B（平衡版）
        base_selfie_prompt = (
            f"请将这张人物图片作为基础，根据以下场景描述，生成一张高质量的自拍照片。"
            # f"艺术风格要求：保持明日方舟游戏的二次元动漫画风，避免过于写实的三次元风格，注重展现角色的性感魅力和身材曲线。"
            f"艺术风格要求：冷艳都市风格，简约高级，性感而不失高冷气质。"
            # 🎨 眼睛颜色限制已注释 - SeeDream已能根据训练数据正确生成德克萨斯的渐变色眼睛
            # f"主角特征要求：德克萨斯（黑色头发，兽耳），必须保持独特的渐变色眼眸，BOTH EYES must have gradient colors from blue (top) to orange (bottom)，两只眼睛都是从蓝色（上半部分）渐变到橙色（下半部分），这是区别于其他角色的重要特征。"
            f"主角特征要求：德克萨斯（黑色头发，兽耳），明日方舟角色。"
            f"人物的面部特征、黑色发型和整体风格需要与原图保持高度一致。"
            f"💃 身材展现：展现健康性感的身材，超级丰满的胸部（D罩杯），纤细但不过分的腰身、修长双腿。身材比例匀称健康，该有肉的地方丰满，该瘦的地方紧致，通过身材本身的优势体现魅力。"
        )

        # 💃 姿态建议：版本B（平衡版）
        if scene_analysis and scene_analysis.get("pose_suggestion"):
            pose_prompt = f"💃 姿态要求：{scene_analysis['pose_suggestion']}。姿态流畅优雅，既展现身材优势又保持高冷气场。"
        else:
            # 默认的平衡姿态建议
            pose_prompt = f"💃 姿态要求：采用自然而有魅力的自拍姿态，如：侧身展现曲线、挺胸展现身材、自然站立等。姿态流畅优雅，既展现身材优势又保持高冷气场。"

        # 🆕 使用AI预分析的表情建议 - 版本B（平衡版）
        if scene_analysis and scene_analysis.get("character_expressions"):
            # 查找德克萨斯的表情建议
            texas_expression = None
            for expr in scene_analysis["character_expressions"]:
                if expr.get("name") == "德克萨斯":
                    texas_expression = expr.get("expression")
                    break

            if texas_expression:
                expression_prompt = f"性格表情要求：德克萨斯{texas_expression}，保持高冷气质，眼神冷静自信中带一丝吸引力，表情淡然优雅。"
            else:
                expression_prompt = f"性格表情要求：德克萨斯保持高冷气质，眼神冷静自信中带一丝吸引力，表情淡然优雅，可以有微笑或平静的神态，展现冷艳美人的魅力。"
        else:
            expression_prompt = f"性格表情要求：德克萨斯保持高冷气质，眼神冷静自信中带一丝吸引力，表情淡然优雅，可以有微笑或平静的神态，展现冷艳美人的魅力。"

        # 🎨 构建增强的场景描述（包含新的视觉效果）
        if scene_analysis:
            scene_details = []
            if scene_analysis.get("location"):
                scene_details.append(f"地点: {scene_analysis['location']}")
            if scene_analysis.get("time_atmosphere"):
                scene_details.append(f"时间氛围: {scene_analysis['time_atmosphere']}")
            if scene_analysis.get("lighting_mood"):
                scene_details.append(f"光线效果: {scene_analysis['lighting_mood']}")
            if scene_analysis.get("color_tone"):
                scene_details.append(f"色彩基调: {scene_analysis['color_tone']}")
            if scene_analysis.get("emotional_state"):
                scene_details.append(f"情感氛围: {scene_analysis['emotional_state']}")

            # 🎨 新增：高级视觉效果
            if scene_analysis.get("visual_effects"):
                scene_details.append(f"✨ 特殊视觉效果: {scene_analysis['visual_effects']}")
            if scene_analysis.get("photographic_technique"):
                scene_details.append(f"📸 摄影技巧: {scene_analysis['photographic_technique']}")
            if scene_analysis.get("artistic_style"):
                scene_details.append(f"🎬 艺术风格: {scene_analysis['artistic_style']}")

            enhanced_scene_desc = " | ".join(scene_details) if scene_details else experience_description
        else:
            enhanced_scene_desc = experience_description

        # 组合完整的自拍提示词
        prompt = f"{base_selfie_prompt}{other_characters_desc}{expression_prompt}{pose_prompt}{clothing_prompt}构图要求：自拍视角，画面构图要突出人物魅力和身材曲线。场景融合：姿势、神态和背景需要完全融入新的场景，营造自然的自拍效果。场景描述: {enhanced_scene_desc}"

        # 自拍照：使用AI推荐的尺寸，默认9:16竖屏2K
        recommended_size = scene_analysis.get("recommended_image_size", "1080x1920") if scene_analysis else "1080x1920"

        # 📝 发送提示词日志到Mattermost（用于调试）
        try:
            await send_prompt_log_to_mattermost(
                prompt=prompt,
                image_type="自拍",
                scene_analysis=scene_analysis,
                detected_characters=detected_characters,
                clothing_source=clothing_source
            )
        except Exception as e:
            logger.warning(f"发送提示词日志失败（不影响图片生成）: {e}")

        # 🆕 使用新的 Provider 接口
        filepath = await self._generate_with_provider(prompt=prompt, images=[base_image_data], size=recommended_size)

        if filepath:
            await bark_notifier.send_notification("德克萨斯AI-生成自拍成功", f"图片已保存到 {filepath}", "TexasAIPics")
            return filepath
        else:
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", "错误: 图片生成失败", "TexasAIPics")
            return None

image_generation_service = ImageGenerationService()
