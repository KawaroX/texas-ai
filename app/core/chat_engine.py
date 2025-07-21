import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from core.memory_buffer import get_channel_memory, list_channels
from core.context_merger import merge_context
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
        all_latest_timestamps = []

        # 获取当前频道最新消息的时间戳
        current_channel_messages = get_channel_memory(channel_id).get_recent_messages()
        if current_channel_messages:
            # 假设消息是按时间倒序排列的，或者我们取最后一条
            latest_current_message_time = datetime.fromisoformat(
                current_channel_messages[-1]["timestamp"]
            )
            all_latest_timestamps.append(latest_current_message_time)

        for other_channel in other_channels:
            messages = get_channel_memory(other_channel).get_recent_messages()
            if not messages:
                continue

            # 获取其他频道最新消息的时间戳
            latest_other_message_time = datetime.fromisoformat(
                messages[-1]["timestamp"]
            )
            all_latest_timestamps.append(latest_other_message_time)

            # 为每个频道创建异步摘要任务
            task = asyncio.create_task(
                self._summarize_channel(other_channel, messages, latest_query),
                name=f"summary_{other_channel}",
            )
            summary_tasks.append(task)

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

        # 计算时间差并生成“谴责”提示
        if all_latest_timestamps:
            latest_overall_message_time = max(all_latest_timestamps)
            current_utc_time = datetime.utcnow()  # 使用 UTC 时间
            time_diff = current_utc_time - latest_overall_message_time

            if time_diff > timedelta(hours=1):
                # 判断是否在东八区睡眠时间（23:00 - 07:00）
                # 将 UTC 时间转换为东八区时间进行判断
                latest_local_time = latest_overall_message_time + timedelta(hours=8)
                current_local_time = current_utc_time + timedelta(hours=8)

                is_during_sleep_time = False
                # 检查时间段是否与睡眠时间高度重合
                # 简化判断：如果最新消息时间和当前时间都在睡眠时间段内，或者跨越了睡眠时间段
                # 睡眠时间：23:00 (23) 到次日 7:00 (7)

                # 定义睡眠时间段的开始和结束小时（东八区）
                SLEEP_START_HOUR = 23
                SLEEP_END_HOUR = 7

                # 检查时间段是否完全落在睡眠时间段内
                # 情况1: 都在同一天，且在睡眠时间段内 (例如 23:30 -> 00:30) - 不可能，因为跨天了
                # 情况2: 跨天，从前一天的睡眠时间到当前天的睡眠时间 (例如 23:30 -> 06:30)
                # 情况3: 从非睡眠时间进入睡眠时间 (例如 22:30 -> 00:30)
                # 情况4: 从睡眠时间进入非睡眠时间 (例如 06:30 -> 08:30)

                # 辅助函数：判断一个小时是否在睡眠时间段内
                def is_in_sleep_range(hour):
                    if SLEEP_START_HOUR <= SLEEP_END_HOUR:  # 同一天
                        return SLEEP_START_HOUR <= hour < SLEEP_END_HOUR
                    else:  # 跨天
                        return hour >= SLEEP_START_HOUR or hour < SLEEP_END_HOUR

                # 检查时间段内是否有大部分时间落在睡眠时间
                # 简单判断：如果开始时间和结束时间都在睡眠时间段内，或者时间段跨越了睡眠时间段的大部分
                # 这里可以更精确地计算重合时长，但为了简化，先判断起点和终点

                # 如果开始时间在睡眠时间段内
                if is_in_sleep_range(latest_local_time.hour):
                    is_during_sleep_time = True
                # 如果结束时间在睡眠时间段内
                elif is_in_sleep_range(current_local_time.hour):
                    is_during_sleep_time = True
                # 如果时间段跨越了睡眠时间段（例如从晚上22点到早上8点）
                elif (
                    latest_local_time.hour < SLEEP_START_HOUR
                    and current_local_time.hour >= SLEEP_END_HOUR
                    and time_diff > timedelta(hours=8)
                ):
                    # 粗略判断，如果时间差超过8小时，且跨越了整个睡眠时间段
                    is_during_sleep_time = True

                # 更精确的判断：计算时间段内有多少小时落在睡眠时间
                total_sleep_overlap_seconds = 0
                current_check_time = latest_overall_message_time  # UTC时间

                while current_check_time < current_utc_time:
                    # 将当前检查时间转换为东八区时间
                    local_check_time = current_check_time + timedelta(hours=8)

                    # 计算到下一个小时边界的时间
                    next_hour_utc = (current_check_time + timedelta(hours=1)).replace(
                        minute=0, second=0, microsecond=0
                    )

                    # 确保不超过 current_utc_time
                    end_of_interval_utc = min(next_hour_utc, current_utc_time)

                    # 计算当前小时内重叠的秒数
                    overlap_seconds_in_this_hour = 0

                    # 如果当前小时在睡眠时间段内
                    if is_in_sleep_range(local_check_time.hour):
                        # 计算当前小时内，从 current_check_time 到 end_of_interval_utc 的秒数
                        overlap_seconds_in_this_hour = (
                            end_of_interval_utc - current_check_time
                        ).total_seconds()

                    total_sleep_overlap_seconds += overlap_seconds_in_this_hour
                    current_check_time = end_of_interval_utc  # 移动到下一个检查点

                # 如果睡眠时间重合超过总时间差的50% (或者一个固定阈值，比如4小时)
                # 这里设定一个阈值，比如至少有4小时的睡眠时间重合
                if total_sleep_overlap_seconds >= timedelta(hours=4).total_seconds():
                    is_during_sleep_time = True

                if not is_during_sleep_time:
                    hours_diff = int(time_diff.total_seconds() // 3600)
                    minutes_diff = int((time_diff.total_seconds() % 3600) // 60)
                    condemn_message = (
                        f"【参考资料】\n"
                        f"注意：距离Kawaro你上次在任何频道（包括当前频道）回复我，已经过去了 {hours_diff} 小时 {minutes_diff} 分钟。Kawaro你的最新消息与上次回复的内容是否有关联？请根据上下文判断是否需要对此进行适当的评论或“谴责”。"
                    )
                    summary_notes.insert(0, condemn_message)  # 将谴责信息放在最前面

        logger.info(f"✅ 成功获取 {len(summary_notes)} 个频道摘要 (包括潜在的谴责提示)")
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

            summary = summary.replace("user", "Kawaro").replace(
                "assistant", "你"
            )  # 直接赋值给 summary

            if summary and summary.strip() and summary.strip() != "空":
                return f"频道 [{channel_id}] 的摘要信息：\n{summary}"
            return ""

        except Exception as e:
            logger.warning(f"⚠️ 频道 {channel_id} 摘要失败: {e}")
            return ""

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
        if channel_info:
            dynamic_system_prompt += (
                f"\n\n当前频道信息：\n"
                f"- 频道名称 (系统): {channel_info.get('name', '未知')}\n"
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
                "\n\n如果不是Kawaro的话，你应该表现得更冷漠。你的温柔应该留给Kawaro."
            )

        # 2. 使用新的 context_merger 获取整合的单条文本
        latest_query = " ".join(messages)
        merged_context = await merge_context(channel_id, latest_query)

        # 3. 构建新的消息结构：system + 单条 user 消息
        prompt_messages = [
            {"role": "system", "content": dynamic_system_prompt},
            {"role": "user", "content": merged_context}
        ]

        # 调试输出
        logger.info(f"\n=== 新消息结构 ===")
        for i, m in enumerate(prompt_messages):
            logger.info(f"Message {i+1} - Role: {m['role']}")
            logger.info(f"Content (前200字符): {m['content'][:200]}...")
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
