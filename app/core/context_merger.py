import logging
import redis
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict
import pytz

from core.memory_buffer import get_channel_memory, list_channels
from services.ai_service import call_ai_summary
from config import settings

logger = logging.getLogger(__name__)

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


def _needs_summary(messages_text: str) -> bool:
    """判断消息是否需要跨频道摘要"""
    combined_message = messages_text.strip()

    # 短消息不需要摘要
    if len(combined_message) < 5:
        return False

    # 简单问候语不需要摘要
    simple_greetings = ["在吗", "你好", "hi", "hello", "嗨", "？", "?"]
    if combined_message.lower() in simple_greetings:
        return False

    # 其他情况需要摘要
    return True


async def _summarize_channel(channel_id: str, messages: List[Dict], latest_query: str) -> str:
    """为单个频道生成摘要"""
    try:
        content = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        prompt = (
            f"你是一个 AI 助手，当前用户提出了一个问题：\n"
            f"{latest_query}\n"
            f"以下是频道 {channel_id} 中的最近 6 小时对话记录：\n{content}\n\n"
            f"请你摘录与用户问题相关的句子并做总结，用于辅助回答，不相关的请忽略。"
            f'如果没有相关的句子，请返回"空"（不需要任何符号，只需要这一个字）。'
            f"如果有相关的内容，那么返回的格式要求：\n\n总结：（对话记录中与用户相关的信息总结）\n\n相关对话记录：\nrole: (user/assistant二选一)\ncontent: 消息内容"
        )
        summary = await call_ai_summary(prompt)
        
        # 替换角色名称
        summary = summary.replace("user", "Kawaro").replace("assistant", "德克萨斯")

        if summary and summary.strip() and summary.strip() != "空":
            return f"频道 [{channel_id}] 的摘要信息：\n{summary}"
        return ""

    except Exception as e:
        logger.warning(f"⚠️ 频道 {channel_id} 摘要失败: {e}")
        return ""


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
    shanghai_tz = pytz.timezone("Asia/Shanghai")
    now = now or datetime.now(shanghai_tz)
    logger.info(f"🔍 Merging context for channel: {channel_id}")

    # 1. 格式化历史聊天记录
    history = get_channel_memory(channel_id).format_recent_messages()
    logger.info(f"🧠 Found formatted history: {len(history)} characters")

    # 2. 获取参考资料（其他频道摘要）- 判断是否需要摘要
    summary_notes = []
    if _needs_summary(latest_query):
        other_channels = list_channels(exclude=[channel_id])
        summary_tasks = []
        all_latest_timestamps = []

        # 获取当前频道最新消息的时间戳
        current_channel_messages = get_channel_memory(channel_id).get_recent_messages()
        if current_channel_messages:
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
                _summarize_channel(other_channel, messages, latest_query),
                name=f"summary_{other_channel}",
            )
            summary_tasks.append(task)

        # 等待所有摘要任务完成
        if summary_tasks:
            summaries = await asyncio.gather(*summary_tasks, return_exceptions=True)

            # 处理结果，过滤异常和空摘要
            for i, summary in enumerate(summaries):
                if isinstance(summary, Exception):
                    logger.warning(f"⚠️ 频道摘要失败: {summary}")
                    continue
                if summary and summary.strip() and summary.strip() != "空":
                    summary_notes.append(summary)

        # 计算时间差并生成"谴责"提示
        if all_latest_timestamps:
            latest_overall_message_time = max(all_latest_timestamps)
            # 使用东八区时间
            current_time = datetime.now(shanghai_tz)
            time_diff = current_time - latest_overall_message_time

            if time_diff > timedelta(hours=1):
                # 判断是否在东八区睡眠时间（23:00 - 07:00）
                latest_local_time = latest_overall_message_time
                current_local_time = current_time

                is_during_sleep_time = False
                # 定义睡眠时间段的开始和结束小时（东八区）
                SLEEP_START_HOUR = 23
                SLEEP_END_HOUR = 7

                # 辅助函数：判断一个小时是否在睡眠时间段内
                def is_in_sleep_range(hour):
                    if SLEEP_START_HOUR <= SLEEP_END_HOUR:  # 同一天
                        return SLEEP_START_HOUR <= hour < SLEEP_END_HOUR
                    else:  # 跨天
                        return hour >= SLEEP_START_HOUR or hour < SLEEP_END_HOUR

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
                current_check_time = latest_overall_message_time

                while current_check_time < current_time:
                    # 已经是东八区时间，直接使用
                    local_check_time = current_check_time

                    # 计算到下一个小时边界的时间
                    next_hour = (current_check_time + timedelta(hours=1)).replace(
                        minute=0, second=0, microsecond=0
                    )

                    # 确保不超过 current_time
                    end_of_interval = min(next_hour, current_time)

                    # 计算当前小时内重叠的秒数
                    overlap_seconds_in_this_hour = 0

                    # 如果当前小时在睡眠时间段内
                    if is_in_sleep_range(local_check_time.hour):
                        # 计算当前小时内，从 current_check_time 到 end_of_interval 的秒数
                        overlap_seconds_in_this_hour = (
                            end_of_interval - current_check_time
                        ).total_seconds()

                    total_sleep_overlap_seconds += overlap_seconds_in_this_hour
                    current_check_time = end_of_interval  # 移动到下一个检查点

                # 如果睡眠时间重合超过4小时，认为是睡眠时间
                if total_sleep_overlap_seconds >= timedelta(hours=4).total_seconds():
                    is_during_sleep_time = True

                if not is_during_sleep_time:
                    hours_diff = int(time_diff.total_seconds() // 3600)
                    minutes_diff = int((time_diff.total_seconds() % 3600) // 60)
                    condemn_message = (
                        f"【参考资料】\n"
                        f"注意：距离Kawaro你上次在任何频道（包括当前频道）回复我，已经过去了 {hours_diff} 小时 {minutes_diff} 分钟。Kawaro你的最新消息与上次回复的内容是否有关联？请根据上下文判断是否需要对此进行适当的评论、抱怨或“谴责”。"
                    )
                    summary_notes.insert(0, condemn_message)  # 将谴责信息放在最前面

        logger.info(f"✅ 成功获取 {len(summary_notes)} 个频道摘要 (包括潜在的谴责提示)")
    else:
        logger.info("📝 消息较简单，跳过跨频道摘要")

    # # 3. 获取 Mattermost 消息缓存
    # cache_key = f"channel_buffer:{channel_id}"
    # cached_messages = redis_client.lrange(cache_key, 0, -1)
    # mattermost_cache = ""
    # if cached_messages:
    #     mattermost_cache = f"刚收到的新消息：\n" + "\n".join(cached_messages)
    #     logger.info(f"📝 Found {len(cached_messages)} cached messages")

    # 4. 组合四部分内容
    parts = []
    
    if history:
        parts.append(f"【历史聊天记录】\n{history}")
    
    if summary_notes:
        parts.append(f"【参考资料】\n" + "\n\n".join(summary_notes))
    
    # if mattermost_cache:
    #     parts.append(f"【新消息缓存】\n{mattermost_cache}")
    
    # 添加引导提示词
    parts.append(f"请根据上述信息回复Kawaro的消息：{latest_query}")
    
    merged_context = "\n\n".join(parts)
    logger.info(f"✅ Context merged, total length: {len(merged_context)} characters")
    
    return merged_context
