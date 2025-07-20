import logging
from datetime import datetime, timedelta
from typing import List, Dict

from core.memory_buffer import get_channel_memory, list_channels
from services.ai_service import call_ai_summary

logger = logging.getLogger(__name__)


async def merge_context(
    channel_id: str, latest_query: str, now: datetime = None
) -> Dict[str, List[Dict[str, str]]]:
    """
    整合最终上下文：
    1. 当前频道的 2h 聊天记录，直接作为上下文内容
    2. 其他频道的 2h 聊天记录，AI 摘录摘要信息，整合进 prompt 最后一段 user 消息中
    """
    now = now or datetime.utcnow()
    six_hours_ago = now - timedelta(hours=2)

    logger.info(f"🔍 Merging context for channel: {channel_id}")

    # 当前频道上下文（直接放入对话上下文）
    current_context = get_channel_memory(channel_id).get_recent_messages()
    logger.info(f"🧠 Found {len(current_context)} messages in current channel")

    # 其他频道消息 -> 摘录/摘要
    other_channels = list_channels(exclude=[channel_id])
    other_context_snippets = []

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
                f"如果没有相关的句子，请返回“空”。"
            )
            summary = await call_ai_summary(prompt)

            if summary:
                other_context_snippets.append(f"频道 [{other}] 的摘要信息：\n{summary}")
                logger.info(f"✅ Extracted summary from channel {other}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to summarize from {other}: {e}")

    # 汇总到最终结构：返回 prompt 的上下文结构
    return {
        "chat_context": current_context,  # 放入完整上下文
        "summary_notes": other_context_snippets,  # 放入最后 user 消息里
    }
