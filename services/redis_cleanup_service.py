import asyncio
from utils.logging_config import get_logger

logger = get_logger(__name__)
import redis
import json
import datetime
import pytz
from app.config import settings

# 日志配置由应用主入口统一设置


class RedisCleanupService:
    """Redis缓存清理服务，负责定期清理过期的聊天记录并归档到PostgreSQL"""

    def __init__(self):
        from utils.redis_manager import get_redis_client
        self.redis_client = get_redis_client()
        self.cleanup_interval = 2 * 60 * 60  # 2小时运行一次清理
        self.retention_seconds = 48 * 60 * 60  # 48 小时保留时间
        self.min_keep_count = 1000  # 无论过期多久都保留的最近记录数量

    async def start_cleanup_scheduler(self):
        """启动定期清理任务"""
        logger.info("[redis_cleanup] 启动 Redis 缓存清理服务")
        while True:
            try:
                await self.cleanup_expired_messages()
                await asyncio.sleep(self.cleanup_interval)
            except Exception as e:
                logger.error(f"Redis清理服务出错: {e}")
                await asyncio.sleep(60)  # 出错时等待1分钟后重试

    async def cleanup_expired_messages(self):
        """清理所有频道的过期消息"""
        try:
            # 获取所有聊天记录的Redis键
            channel_keys = self.redis_client.keys("channel_memory:*")

            if not channel_keys:
                logger.debug("[redis_cleanup] 没有找到需要清理的聊天记录")
                return

            logger.info(
                f"[redis_cleanup] 开始清理 {len(channel_keys)} 个频道的过期消息"
            )

            total_archived = 0
            total_deleted = 0

            for channel_key in channel_keys:
                channel_id = channel_key.split(":")[1]
                archived, deleted = await self.cleanup_channel_messages(channel_id)
                total_archived += archived
                total_deleted += deleted

            if total_archived > 0 or total_deleted > 0:
                logger.info(
                    f"[redis_cleanup] 清理完成: 归档 {total_archived} 条, 删除 {total_deleted} 条"
                )
            else:
                logger.info("[redis_cleanup] 清理完成: 没有过期消息")

        except Exception as e:
            logger.error(f"清理过期消息时出错: {e}")

    async def cleanup_channel_messages(self, channel_id: str):
        """清理指定频道的过期消息，但始终保留最近的 1000 条记录"""
        try:
            # 使用东八区时间
            tz = pytz.timezone("Asia/Shanghai")
            now_timestamp = datetime.datetime.now(tz).timestamp()
            retention_cutoff_timestamp = now_timestamp - self.retention_seconds

            channel_key = f"channel_memory:{channel_id}"

            # 获取当前频道的总消息数量
            total_count = self.redis_client.zcard(channel_key)

            if total_count <= self.min_keep_count:
                # 如果总数不超过最小保留数量，不进行任何清理
                logger.debug(
                    f"[redis_cleanup] 频道 {channel_id}: 总消息数 {total_count} <= {self.min_keep_count}，跳过清理"
                )
                return 0, 0

            # 获取所有消息，按时间戳倒序排列（最新的在前）
            # 注意：你的数据中，member是JSON字符串，score是时间戳
            all_messages = self.redis_client.zrevrange(
                channel_key, 0, -1, withscores=True
            )

            if len(all_messages) <= self.min_keep_count:
                logger.debug(
                    f"[redis_cleanup] 频道 {channel_id}: 实际消息数 {len(all_messages)} <= {self.min_keep_count}，跳过清理"
                )
                return 0, 0

            # 确定要保留的消息（最新的 1000 条）
            # 最新的 self.min_keep_count 条消息将被保留

            # 找出需要删除的过期消息（超过 48 小时且不在最新 1000 条中）
            messages_to_delete = []
            for message_json, timestamp in all_messages[
                self.min_keep_count :
            ]:  # 从第1001条开始检查
                if timestamp < retention_cutoff_timestamp:
                    messages_to_delete.append((message_json, timestamp))

            if not messages_to_delete:
                logger.debug(
                    f"[redis_cleanup] 频道 {channel_id}: 没有需要清理的过期消息"
                )
                return 0, 0

            # 批量删除过期消息
            deleted_count = 0
            for message_json, timestamp in messages_to_delete:
                # 删除特定的消息（使用JSON字符串作为member）
                removed = self.redis_client.zrem(channel_key, message_json)
                if removed:
                    deleted_count += 1
                    # 可选：解析消息内容用于日志记录
                    try:
                        msg_data = json.loads(message_json)
                        msg_time = datetime.datetime.fromtimestamp(
                            timestamp, tz
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        logger.debug(
                            f"删除消息: {msg_time} - {msg_data.get('role', 'unknown')}"
                        )
                    except Exception:
                        pass  # 忽略JSON解析错误

            if deleted_count > 0:
                remaining_count = self.redis_client.zcard(channel_key)
                logger.info(
                    f"[redis_cleanup] 频道 {channel_id}: 删除 {deleted_count} 条过期消息，保留 {remaining_count} 条"
                )

            return 0, deleted_count

        except Exception as e:
            logger.error(f"清理频道 {channel_id} 消息时出错: {e}")
            return 0, 0

    async def cleanup_abandoned_buffers(self):
        """清理被遗弃的消息缓冲区（可选功能）"""
        try:
            # 获取所有消息缓冲区的键
            buffer_keys = self.redis_client.keys("channel_buffer:*")

            if not buffer_keys:
                return

            logger.debug(f"[redis_cleanup] 检查 {len(buffer_keys)} 个消息缓冲区")

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
                logger.info(
                    f"[redis_cleanup] 清理了 {cleaned_count} 个被遗弃的消息缓冲区"
                )

        except Exception as e:
            logger.error(f"清理被遗弃缓冲区时出错: {e}")


# 单例实例
cleanup_service = RedisCleanupService()


async def start_redis_cleanup():
    """启动Redis清理服务的入口函数"""
    await cleanup_service.start_cleanup_scheduler()


if __name__ == "__main__":
    asyncio.run(start_redis_cleanup())
