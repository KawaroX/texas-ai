import datetime
import pytz
import json
import redis
from app.config import settings
from utils.postgres_service import insert_messages

# 消息保留时长（秒）
MEMORY_RETENTION_SECONDS = 48 * 60 * 60  # 48 小时

# Redis 客户端
from utils.redis_manager import get_redis_client
redis_client = get_redis_client()


class ChannelMemory:
    def __init__(self, channel_id):
        self.channel_id = channel_id

    def add_message(self, role: str, content: str):
        # 获取东八区时间戳
        tz = pytz.timezone("Asia/Shanghai")
        now = datetime.datetime.now(tz)
        timestamp = now.timestamp()
        iso_time = now.isoformat()

        # 消息存储为 JSON 字符串，分数是东八区时间戳
        message = {
            "timestamp": timestamp,
            "role": role,
            "content": content,
        }

        # 1. 存入Redis
        redis_client.zadd(
            f"channel_memory:{self.channel_id}",
            {json.dumps(message, ensure_ascii=False): timestamp},
        )

        # 2. 同步存入PostgreSQL
        insert_messages([(self.channel_id, role, content, iso_time)])

    def get_recent_messages(self):
        tz = pytz.timezone("Asia/Shanghai")
        now_timestamp = datetime.datetime.now(tz).timestamp()
        six_hours_ago_timestamp = now_timestamp - MEMORY_RETENTION_SECONDS

        # 获取最近48小时内的消息
        raw_messages = redis_client.zrangebyscore(
            f"channel_memory:{self.channel_id}", six_hours_ago_timestamp, now_timestamp
        )

        recent_messages = []
        for msg_json in raw_messages:
            msg = json.loads(msg_json)
            # 将时间戳转换回 ISO 格式，使用东八区时间
            msg["timestamp"] = datetime.datetime.fromtimestamp(
                msg["timestamp"], tz=tz
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

            # 映射角色到用户名 &&&&&
            username = "德克萨斯" if msg["role"] == "assistant" else "kawaro"

            formatted.append(f"{time_str}{username}：{msg['content']}")
        return "\n".join(formatted)


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
