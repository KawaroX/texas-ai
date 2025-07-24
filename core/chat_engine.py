import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pytz

from core.memory_buffer import get_channel_memory, list_channels
from core.context_merger import merge_context
from services.ai_service import stream_ai_chat, call_ai_summary
from core.persona import get_texas_system_prompt

logger = logging.getLogger(__name__)


class ChatEngine:
    def __init__(self):
        self.system_prompt = get_texas_system_prompt()

    async def stream_reply(
        self,
        channel_id: str,
        messages: List[str],
        channel_info: Optional[Dict] = None,
        user_info: Optional[Dict] = None,
        context_info: Optional[Dict] = None,
    ):
        """流式生成回复，使用新的消息结构（system + 单条 user 消息）"""
        logger.info(
            f"🧠 流式生成回复 for channel {channel_id}, 消息数: {len(messages)}"
        )

        # 1. 系统提示词 (根据频道和用户信息动态生成)
        dynamic_system_prompt = self.system_prompt
        if channel_info["type"] == "D":
            channel_info["display_name"] = "私聊"
        if channel_info:
            dynamic_system_prompt += (
                f"\n\n当前频道信息：\n"
                f"- 频道显示名称: {channel_info.get('display_name', '未知')}\n"
                f"- 频道类型: {channel_info.get('type', '未知')}"
                "\n\n可以根据频道信息进行定制化处理。"
            )
        if user_info:
            dynamic_system_prompt += (
                f"\n\n当前用户信息：\n"
                f"- 用户名: {user_info.get('username', '未知')}\n"
                f"- 全名: {user_info.get('full_name', '未知')}\n"
                f"- 昵称: {user_info.get('nickname', '未知')}"
            )
        if user_info.get("username") == "kawaro":
            dynamic_system_prompt += "\n\nKawaro，这是你最熟悉的人，你应该表现得更温柔，你很喜欢他。虽然是一种克制的喜欢，但是你的心里知道你对他的喜欢超过对世上任何一个人。"
        else:
            dynamic_system_prompt += (
                "\n\n这是一个普通用户，并不是Kawaro，你应该表现得更冷漠。"
                "尽一切可能少回复，用最少的字和最少的句子。但是也要有礼貌，礼貌地保持很大的社交距离。"
            )

        # 2. 使用新的 context_merger 获取整合的单条文本
        latest_query = " ".join(messages)
        merged_context = await merge_context(channel_id, latest_query)

        # 3. 构建新的消息结构：system + 单条 user 消息
        prompt_messages = [
            {"role": "system", "content": dynamic_system_prompt},
            {"role": "user", "content": merged_context},
        ]

        # 调试输出
        logger.info(f"\n=== 新消息结构 ===")
        for i, m in enumerate(prompt_messages):
            logger.info(f"Message {i+1} - Role: {m['role']}")
            logger.info(f"Content: {m['content']}")
            logger.info(f"Content length: {len(m['content'])} characters\n")

        # 4. 流式调用 AI 模型
        async for segment in stream_ai_chat(prompt_messages):
            yield segment

    # 为了向后兼容，保留原有的单消息接口
    async def stream_reply_single(
        self,
        channel_id: str,
        latest_query: str,
        channel_info: Optional[Dict] = None,
        user_info: Optional[Dict] = None,
    ):
        """向后兼容的单消息接口"""
        async for segment in self.stream_reply(
            channel_id, [latest_query], channel_info, user_info
        ):
            yield segment
