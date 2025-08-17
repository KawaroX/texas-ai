
import logging
import random
import json
import redis
from datetime import datetime
from celery import shared_task
from app.config import settings
from services.image_generation_service import image_generation_service

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

    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

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
                if is_selfie:
                    logger.info(f"[image_gen] 📸 尝试为事件 {experience_id} 生成自拍。")
                    image_path = loop.run_until_complete(
                        image_generation_service.generate_selfie(interaction_content)
                    )
                else:
                    logger.info(f"[image_gen] 🎨 尝试为事件 {experience_id} 生成场景图片。")
                    image_path = loop.run_until_complete(
                        image_generation_service.generate_image_from_prompt(interaction_content)
                    )
                
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
