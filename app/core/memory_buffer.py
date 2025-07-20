import datetime
from collections import defaultdict
from utils.postgres_service import insert_messages

# 消息保留时长（秒）
MEMORY_RETENTION_SECONDS = 2 * 60 * 60  # 2 小时


class ChannelMemory:
    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.messages = []

    def add_message(self, role: str, content: str):
        self.messages.append(
            {"timestamp": datetime.datetime.utcnow().isoformat(), "role": role, "content": content}
        )

    def get_recent_messages(self):
        now = datetime.datetime.utcnow()
        recent_messages = []
        for m in self.messages:
            # 将 ISO 格式的时间戳字符串转换为 datetime 对象
            timestamp = datetime.datetime.fromisoformat(m["timestamp"])
            delta = (now - timestamp).total_seconds()
            if delta <= MEMORY_RETENTION_SECONDS:
                recent_messages.append(m)
        return recent_messages

    def persist_if_needed(self):
        now = datetime.datetime.utcnow()
        messages_to_persist = []
        retained = []

        for m in self.messages:
            # 将 ISO 格式的时间戳字符串转换为 datetime 对象
            timestamp = datetime.datetime.fromisoformat(m["timestamp"])
            delta = (now - timestamp).total_seconds()
            if delta > MEMORY_RETENTION_SECONDS:
                messages_to_persist.append(
                    (self.channel_id, m["role"], m["content"], m["timestamp"])
                )
            else:
                retained.append(m)

        self.messages = retained

        if messages_to_persist:
            insert_messages(messages_to_persist)


# 每个 channel 的内存缓存：channel_id -> ChannelMemory 实例
memory = defaultdict(lambda: None)

def get_channel_memory(channel_id):
    if memory[channel_id] is None:
        memory[channel_id] = ChannelMemory(channel_id)
    return memory[channel_id]

def list_channels(exclude=None):
    """返回所有已知频道ID列表，可排除指定频道"""
    exclude = exclude or []
    return [channel_id for channel_id in memory.keys() if channel_id and channel_id not in exclude]
