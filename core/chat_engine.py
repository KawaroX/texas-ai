from utils.logging_config import get_logger

logger = get_logger(__name__)
from typing import List, Dict, Optional, Tuple
import asyncio

from core.context_merger import merge_context
from services.ai_service import stream_ai_chat
from core.persona import get_texas_system_prompt


class ChatEngine:
    def __init__(self):
        self.system_prompt = get_texas_system_prompt()

    async def stream_reply(
        self,
        channel_id: str,
        messages: List[str],
        channel_info: Optional[Dict] = None,
        user_info: Optional[Dict] = None,
        context_info: Optional[Tuple[str, List[str]]] = None,
        is_active_interaction: bool = False,
    ):
        """流式生成回复，使用新的消息结构（system + 单条 user 消息）"""
        logger.info(
            f"[chat_engine] 开始流式生成回复 channel={channel_id}, 消息数={len(messages)}"
        )

        # 1. 系统提示词 (根据频道和用户信息动态生成)
        dynamic_system_prompt = self.system_prompt

        dynamic_system_prompt += "\n\n# 背景信息\n\n <BgInfo>"

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
                f"\n\n当前用户信息，你可以选择合适的名字称呼对方：\n"
                f"- 用户名: {user_info.get('username', '未知')}\n"
                f"- 全名: {user_info.get('full_name', '未知')}\n"
                f"- 昵称: {user_info.get('nickname', '未知')}"
            )
        if user_info.get("username") == "kawaro":
            dynamic_system_prompt += "\n\n现在和你交流的user是Kawaro，这是你最熟悉的人，你应该表现得更温柔，你很喜欢他。虽然是一种克制的喜欢，但是你的心里知道你对他的喜欢超过对世上任何一个人。如果你们之间有争论，最终你会顺从他。"
        else:
            dynamic_system_prompt += (
                "\n\n这是一个普通用户，并不是Kawaro，你应该表现得更冷漠。"
                "尽一切可能少回复，用最少的字和最少的句子。但是也要有礼貌，礼貌地保持很大的社交距离。"
            )

        # 2. 获取整合的系统提示词和完整消息列表
        if context_info:
            # 如果提供了 context_info，说明已经预先调用了 merge_context
            logger.debug("使用预提供的 context_info")

            if isinstance(context_info, tuple) and len(context_info) == 2:
                # 如果 context_info 是 merge_context 返回的元组格式
                bg_info, context_messages = context_info
            elif isinstance(context_info, dict):
                # 如果 context_info 是字典格式
                bg_info = context_info.get("system_prompt", "")
                context_messages = context_info.get("messages", [])
            else:
                # 兼容旧格式：context_info 是单一字符串
                logger.warning(
                    "[chat_engine] context_info 使用旧格式，建议更新调用方式"
                )
                bg_info = ""  # 无法从旧格式中提取背景信息
                # 将旧格式转换为消息格式
                context_messages = [{"role": "user", "content": context_info}]

            logger.debug(
                f"[chat_engine] context_info 背景长度={len(bg_info)}, 消息数={len(context_messages)}"
            )

        else:
            # 否则，使用新的 merge_context 获取整合的系统提示词和消息
            latest_query = " ".join(messages)
            bg_info, context_messages = await merge_context(
                channel_id, latest_query, is_active=is_active_interaction
            )

            logger.debug(
                f"[chat_engine] merge_context 背景长度={len(bg_info)}, 消息数={len(context_messages)}"
            )

        # 3. 替换 dynamic_system_prompt 中的 <BgInfo> 占位符
        if "<BgInfo>" in dynamic_system_prompt:
            final_system_prompt = dynamic_system_prompt.replace("<BgInfo>", bg_info)
            logger.debug("已替换 <BgInfo> 占位符")
        else:
            # 如果没有占位符，直接追加背景信息
            final_system_prompt = f"{dynamic_system_prompt}\n\n{bg_info}"
            logger.debug("无 <BgInfo> 占位符，直接追加背景信息")

        # 4. 构建新的消息结构：system + 完整的对话历史
        prompt_messages = [
            {"role": "system", "content": final_system_prompt}
        ] + context_messages

        logger.debug(
            f"[chat_engine] 构建完成 system_len={len(final_system_prompt)}, 消息数={len(context_messages)}"
        )

        # 调试输出
        # logger.info(f"\n=== 新消息结构 ===")
        # for i, m in enumerate(prompt_messages):
        #     l_i = (
        #         f"\n\nMessage {i+1} - Role: {m['role']}\n"
        #         f"Content: {m['content'][:100]}...\n"
        #         f"Content length: {len(m['content'])} characters\n\n"
        #     )
        #     logger.info(l_i)
        # logger.info(f"Message {i+1} - Role: {m['role']}")
        # logger.info(f"Content: {m['content']}")
        # logger.info(f"Content length: {len(m['content'])} characters\n")

        # 4. 流式调用 AI 模型，并收集完整回复用于事件检测
        full_response = ""
        segments_list = []  # 收集所有segments
        marker = "[EVENT_DETECTED]"

        # 先收集所有segments
        async for segment in stream_ai_chat(prompt_messages, "claude-opus-4-5-20251101"):
            full_response += segment
            segments_list.append(segment)

        # 检查是否包含标记，并从segments中移除
        if marker in full_response:
            # 找到包含标记的segment并移除标记
            for i, seg in enumerate(segments_list):
                if marker in seg:
                    segments_list[i] = seg.replace(marker, "")
                    logger.info(f"[chat_engine] 从segment {i} 中移除事件标记")

        # 输出所有segments（保持原有分段逻辑）
        for seg in segments_list:
            yield seg

        logger.info(f"[chat_engine] 流式生成回复完成 channel={channel_id}, 回复长度={len(full_response)}, segments数量={len(segments_list)}")
        logger.debug(f"[chat_engine] 完整回复内容: {full_response[:200]}...")

        # 5. 检测事件标记并触发异步处理
        await self._process_event_detection(
            full_response,
            channel_id,
            messages,
            context_messages,
            user_info
        )

    async def _process_event_detection(
        self,
        ai_response: str,
        channel_id: str,
        user_messages: List[str],
        context_messages: List[Dict],
        user_info: Optional[Dict] = None
    ):
        """
        检测AI回复中的事件标记，并异步提取和存储事件

        Args:
            ai_response: AI的完整回复
            channel_id: 频道ID
            user_messages: 用户消息列表
            context_messages: 对话上下文
            user_info: 用户信息
        """
        logger.debug(f"[chat_engine] 检查事件标记，回复长度={len(ai_response)}, 包含标记={'[EVENT_DETECTED]' in ai_response}")

        # 检查事件标记
        if "[EVENT_DETECTED]" not in ai_response:
            logger.debug(f"[chat_engine] 未检测到事件标记")
            return

        logger.info(f"[chat_engine] ✅ 检测到事件标记，开始异步提取 channel={channel_id}")

        # 启动异步任务处理事件提取（不阻塞主流程）
        asyncio.create_task(
            self._extract_and_store_event(
                ai_response,
                channel_id,
                user_messages,
                context_messages,
                user_info
            )
        )

    async def _extract_and_store_event(
        self,
        ai_response: str,
        channel_id: str,
        user_messages: List[str],
        context_messages: List[Dict],
        user_info: Optional[Dict] = None
    ):
        """
        异步提取事件详情并存储

        Args:
            ai_response: AI的完整回复（包含标记）
            channel_id: 频道ID
            user_messages: 用户消息列表
            context_messages: 对话上下文
            user_info: 用户信息
        """
        try:
            from services.event_extractor import extract_event_details
            from services.future_event_manager import future_event_manager

            # 移除标记，获取干净的AI回复
            clean_response = ai_response.replace("[EVENT_DETECTED]", "").strip()

            # 获取用户消息
            user_message = " ".join(user_messages)

            # 提取事件详情
            event_data = await extract_event_details(
                user_message=user_message,
                ai_response=clean_response,
                recent_context=context_messages[-10:]  # 最近10条消息作为上下文
            )

            if not event_data:
                logger.info("[chat_engine] 事件提取失败或置信度过低，跳过存储")
                return

            # 获取用户ID
            user_id = user_info.get('username', 'unknown') if user_info else 'unknown'

            # 创建事件
            event_id = await future_event_manager.create_event(
                event_data=event_data,
                channel_id=channel_id,
                user_id=user_id,
                context_messages=context_messages[-5:]  # 保存最近5条消息作为上下文
            )

            if event_id:
                logger.info(
                    f"[chat_engine] 事件创建成功: {event_id} - {event_data.get('event_summary')}"
                )
            else:
                logger.warning("[chat_engine] 事件创建失败")

        except Exception as e:
            logger.error(f"[chat_engine] 事件提取和存储异常: {e}", exc_info=True)

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
