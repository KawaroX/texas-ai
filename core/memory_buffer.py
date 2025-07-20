import datetime
from collections import defaultdict
from utils.postgres_service import insert_messages

# 每个 channel 的内存缓存：channel_id -> list of dicts
# 每条消息结构：{"timestamp": ..., "role": ..., "content": ...}
memory = defaultdict(list)

# 消息保留时长（秒）
MEMORY_RETENTION_SECONDS = 2 * 60 * 60  # 2 小时


def add_message(channel_id: str, role: str, content: str):
    memory[channel_id].append(
        {"timestamp": datetime.datetime.utcnow(), "role": role, "content": content}
    )


def get_context(channel_id: str):
    now = datetime.datetime.utcnow()
    return [
        m
        for m in memory[channel_id]
        if (now - m["timestamp"]).total_seconds() <= MEMORY_RETENTION_SECONDS
    ]


def persist_if_needed(channel_id: str):
    now = datetime.datetime.utcnow()
    messages_to_persist = []

    retained = []
    for m in memory[channel_id]:
        delta = (now - m["timestamp"]).total_seconds()
        if delta > MEMORY_RETENTION_SECONDS:
            messages_to_persist.append(
                (channel_id, m["role"], m["content"], m["timestamp"])
            )
        else:
            retained.append(m)

    memory[channel_id] = retained

    if messages_to_persist:
        insert_messages(messages_to_persist)
