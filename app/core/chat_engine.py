import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from core.memory_buffer import get_channel_memory, list_channels
from services.ai_service import stream_ai_chat, call_ai_summary
from core.persona import get_texas_system_prompt

logger = logging.getLogger(__name__)


class ChatEngine:
    def __init__(self):
        self.system_prompt = get_texas_system_prompt()

    def _needs_summary(self, messages: List[str]) -> bool:
        """判断消息是否需要跨频道摘要"""
        # 合并所有消息进行判断
        combined_message = " ".join(messages).strip()

        # 短消息不需要摘要
        if len(combined_message) < 5:
            return False

        # 简单问候语不需要摘要
        simple_greetings = ["在吗", "你好", "hi", "hello", "嗨", "？", "?"]
        if combined_message.lower() in simple_greetings:
            return False

        # 其他情况需要摘要
        return True

    async def _collect_context_info(self, channel_id: str, messages: List[str]) -> Dict:
        """收集所有上下文信息的统一入口"""
        logger.info(f"🔍 开始收集频道 {channel_id} 的上下文信息...")

        # 获取当前频道上下文（这个很快，直接获取）
        current_context = get_channel_memory(channel_id).get_recent_messages()
        logger.info(f"🧠 当前频道找到 {len(current_context)} 条消息")

        # 判断是否需要其他频道摘要
        if not self._needs_summary(messages):
            logger.info("📝 消息较简单，跳过跨频道摘要")
            return {"chat_context": current_context, "summary_notes": []}

        # 异步获取其他频道摘要
        latest_query = " ".join(messages)
        summary_notes = await self._get_cross_channel_summaries(
            channel_id, latest_query
        )

        return {"chat_context": current_context, "summary_notes": summary_notes}

    async def _get_cross_channel_summaries(
        self, channel_id: str, latest_query: str
    ) -> List[str]:
        """获取其他频道的摘要信息"""
        other_channels = list_channels(exclude=[channel_id])
        summary_tasks = []

        for other_channel in other_channels:
            messages = get_channel_memory(other_channel).get_recent_messages()
            if not messages:
                continue

            # 为每个频道创建异步摘要任务
            task = asyncio.create_task(
                self._summarize_channel(other_channel, messages, latest_query),
                name=f"summary_{other_channel}",
            )
            summary_tasks.append(task)

        if not summary_tasks:
            return []

        # 等待所有摘要任务完成
        summaries = await asyncio.gather(*summary_tasks, return_exceptions=True)

        # 处理结果，过滤异常和空摘要
        summary_notes = []
        for i, summary in enumerate(summaries):
            if isinstance(summary, Exception):
                logger.warning(f"⚠️ 频道摘要失败: {summary}")
                continue
            if summary and summary.strip() and summary.strip() != "空":
                summary_notes.append(summary)

        logger.info(f"✅ 成功获取 {len(summary_notes)} 个频道摘要")
        return summary_notes

    async def _summarize_channel(
        self, channel_id: str, messages: List[Dict], latest_query: str
    ) -> str:
        """为单个频道生成摘要"""
        try:
            content = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            prompt = (
                f"你是一个 AI 助手，当前用户提出了一个问题：\n"
                f"{latest_query}\n"
                f"以下是频道 {channel_id} 中的最近 2 小时对话记录：\n{content}\n\n"
                f"请你摘录与用户问题相关的句子并做总结，用于辅助回答，不相关的请忽略。"
                f'如果没有相关的句子，请返回"空"（不需要任何符号，只需要这一个字）。'
                f"如果有相关的内容，那么返回的格式要求：\n\n总结：（对话记录中与用户相关的信息总结）\n\n相关对话记录：\nrole: (user/assistant二选一)\ncontent: 消息内容"
            )
            summary = await call_ai_summary(prompt)

            summary.replace("user", "Kawaro").replace("assistant", "你")

            if summary and summary.strip() and summary.strip() != "空":
                return f"频道 [{channel_id}] 的摘要信息：\n{summary}"
            return ""

        except Exception as e:
            logger.warning(f"⚠️ 频道 {channel_id} 摘要失败: {e}")
            return ""

    async def stream_reply(
        self, channel_id: str, messages: List[str], context_info: Optional[Dict] = None
    ):
        """流式生成回复，支持消息列表和预收集的上下文"""
        logger.info(
            f"🧠 流式生成回复 for channel {channel_id}, 消息数: {len(messages)}"
        )

        # 如果没有预收集的上下文，现在收集
        if context_info is None:
            context_info = await self._collect_context_info(channel_id, messages)

        # 构建完整的用户查询
        latest_query = "\n".join(messages) if len(messages) > 1 else messages[0]

        # 构建消息列表
        prompt_messages = []

        # 1. 系统提示词
        prompt_messages.append({"role": "system", "content": self.system_prompt})

        # 2. 本频道上下文
        prompt_messages.extend(context_info["chat_context"])

        # 3. 构建用户消息（包含参考资料）
        reference_note = "\n\n".join(context_info["summary_notes"])

        # 如果有现有的用户消息，先移除最后一个
        # 这一步是针对 chat_context 中可能包含的最后一条用户消息
        if prompt_messages and prompt_messages[-1]["role"] == "user":
            prompt_messages.pop()

        # 添加参考资料作为单独的用户消息
        if reference_note:
            prompt_messages.append(
                {"role": "user", "content": f"【参考资料】\n{reference_note}"}
            )

        # 将用户发送的每一条消息作为独立的user消息添加到prompt_messages中
        for i, msg in enumerate(messages):
            prompt_messages.append({"role": "user", "content": msg})

        # 在最后一条用户消息中添加回复要求
        if prompt_messages and prompt_messages[-1]["role"] == "user":
            prompt_messages[-1][
                "content"
            ] += '\n\n请根据参考资料回复Kawaro的消息。以消息为主，参考资料只是辅助。如果用===分段后，每个段落的末尾是句号"。"可以省略'

        # 调试输出
        for m in prompt_messages:
            logger.info(f"\nRole: {m['role']}")
            logger.info(f"Message: {m['content']}\n")

        # 4. 流式调用 AI 模型
        async for segment in stream_ai_chat(prompt_messages):
            yield segment

    # 为了向后兼容，保留原有的单消息接口
    async def stream_reply_single(self, channel_id: str, latest_query: str):
        """向后兼容的单消息接口"""
        async for segment in self.stream_reply(channel_id, [latest_query]):
            yield segment
