#!/usr/bin/env python3
"""
测试主动交互中的图片发送功能
"""

import asyncio
import json
import logging
import redis
import os
import sys
from datetime import datetime, timedelta

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.config import settings
from tasks.image_generation_tasks import prepare_images_for_proactive_interactions, cleanup_expired_proactive_images
from tasks.interaction_tasks import process_scheduled_interactions

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)

PROACTIVE_IMAGES_KEY = "proactive_interaction_images"


def create_test_interaction_event():
    """创建测试用的主动交互事件"""
    today = datetime.now().strftime('%Y-%m-%d')
    test_event = {
        "id": "test_experience_001",
        "interaction_content": "今天天气真不错，在校园里散步时看到樱花开得很美，心情变好了很多",
        "start_time": "09:00",
        "end_time": "10:00",
        "timestamp": datetime.now().timestamp()
    }
    
    # 将测试事件添加到 Redis
    today_key = f"interaction_needed:{today}"
    # 设置一个较早的时间戳，确保事件会被处理
    past_timestamp = (datetime.now() - timedelta(minutes=5)).timestamp()
    
    redis_client.zadd(today_key, {json.dumps(test_event): past_timestamp})
    logger.info(f"✅ 已创建测试交互事件: {test_event['id']}")
    return test_event


def create_test_image_mapping(experience_id: str, image_path: str):
    """创建测试用的图片映射"""
    redis_client.hset(PROACTIVE_IMAGES_KEY, experience_id, image_path)
    logger.info(f"✅ 已创建图片映射: {experience_id} -> {image_path}")


def cleanup_test_data():
    """清理测试数据"""
    today = datetime.now().strftime('%Y-%m-%d')
    today_key = f"interaction_needed:{today}"
    interacted_key = f"interacted_schedule_items:{today}"
    
    # 清理测试事件
    redis_client.delete(today_key)
    redis_client.delete(interacted_key)
    
    # 清理测试图片映射
    redis_client.hdel(PROACTIVE_IMAGES_KEY, "test_experience_001")
    
    logger.info("🧹 已清理测试数据")


async def test_image_generation_and_interaction():
    """测试图片生成和主动交互的完整流程"""
    logger.info("🚀 开始测试主动交互图片发送功能")
    
    try:
        # 1. 创建测试交互事件
        test_event = create_test_interaction_event()
        
        # 2. 测试图片预生成任务
        logger.info("📸 测试图片预生成任务...")
        prepare_images_for_proactive_interactions()
        
        # 检查是否生成了图片映射
        image_path = redis_client.hget(PROACTIVE_IMAGES_KEY, test_event["id"])
        if image_path:
            logger.info(f"✅ 图片预生成成功: {image_path}")
            
            # 检查文件是否真的存在
            if os.path.exists(image_path):
                logger.info(f"✅ 图片文件确实存在: {image_path}")
            else:
                logger.warning(f"⚠️ 图片文件不存在: {image_path}")
                # 创建一个虚拟的测试图片路径用于测试逻辑
                test_image_path = "/app/generated_content/images/test_image.png"
                create_test_image_mapping(test_event["id"], test_image_path)
        else:
            logger.info("📷 未触发图片生成（概率机制），创建测试图片映射")
            test_image_path = "/app/generated_content/images/test_image.png"
            create_test_image_mapping(test_event["id"], test_image_path)
        
        # 3. 测试主动交互处理任务
        logger.info("💬 测试主动交互处理任务...")
        
        # 注意: 这里需要在有Mattermost连接的环境中测试
        # 在测试环境中，我们只能验证逻辑，不能真正发送消息
        try:
            process_scheduled_interactions()
            logger.info("✅ 主动交互处理任务执行完成")
        except Exception as e:
            logger.error(f"❌ 主动交互处理任务执行失败（可能是因为没有Mattermost连接）: {e}")
        
        # 4. 测试清理任务
        logger.info("🧹 测试图片映射清理任务...")
        cleanup_expired_proactive_images()
        
        # 5. 检查最终状态
        remaining_mapping = redis_client.hget(PROACTIVE_IMAGES_KEY, test_event["id"])
        if remaining_mapping:
            logger.info(f"📋 图片映射仍然存在: {remaining_mapping}")
        else:
            logger.info("✅ 图片映射已被清理")
        
        logger.info("🎉 测试完成！")
        
    except Exception as e:
        logger.error(f"❌ 测试过程中发生错误: {e}")
    
    finally:
        # 清理测试数据
        cleanup_test_data()


def test_redis_connectivity():
    """测试Redis连接"""
    try:
        redis_client.ping()
        logger.info("✅ Redis连接正常")
        return True
    except Exception as e:
        logger.error(f"❌ Redis连接失败: {e}")
        return False


def main():
    """主函数"""
    logger.info("🔧 主动交互图片发送功能测试脚本")
    
    # 检查Redis连接
    if not test_redis_connectivity():
        return
    
    # 运行测试
    asyncio.run(test_image_generation_and_interaction())


if __name__ == "__main__":
    main()