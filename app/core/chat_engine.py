import logging
from typing import List

from core.context_merger import merge_context
from services.ai_service import stream_ai_chat
from core.persona import get_texas_system_prompt

logger = logging.getLogger(__name__)


class ChatEngine:
    def __init__(self):
        self.system_prompt = get_texas_system_prompt()

    async def stream_reply(self, channel_id: str, latest_query: str):
        logger.info(f"🧠 流式生成回复 for channel {channel_id}...")

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
            user_prompt = f"【参考资料】\n{reference_note}\n\n【Kawaro发来的信息】\n{latest_query}\n请根据参考资料回复Kawaro的消息。以消息为主，参考资料只是辅助。如果用===分段后，每个段落的末尾是句号“。”可以省略"
        messages.append({"role": "user", "content": user_prompt})

        print(user_prompt[:100] + "...")

        # 5. 流式调用 AI 模型
        async for segment in stream_ai_chat(messages):
            yield segment
