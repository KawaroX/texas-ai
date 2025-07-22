import asyncio
import logging
import redis
import json
import datetime
import pytz
from app.config import settings
from utils.postgres_service import insert_messages

logging.basicConfig(level=logging.INFO)


class RedisCleanupService:
    """Redis缓存清理服务，负责定期清理过期的聊天记录并归档到PostgreSQL"""

    def __init__(self):
        self.redis_client = redis.StrictRedis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        self.cleanup_interval = 2 * 60 * 60  # 2小时运行一次清理
        self.retention_seconds = 6 * 60 * 60  # 6小时保留时间

    async def start_cleanup_scheduler(self):
        """启动定期清理任务"""
        logging.info("🔄 启动Redis缓存清理服务...")
        while True:
            try:
                await self.cleanup_expired_messages()
                await asyncio.sleep(self.cleanup_interval)
            except Exception as e:
                logging.error(f"❌ Redis清理服务出错: {e}")
                await asyncio.sleep(60)  # 出错时等待1分钟后重试

    async def cleanup_expired_messages(self):
        """清理所有频道的过期消息"""
        try:
            # 获取所有聊天记录的Redis键
            channel_keys = self.redis_client.keys("channel_memory:*")

            if not channel_keys:
                logging.info("🔍 没有找到需要清理的聊天记录")
                return

            logging.info(f"🔍 开始清理 {len(channel_keys)} 个频道的过期消息...")

            total_archived = 0
            total_deleted = 0

            for channel_key in channel_keys:
                channel_id = channel_key.split(":")[1]
                archived, deleted = await self.cleanup_channel_messages(channel_id)
                total_archived += archived
                total_deleted += deleted

            if total_archived > 0 or total_deleted > 0:
                logging.info(
                    f"✅ 清理完成: 归档 {total_archived} 条消息, 删除 {total_deleted} 条过期消息"
                )
            else:
                logging.info("✅ 清理完成: 没有过期消息需要处理")

        except Exception as e:
            logging.error(f"❌ 清理过期消息时出错: {e}")

    async def cleanup_channel_messages(self, channel_id: str):
        """清理指定频道的过期消息"""
        try:
            # 使用东八区时间
            tz = pytz.timezone("Asia/Shanghai")
            now_timestamp = datetime.datetime.now(tz).timestamp()
            six_hours_ago_timestamp = now_timestamp - self.retention_seconds

            # 从Redis中删除已归档的消息
            deleted_count = self.redis_client.zremrangebyscore(
                f"channel_memory:{channel_id}", 0, six_hours_ago_timestamp
            )

            if deleted_count > 0:
                logging.info(
                    f"🧹 频道 {channel_id}: 从Redis删除 {deleted_count} 条过期消息"
                )

            return 0, deleted_count

        except Exception as e:
            logging.error(f"❌ 清理频道 {channel_id} 消息时出错: {e}")
            return 0, 0

    async def cleanup_abandoned_buffers(self):
        """清理被遗弃的消息缓冲区（可选功能）"""
        try:
            # 获取所有消息缓冲区的键
            buffer_keys = self.redis_client.keys("channel_buffer:*")

            if not buffer_keys:
                return

            logging.info(f"🧹 检查 {len(buffer_keys)} 个消息缓冲区...")

            cleaned_count = 0
            for buffer_key in buffer_keys:
                # 检查缓冲区是否超过10分钟没有活动
                # 这里可以通过设置TTL或者其他方式来判断
                buffer_length = self.redis_client.llen(buffer_key)
                if buffer_length > 0:
                    # 可以设置缓冲区的TTL，超时自动删除
                    # 或者根据业务逻辑判断是否需要清理
                    pass

            if cleaned_count > 0:
                logging.info(f"🧹 清理了 {cleaned_count} 个被遗弃的消息缓冲区")

        except Exception as e:
            logging.error(f"❌ 清理被遗弃缓冲区时出错: {e}")


# 单例实例
cleanup_service = RedisCleanupService()


async def start_redis_cleanup():
    """启动Redis清理服务的入口函数"""
    await cleanup_service.start_cleanup_scheduler()


if __name__ == "__main__":
    asyncio.run(start_redis_cleanup())
