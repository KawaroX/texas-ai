from core.memory_buffer import memory
from services.ai_service import call_ai_summary
from typing import List


class CrossChannelContextAggregator:
    def __init__(self):
        pass

    async def summarize_other_channels(
        self, current_channel_id: str, all_channel_ids: List[str], latest_query: str
    ) -> str:
        """
        提取除当前频道外的所有频道的 2h 内缓存记录，调用 AI 摘录摘要。
        """
        related_messages = []

        for channel_id in all_channel_ids:
            if channel_id == current_channel_id:
                continue
            messages = memory.get_recent_messages(channel_id)
            if messages:
                context_block = self.format_channel_context(channel_id, messages)
                related_messages.append(context_block)

        if not related_messages:
            return ""

        context_for_ai = "\n\n".join(related_messages)
        summary_prompt = (
            "你是一个 AI 助手，将会看到多个不同聊天频道的近期对话内容，"
            "你的任务是从中提取与以下用户问题相关的信息，并总结为一段上下文摘要：\n"
            f"用户问题：{latest_query}\n"
            f"其他频道信息如下：\n{context_for_ai}"
        )

        summary = await call_ai_summary(summary_prompt)
        return summary or ""

    def format_channel_context(self, channel_id: str, messages: List[dict]) -> str:
        """格式化为可供 AI 理解的结构化聊天信息"""
        formatted = [f"[其他频道: {channel_id}]"]
        for msg in messages:
            role = "你" if msg["role"] == "user" else "德克萨斯"
            formatted.append(f"{role}: {msg['content']}")
        return "\n".join(formatted)
