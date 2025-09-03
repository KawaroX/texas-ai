
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

logger = logging.getLogger(__name__)

# 初始化 Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)

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


async def _do_image_generation():
    """执行具体的图片生成逻辑"""
    today_key = f"interaction_needed:{datetime.now().strftime('%Y-%m-%d')}"
    if not redis_client.exists(today_key):
        logger.warning(f"⚠️ Redis 中不存在 key: {today_key}，无法为主动交互生成图片。")
        return

    # 获取所有事件，这里不关心分数，因为是提前准备
    events = redis_client.zrange(today_key, 0, -1)
    if not events:
        logger.info("[image_gen] 今天没有需要处理的主动交互事件。")
        return

    logger.info(f"[image_gen] 发现 {len(events)} 个潜在的交互事件需要处理图片生成。")

    for event_json_str in events:
        try:
            event_data = json.loads(event_json_str)
            experience_id = event_data.get("id")
            interaction_content = event_data.get("interaction_content")

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
                
                for attempt in range(max_retries + 1):
                    try:
                        if attempt > 0:
                            logger.info(f"[image_gen] 🔄 事件 {experience_id} 重试第 {attempt} 次图片生成")
                        
                        if is_selfie:
                            if attempt == 0:
                                logger.info(f"[image_gen] 📸 尝试为事件 {experience_id} 生成自拍。")
                            # 为自拍生成设置更长的超时时间（8分钟）
                            image_path = await asyncio.wait_for(
                                image_generation_service.generate_selfie(interaction_content),
                                timeout=480.0
                            )
                        else:
                            if attempt == 0:
                                logger.info(f"[image_gen] 🎨 尝试为事件 {experience_id} 生成场景图片。")
                            # 为场景图设置超时时间（5分钟）
                            image_path = await asyncio.wait_for(
                                image_generation_service.generate_image_from_prompt(interaction_content),
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
                    # 检测角色用于监控
                    from services.character_manager import character_manager
                    detected_chars = character_manager.detect_characters_in_text(interaction_content)
                    
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
                        prompt_length=len(interaction_content),
                        detected_characters=detected_chars
                    )
                except Exception as monitor_error:
                    logger.warning(f"⚠️ 记录监控数据失败（不影响主流程）: {monitor_error}")
                
                if image_path:
                    # 将 experience_id 和 image_path 存入 Redis Hash
                    redis_client.hset(PROACTIVE_IMAGES_KEY, experience_id, image_path)
                    logger.info(f"[image_gen] ✅ 成功关联图片 {image_path} 到事件 {experience_id}")
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
