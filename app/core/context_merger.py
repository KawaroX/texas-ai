import logging
import redis
from datetime import datetime, timedelta
from typing import List, Dict

from core.memory_buffer import get_channel_memory, list_channels
from services.ai_service import call_ai_summary
from config import settings

logger = logging.getLogger(__name__)

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


async def merge_context(
    channel_id: str, latest_query: str, now: datetime = None
) -> str:
    """
    整合最终上下文，返回单条文本，包含四部分：
    1. 格式化的历史聊天记录（6小时内）
    2. 参考资料（其他频道摘要）
    3. Mattermost 消息缓存
    4. 引导提示词
    """
    now = now or datetime.utcnow()
    logger.info(f"🔍 Merging context for channel: {channel_id}")

    # 1. 格式化历史聊天记录
    history = get_channel_memory(channel_id).format_recent_messages()
    logger.info(f"🧠 Found formatted history: {len(history)} characters")

    # 2. 获取参考资料（其他频道摘要）
    other_channels = list_channels(exclude=[channel_id])
    summary_notes = []

    for other in other_channels:
        messages = get_channel_memory(other).get_recent_messages()
        if not messages:
            continue

        try:
            # 提示词构建
            content = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            prompt = (
                f"你是一个 AI 助手，当前用户提出了一个问题：\n"
                f"{latest_query}\n"
                f"以下是频道 {other} 中的最近 2 小时对话记录：\n{content}\n\n"
                f"请你摘录与用户问题相关的句子并做总结，用于辅助回答，不相关的请忽略。"
                f'如果没有相关的句子，请返回"空"（不需要任何符号，只需要这一个字）。'
                f"如果有相关的内容，那么返回的格式要求：\n\n总结：（对话记录中与用户相关的信息总结）\n\n相关对话记录：\nrole: (user/assistant二选一)\ncontent: 消息内容"
            )
            summary = await call_ai_summary(prompt)
            
            # 替换角色名称
            summary = summary.replace("user", "Kawaro").replace("assistant", "德克萨斯")

            if summary and summary.strip() and summary.strip() != "空":
                summary_notes.append(f"频道 [{other}] 的摘要信息：\n{summary}")
                logger.info(f"✅ Extracted summary from channel {other}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to summarize from {other}: {e}")

    # 3. 获取 Mattermost 消息缓存
    cache_key = f"channel_buffer:{channel_id}"
    cached_messages = redis_client.lrange(cache_key, 0, -1)
    mattermost_cache = ""
    if cached_messages:
        mattermost_cache = f"刚收到的新消息：\n" + "\n".join(cached_messages)
        logger.info(f"📝 Found {len(cached_messages)} cached messages")

    # 4. 组合四部分内容
    parts = []
    
    if history:
        parts.append(f"【历史聊天记录】\n{history}")
    
    if summary_notes:
        parts.append(f"【参考资料】\n" + "\n\n".join(summary_notes))
    
    if mattermost_cache:
        parts.append(f"【新消息缓存】\n{mattermost_cache}")
    
    # 添加引导提示词
    parts.append(f"请根据上述信息回复Kawaro的消息：{latest_query}")
    
    merged_context = "\n\n".join(parts)
    logger.info(f"✅ Context merged, total length: {len(merged_context)} characters")
    
    return merged_context
