
import logging
import random
import json
import redis
import os
import asyncio
from datetime import datetime
from celery import shared_task
from app.config import settings
from services.image_generation_service import image_generation_service
from services.image_generation_monitor import image_generation_monitor

class ProcessTracker:
    """
    🚀 图片生成过程追踪器
    用于收集增强功能的详细使用情况，失败不影响主流程
    """
    def __init__(self):
        self.tracking_key_prefix = "image_generation_process_tracking"
        
    def track_event(self, event_type: str, target_date: str = None):
        """追踪单个事件（失败不影响主流程）"""
        try:
            if target_date is None:
                target_date = datetime.now().strftime('%Y-%m-%d')
            
            tracking_key = f"{self.tracking_key_prefix}:{target_date}"
            redis_client.hincrby(tracking_key, event_type, 1)
            redis_client.expire(tracking_key, 86400 * 3)  # 3天过期
            
        except Exception as e:
            # 追踪失败不记录错误日志，避免干扰主流程
            pass
    
    def track_data_source_usage(self, used_enhanced: bool, target_date: str = None):
        """追踪数据源使用情况"""
        if used_enhanced:
            self.track_event("enhanced_data_used", target_date)
        else:
            self.track_event("fallback_to_original", target_date)
    
    def track_character_detection(self, used_companions: bool, target_date: str = None):
        """追踪角色检测方式"""
        if used_companions:
            self.track_event("companions_detection", target_date)
        else:
            self.track_event("string_detection", target_date)
    
    def track_prompt_enhancement(self, success: bool, target_date: str = None):
        """追踪提示词增强结果"""
        if success:
            self.track_event("prompt_enhancement_success", target_date)
        else:
            self.track_event("prompt_enhancement_failed", target_date)

# 全局追踪器实例
process_tracker = ProcessTracker()

logger = logging.getLogger(__name__)

# 初始化 Redis 客户端
from utils.redis_manager import get_redis_client
redis_client = get_redis_client()

# 新的 Redis Hash Key，用于存储 interaction_id -> image_path 的映射
PROACTIVE_IMAGES_KEY = "proactive_interaction_images"

@shared_task
def prepare_images_for_proactive_interactions():
    """
    Celery 任务：为主动交互预生成图片。
    遍历当天的 interaction_needed 事件，根据概率生成图片并存储映射关系。
    """
    logger.info("[image_gen] 启动主动交互图片预生成任务")
    
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # 运行异步逻辑
    return loop.run_until_complete(_async_prepare_images())


async def _async_prepare_images():
    """异步执行图片预生成逻辑"""
    try:
        # 整体任务超时45分钟（从30分钟增加）
        await asyncio.wait_for(_do_image_generation(), timeout=2700.0)
    except asyncio.TimeoutError:
        logger.error("⏱️ 整体图片生成任务超时（45分钟），部分图片可能未生成完成")
    except Exception as e:
        logger.error(f"❌ 图片生成任务发生未知错误: {e}")


async def _try_read_enhanced_data():
    """尝试读取增强交互数据，失败时返回None"""
    try:
        today_key = f"interaction_needed_enhanced:{datetime.now().strftime('%Y-%m-%d')}"
        if redis_client.exists(today_key):
            events = redis_client.zrange(today_key, 0, -1)
            if events:
                logger.info(f"[image_gen] 🆕 读取到增强数据: {len(events)} 条")
                return events, today_key, True  # (events, key, is_enhanced)
        logger.debug(f"[image_gen] 增强数据不存在，将使用原始数据")
        return None, None, False
    except Exception as e:
        logger.warning(f"[image_gen] 读取增强数据失败，将使用原始数据: {e}")
        return None, None, False


def _build_enhanced_content(interaction_content: str, enhanced_info: dict, generation_type: str) -> str:
    """
    🆕 构建增强的内容描述，失败时回退到原始内容
    """
    try:
        if not enhanced_info:
            return interaction_content
            
        schedule_context = enhanced_info.get("schedule_context", {})
        emotions = enhanced_info.get("emotions", "")
        thoughts = enhanced_info.get("thoughts", "")
        time_period = enhanced_info.get("time_period", "")
        
        # 构建增强信息组件
        enhanced_parts = []
        
        # 1. 基础内容
        enhanced_parts.append(f"经历内容: {interaction_content}")
        
        # 2. 地点信息
        location = schedule_context.get("location")
        if location:
            enhanced_parts.append(f"地点: {location}")
        
        # 3. 时间背景
        time_context_map = {
            "early_morning": "清晨时分，晨光初现",
            "morning": "上午时光，阳光明媚", 
            "noon": "正午时分，阳光正好",
            "afternoon": "下午时光，光线柔和",
            "evening": "傍晚时分，夕阳西下",
            "night": "夜晚时分，灯火阑珊"
        }
        if time_period in time_context_map:
            enhanced_parts.append(f"时间氛围: {time_context_map[time_period]}")
        
        # 4. 情感状态（主要用于自拍）
        if emotions and generation_type == "selfie":
            enhanced_parts.append(f"情感状态: {emotions}")
        
        # 5. 内心想法（用于增加深度）
        if thoughts and len(thoughts) < 100:  # 避免提示词过长
            enhanced_parts.append(f"内心感受: {thoughts}")
            
        # 6. 活动背景
        activity_title = schedule_context.get("title")
        if activity_title:
            enhanced_parts.append(f"活动背景: {activity_title}")
        
        enhanced_content = " | ".join(enhanced_parts)
        logger.debug(f"[image_gen] ✨ 构建增强描述成功，长度: {len(enhanced_content)}")
        return enhanced_content
        
    except Exception as e:
        logger.warning(f"[image_gen] ⚠️ 构建增强描述失败，使用原始内容: {e}")
        return interaction_content


async def _do_image_generation():
    """执行具体的图片生成逻辑"""
    # 🆕 优先尝试读取增强数据
    enhanced_events, enhanced_key, using_enhanced = await _try_read_enhanced_data()
    
    if using_enhanced and enhanced_events:
        # 使用增强数据
        events = enhanced_events
        events_key = enhanced_key
        logger.info(f"[image_gen] ✨ 使用增强数据进行图片生成")
        # 🚀 追踪：使用增强数据
        process_tracker.track_data_source_usage(used_enhanced=True)
    else:
        # 回退到原始数据（保持原有逻辑100%不变）
        today_key = f"interaction_needed:{datetime.now().strftime('%Y-%m-%d')}"
        if not redis_client.exists(today_key):
            logger.warning(f"⚠️ Redis 中不存在 key: {today_key}，无法为主动交互生成图片。")
            return
        events = redis_client.zrange(today_key, 0, -1)
        events_key = today_key
        using_enhanced = False
        logger.info(f"[image_gen] 📦 使用原始数据进行图片生成")
        # 🚀 追踪：回退到原始数据
        process_tracker.track_data_source_usage(used_enhanced=False)

    if not events:
        logger.info("[image_gen] 今天没有需要处理的主动交互事件。")
        return

    logger.info(f"[image_gen] 发现 {len(events)} 个潜在的交互事件需要处理图片生成。")

    for event_json_str in events:
        try:
            event_data = json.loads(event_json_str)
            
            # 🆕 根据数据格式提取信息（向后兼容）
            if using_enhanced:
                # 增强数据格式
                experience_id = event_data.get("id")
                interaction_content = event_data.get("interaction_content")
                enhanced_info = {
                    "emotions": event_data.get("emotions"),
                    "thoughts": event_data.get("thoughts"),
                    "schedule_context": event_data.get("schedule_context", {}),
                    "major_event_context": event_data.get("major_event_context"),
                    "time_period": event_data.get("time_period"),
                }
            else:
                # 原始数据格式（保持100%兼容）
                experience_id = event_data.get("id")
                interaction_content = event_data.get("interaction_content")
                enhanced_info = None

            if not experience_id or not interaction_content:
                logger.warning(f"⚠️ 事件数据缺少ID或内容，跳过: {event_json_str[:100]}...")
                continue

            # 检查是否已经为这个经历生成过图片
            if redis_client.hexists(PROACTIVE_IMAGES_KEY, experience_id):
                logger.debug(f"[image_gen] 事件 {experience_id} 已存在关联图片，跳过。")
                continue

            # 30% 的概率生成图片
            if random.random() < 0.3:
                logger.info(f"[image_gen] 🎲 事件 {experience_id} 触发图片生成。")
                
                # 在这30%中，有40%的概率是自拍
                is_selfie = random.random() < 0.4
                
                image_path = None
                generation_start_time = datetime.now()
                generation_type = "selfie" if is_selfie else "scene"
                error_msg = None
                max_retries = 2  # 最多重试2次（总共3次尝试）
                
                # 🆕 构建增强内容描述（失败时使用原始内容）
                enhanced_content = _build_enhanced_content(
                    interaction_content, 
                    enhanced_info, 
                    "selfie" if is_selfie else "scene"
                )
                
                # 🚀 追踪：提示词增强结果
                enhancement_successful = (enhanced_content != interaction_content) if enhanced_info else False
                process_tracker.track_prompt_enhancement(success=enhancement_successful)
                
                for attempt in range(max_retries + 1):
                    try:
                        if attempt > 0:
                            logger.info(f"[image_gen] 🔄 事件 {experience_id} 重试第 {attempt} 次图片生成")
                        
                        if is_selfie:
                            if attempt == 0:
                                logger.info(f"[image_gen] 📸 尝试为事件 {experience_id} 生成自拍。")
                            # 为自拍生成设置更长的超时时间（8分钟）
                            image_path = await asyncio.wait_for(
                                image_generation_service.generate_selfie(enhanced_content),
                                timeout=480.0
                            )
                        else:
                            if attempt == 0:
                                logger.info(f"[image_gen] 🎨 尝试为事件 {experience_id} 生成场景图片。")
                            # 为场景图设置超时时间（5分钟）
                            image_path = await asyncio.wait_for(
                                image_generation_service.generate_image_from_prompt(enhanced_content),
                                timeout=300.0
                            )
                        
                        # 成功生成，跳出重试循环
                        if image_path:
                            if attempt > 0:
                                logger.info(f"[image_gen] ✅ 事件 {experience_id} 重试第 {attempt} 次成功")
                            break
                            
                    except asyncio.TimeoutError:
                        error_msg = f"Generation timeout (attempt {attempt + 1}/{max_retries + 1})"
                        logger.error(f"⏱️ 事件 {experience_id} 图片生成超时（第 {attempt + 1} 次尝试）")
                        if attempt == max_retries:
                            image_path = None
                    except Exception as e:
                        error_msg = f"{str(e)} (attempt {attempt + 1}/{max_retries + 1})"
                        logger.error(f"❌ 事件 {experience_id} 图片生成失败（第 {attempt + 1} 次尝试）: {e}")
                        if attempt == max_retries:
                            image_path = None
                
                # 记录监控数据（失败不影响主流程）
                try:
                    # 🆕 双轨制角色检测：优先使用增强数据，回退到字符串匹配
                    detected_chars = []
                    used_companions_detection = False
                    
                    if enhanced_info and enhanced_info.get("schedule_context"):
                        companions = enhanced_info["schedule_context"].get("companions", [])
                        if companions:
                            detected_chars = companions
                            used_companions_detection = True
                            logger.debug(f"[image_gen] ✨ 使用增强数据检测角色: {detected_chars}")
                    
                    # 如果增强检测无结果，回退到原有的字符串匹配
                    if not detected_chars:
                        from services.character_manager import character_manager
                        detected_chars = character_manager.detect_characters_in_text(interaction_content)
                        used_companions_detection = False
                        logger.debug(f"[image_gen] 📦 使用字符串匹配检测角色: {detected_chars}")
                    
                    # 🚀 追踪：角色检测方式
                    process_tracker.track_character_detection(used_companions=used_companions_detection)
                    
                    # 如果检测到角色，更新生成类型
                    if detected_chars and not is_selfie:
                        generation_type = "scene_with_characters"
                    
                    image_generation_monitor.record_generation_attempt(
                        experience_id=experience_id,
                        generation_type=generation_type,
                        start_time=generation_start_time,
                        success=image_path is not None,
                        image_path=image_path,
                        error=error_msg,
                        prompt_length=len(enhanced_content),  # 🆕 使用增强内容的长度
                        detected_characters=detected_chars
                    )
                except Exception as monitor_error:
                    logger.warning(f"⚠️ 记录监控数据失败（不影响主流程）: {monitor_error}")
                
                if image_path:
                    # 将 experience_id 和 image_path 存入 Redis Hash
                    redis_client.hset(PROACTIVE_IMAGES_KEY, experience_id, image_path)
                    logger.info(f"[image_gen] ✅ 成功关联图片 {image_path} 到事件 {experience_id}")
                    
                    # 🆕 尝试分析图片内容（失败不影响主流程）
                    try:
                        from services.image_content_analyzer import analyze_generated_image
                        
                        logger.info(f"[image_gen] 🔍 开始分析图片内容: {os.path.basename(image_path)}")
                        description = await analyze_generated_image(image_path)
                        
                        if description:
                            logger.info(f"[image_gen] ✅ 图片内容分析成功: {description[:50]}...")
                        else:
                            logger.info("[image_gen] 📝 图片内容分析未返回结果，将使用默认占位符")
                            
                    except Exception as analyzer_error:
                        logger.warning(f"⚠️ [image_gen] 图片内容分析失败（不影响主流程）: {analyzer_error}")
                        
                else:
                    logger.error(f"❌ 未能为事件 {experience_id} 生成图片。")
            else:
                logger.debug(f"[image_gen] 🎲 事件 {experience_id} 未触发图片生成（概率未命中）。")

        except json.JSONDecodeError:
            logger.error(f"❌ 解析事件JSON失败: {event_json_str[:100]}...")
        except Exception as e:
            logger.error(f"❌ 处理事件 {event_json_str[:100]}... 时发生未知错误: {e}")

    logger.info("[image_gen] 主动交互图片预生成任务完成。")
    
    # 生成今日汇总报告（失败不影响主流程）
    try:
        summary = image_generation_monitor.generate_daily_summary()
        logger.info(f"📊 今日图片生成汇总: 尝试 {summary['total_attempts']} 次，成功 {summary['successful_generations']} 次，成功率 {summary['success_rate']:.2%}")
    except Exception as summary_error:
        logger.warning(f"⚠️ 生成每日汇总失败（不影响主流程）: {summary_error}")


@shared_task
def cleanup_expired_proactive_images():
    """
    Celery 任务：清理过期的主动交互图片映射。
    仅清理Redis中文件不存在的映射关系，图片文件永久保留。
    """
    logger.info("[image_gen] 启动主动交互图片映射清理任务（图片文件永久保留）")
    
    try:
        # 获取所有图片映射
        all_mappings = redis_client.hgetall(PROACTIVE_IMAGES_KEY)
        if not all_mappings:
            logger.info("[image_gen] 没有需要清理的图片映射")
            return
        
        cleaned_count = 0
        preserved_count = 0
        
        for experience_id, image_path in all_mappings.items():
            if not image_path:
                # 清理空路径的映射
                redis_client.hdel(PROACTIVE_IMAGES_KEY, experience_id)
                cleaned_count += 1
                logger.debug(f"[image_gen] 清理空路径映射: {experience_id}")
            elif not os.path.exists(image_path):
                # 文件不存在但不删除映射，只记录日志
                logger.debug(f"[image_gen] 文件不存在但保留映射: {experience_id} -> {image_path}")
                preserved_count += 1
            else:
                # 文件存在，保留映射
                preserved_count += 1
        
        logger.info(f"[image_gen] 图片映射清理完成 - 清理: {cleaned_count}, 保留: {preserved_count}")
        
    except Exception as e:
        logger.error(f"❌ 清理主动交互图片映射时发生错误: {e}")
