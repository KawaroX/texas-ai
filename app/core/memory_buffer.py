import datetime
import json
from datetime import timedelta
import redis
from config import settings
from utils.postgres_service import insert_messages

# 消息保留时长（秒）
MEMORY_RETENTION_SECONDS = 6 * 60 * 60  # 6 小时

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


class ChannelMemory:
    def __init__(self, channel_id):
        self.channel_id = channel_id

    def add_message(self, role: str, content: str):
        # 消息存储为 JSON 字符串，分数是 UTC 时间戳
        message = {
            "timestamp": datetime.datetime.utcnow().timestamp(),
            "role": role,
            "content": content,
        }
        redis_client.zadd(
            f"channel_memory:{self.channel_id}",
            {json.dumps(message): message["timestamp"]},
        )

    def get_recent_messages(self):
        now_timestamp = datetime.datetime.utcnow().timestamp()
        six_hours_ago_timestamp = now_timestamp - MEMORY_RETENTION_SECONDS

        # 获取最近2小时内的消息
        raw_messages = redis_client.zrangebyscore(
            f"channel_memory:{self.channel_id}", six_hours_ago_timestamp, now_timestamp
        )

        recent_messages = []
        for msg_json in raw_messages:
            msg = json.loads(msg_json)
            # 将时间戳转换回 ISO 格式，与旧代码保持一致
            msg["timestamp"] = datetime.datetime.fromtimestamp(
                msg["timestamp"]
            ).isoformat()
            recent_messages.append(msg)
        return recent_messages

    def format_recent_messages(self) -> str:
        messages = self.get_recent_messages()
        formatted = []
        for msg in messages:
            # 转换时间格式: ISO → [HH:MM:SS]
            dt = datetime.datetime.fromisoformat(msg["timestamp"])
            time_str = dt.strftime("[%H:%M:%S]")
            
            # 映射角色到用户名
            username = "德克萨斯" if msg["role"] == "assistant" else "Kawaro"
            
            formatted.append(f"{time_str}{username}：{msg['content']}")
        return "\n".join(formatted)

    def persist_if_needed(self):
        now_timestamp = datetime.datetime.utcnow().timestamp()
        six_hours_ago_timestamp = now_timestamp - MEMORY_RETENTION_SECONDS

        # 获取超过2小时的消息
        messages_to_persist_raw = redis_client.zrangebyscore(
            f"channel_memory:{self.channel_id}", 0, six_hours_ago_timestamp
        )

        if messages_to_persist_raw:
            messages_for_db = []
            for msg_json in messages_to_persist_raw:
                msg = json.loads(msg_json)
                # 转换为 insert_messages 期望的格式 (channel_id, role, content, timestamp)
                messages_for_db.append(
                    (
                        self.channel_id,
                        msg["role"],
                        msg["content"],
                        datetime.datetime.fromtimestamp(msg["timestamp"]).isoformat(),
                    )
                )

            # 批量插入到 PostgreSQL
            insert_messages(messages_for_db)

            # 从 Redis 中删除已归档的消息
            redis_client.zremrangebyscore(
                f"channel_memory:{self.channel_id}", 0, six_hours_ago_timestamp
            )


def get_channel_memory(channel_id):
    # 直接返回 ChannelMemory 实例，它会操作 Redis
    return ChannelMemory(channel_id)


def list_channels(exclude=None):
    """返回所有已知频道ID列表，可排除指定频道"""
    channel_keys = redis_client.keys("channel_memory:*")
    all_channel_ids = [key.split(":")[1] for key in channel_keys]

    exclude = exclude or []
    return [
        channel_id
        for channel_id in all_channel_ids
        if channel_id and channel_id not in exclude
    ]
