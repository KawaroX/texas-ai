"""
即时图片生成协调器
整合上下文提取、场景分析、图片生成的完整流程
"""

import asyncio
import uuid
import random
from datetime import datetime
from typing import Optional, Dict
from utils.logging_config import get_logger

logger = get_logger(__name__)


class InstantImageGenerator:
    """即时图片生成协调器"""

    def __init__(self):
        from services.recent_context_extractor import recent_context_extractor
        from services.scene_pre_analyzer import analyze_scene
        from services.image_generation_service import image_generation_service

        self.context_extractor = recent_context_extractor
        self.scene_analyzer = analyze_scene
        self.image_service = image_generation_service

        # 并发控制（同一频道同时只能生成1张）
        self._generating_channels = set()

    async def generate_instant_image(
        self,
        channel_id: str,
        user_id: str,
        image_type: Optional[str] = None,  # "selfie"|"scene"|None(自动判断)
        context_window_minutes: int = 3,
        max_messages: int = 25,
        image_description: Optional[str] = None
    ) -> Dict:
        """
        生成即时图片的完整流程

        Args:
            channel_id: 频道ID
            user_id: 用户ID
            image_type: 强制指定图片类型
            context_window_minutes: 上下文时间窗口
            max_messages: 最大消息数
            image_description: (可选) AI直接生成的图片描述，如果提供则跳过场景分析

        Returns:
            {
                "success": bool,
                "image_path": str or None,
                "error": str or None,
                "generation_time": float
            }
        """
        start_time = datetime.now()
        logger.info(f"[instant_image] 开始生成即时图片: channel={channel_id}")

        # 1. 并发控制
        if channel_id in self._generating_channels:
            logger.warning(f"[instant_image] 频道正在生成图片，跳过: {channel_id}")
            return {
                "success": False,
                "error": "正在生成图片，请稍候...",
                "generation_time": 0
            }

        self._generating_channels.add(channel_id)

        try:
            # 2. 提取最近对话上下文
            recent_messages = self.context_extractor.extract_recent_context(
                channel_id=channel_id,
                window_minutes=context_window_minutes,
                max_messages=max_messages,
                include_assistant=True
            )

            # 如果没有image_description，则必须要有足够的上下文
            if not image_description and (not recent_messages or len(recent_messages) < 2):
                logger.warning("[instant_image] 未找到足够的最近对话，无法生成图片")
                return {
                    "success": False,
                    "error": "没有找到足够的对话内容来生成图片",
                    "generation_time": 0
                }

            # 3. 构建场景数据
            if image_description:
                scene_content = image_description
                logger.info(f"[instant_image] 使用AI直接生成的图片描述，跳过上下文拼接")
            else:
                # 格式化对话为场景描述
                scene_content = self.context_extractor.format_context_for_scene(recent_messages)

            scene_data = {
                "id": str(uuid.uuid4()),
                "content": scene_content,
                "timestamp": datetime.now().isoformat(),
                "channel_id": channel_id,
                "source": "instant_generation"
            }

            # 4. 判断图片类型（selfie vs scene）
            if image_description and ("自拍" in image_description or "selfie" in image_description.lower()):
                is_selfie = True
                logger.info(f"[instant_image] 从描述中检测到自拍类型")
            else:
                is_selfie = self._determine_image_type(image_type, recent_messages or [])

            logger.info(f"[instant_image] 图片类型: {'自拍' if is_selfie else '场景'}")

            # 5. 场景分析
            if image_description:
                # 如果有直接描述，跳过昂贵的AI预分析
                logger.info("[instant_image] 使用AI直接描述，跳过ScenePreAnalyzer")
                # 构造基础的分析结果
                analysis_result = {
                    "characters": [],  # 让image_service自己去检测或回退
                    "recommended_image_size": "1080x1920" if is_selfie else "3840x2160",
                    # 标记这是直接描述，避免后续逻辑过度处理
                    "is_direct_description": True
                }
            else:
                # AI场景预分析（复用现有逻辑）
                logger.debug("[instant_image] 开始场景预分析")
                analysis_result = await self.scene_analyzer(
                    scene_data=scene_data,
                    is_selfie=is_selfie
                )

                if not analysis_result:
                    logger.error("[instant_image] 场景预分析失败")
                    return {
                        "success": False,
                        "error": "场景分析失败",
                        "generation_time": (datetime.now() - start_time).total_seconds()
                    }

                logger.debug(f"[instant_image] 场景分析完成: {len(analysis_result.get('characters', []))}个角色")

            # 6. 生成图片（复用现有逻辑）
            # 获取场景描述文本
            experience_description = scene_data.get('content', '')
            logger.debug("[instant_image] 开始生成图片")

            if is_selfie:
                # 自拍模式
                image_path = await self.image_service.generate_selfie(
                    experience_description=experience_description,
                    scene_analysis=analysis_result
                )
            else:
                # 场景模式
                image_path = await self.image_service.generate_image_from_prompt(
                    experience_description=experience_description,
                    scene_analysis=analysis_result
                )

            if not image_path:
                logger.error("[instant_image] 图片生成失败")
                return {
                    "success": False,
                    "error": "图片生成失败",
                    "generation_time": (datetime.now() - start_time).total_seconds()
                }

            logger.info(f"[instant_image] 图片生成成功: {image_path}")

            # 7. 返回结果（发送由调用方处理）
            generation_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"[instant_image] 完成，耗时: {generation_time:.2f}秒")

            return {
                "success": True,
                "image_path": image_path,
                "is_selfie": is_selfie,
                "error": None,
                "generation_time": generation_time
            }

        except asyncio.TimeoutError:
            logger.error("[instant_image] 生成超时")
            return {
                "success": False,
                "error": "生成超时，请稍后重试",
                "generation_time": (datetime.now() - start_time).total_seconds()
            }

        except Exception as e:
            logger.error(f"[instant_image] 生成失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"生成失败: {str(e)}",
                "generation_time": (datetime.now() - start_time).total_seconds()
            }

        finally:
            # 移除并发标记
            self._generating_channels.discard(channel_id)

    def _build_scene_data(self, messages: list, channel_id: str) -> Dict:
        """构建场景数据（模拟微观经历的格式）"""
        # 格式化对话为场景描述
        scene_content = self.context_extractor.format_context_for_scene(messages)

        scene_data = {
            "id": str(uuid.uuid4()),
            "content": scene_content,
            "timestamp": datetime.now().isoformat(),
            "channel_id": channel_id,
            "source": "instant_generation"
        }

        return scene_data

    def _determine_image_type(
        self,
        forced_type: Optional[str],
        messages: list
    ) -> bool:
        """
        判断图片类型（selfie vs scene）

        Args:
            forced_type: 强制指定的类型
            messages: 最近消息

        Returns:
            True=selfie, False=scene
        """
        # 如果强制指定，直接返回
        if forced_type == "selfie":
            return True
        elif forced_type == "scene":
            return False

        # 否则根据对话内容判断
        # 简单规则：如果提到"你"、"自拍"、"看看你"，则为selfie
        combined_text = " ".join([msg.get('content', '') for msg in messages[-5:]])
        combined_text = combined_text.lower()

        selfie_keywords = ["你", "自拍", "看看你", "你在", "你的", "看你", "你现在"]
        scene_keywords = ["风景", "景色", "这里", "那里", "环境", "周围", "外面"]

        selfie_score = sum(1 for kw in selfie_keywords if kw in combined_text)
        scene_score = sum(1 for kw in scene_keywords if kw in combined_text)

        logger.debug(f"[instant_image] 图片类型判断: selfie_score={selfie_score}, scene_score={scene_score}")

        # 默认优先selfie（与现有逻辑一致：40%概率）
        if selfie_score > scene_score:
            return True
        elif scene_score > selfie_score:
            return False
        else:
            # 平局，随机（40%概率selfie）
            return random.random() < 0.4


# 全局实例
instant_image_generator = InstantImageGenerator()
