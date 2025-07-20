import logging
from typing import List

from core.context_merger import merge_context
from services.ai_service import call_ai_chat
from app.core.persona import get_texas_system_prompt

logger = logging.getLogger(__name__)


class ChatEngine:
    def __init__(self):
        self.system_prompt = get_texas_system_prompt()

    async def reply(self, channel_id: str, latest_query: str) -> List[str]:
        logger.info(f"🧠 Generating reply for channel {channel_id}...")

        # 1. 合并上下文（本频道+其他频道的摘要）
        context = await merge_context(channel_id, latest_query)
        messages = []

        # 2. 系统提示词
        messages.append({"role": "system", "content": self.system_prompt})

        # 3. 本频道上下文
        messages.extend(context["chat_context"])

        # 4. 当前 user 提问 + 附加参考资料（其他频道摘要）
        reference_note = "\n\n".join(context["summary_notes"])
        user_prompt = latest_query
        if reference_note:
            user_prompt += f"\n\n【参考资料】\n{reference_note}"
        messages.append({"role": "user", "content": user_prompt})

        # 5. 调用 AI 模型获取回复
        raw_response = await call_ai_chat(messages)

        # 6. === 分段处理
        replies = [part.strip() for part in raw_response.split("===") if part.strip()]
        return replies
