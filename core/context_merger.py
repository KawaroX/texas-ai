import logging
import redis
import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import pytz

from core.memory_buffer import get_channel_memory, list_channels
from services.ai_service import call_ai_summary
from app.config import settings
from utils.mem0_service import mem0

logger = logging.getLogger(__name__)

# Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


def _needs_summary(messages_text: str) -> bool:
    """判断消息是否需要跨频道摘要"""
    combined_message = messages_text.strip()

    # 短消息不需要摘要
    if len(combined_message) < 3:
        return False

    # 简单问候语不需要摘要
    simple_greetings = ["在吗", "你好", "hi", "hello", "嗨", "？", "?"]
    if combined_message.lower() in simple_greetings:
        return False

    # 其他情况需要摘要
    return True


async def _summarize_channel(
    channel_id: str, messages: List[Dict], latest_query: str
) -> str:
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
        summary = summary.replace(
            "assistant", "德克萨斯"
        )  # .replace("user", "Kawaro") &&&&&

        if summary and summary.strip() and summary.strip() != "空":
            return f"频道 [{channel_id}] 的摘要信息：\n{summary}"
        return ""

    except Exception as e:
        logger.warning(f"⚠️ 频道 {channel_id} 摘要失败: {e}")
        return ""


def _get_life_system_context() -> str:
    """获取生活系统数据作为上下文"""
    try:
        from datetime import date

        today = date.today()
        date_str = today.strftime("%Y-%m-%d")
        redis_key = f"life_system:{date_str}"

        life_data = redis_client.hgetall(redis_key)

        if not life_data:
            logger.info("ℹ️ 未找到生活系统数据")
            return ""

        context_parts = []

        # 添加大事件信息
        if "major_event" in life_data:
            try:
                major_event = json.loads(life_data["major_event"])
                if major_event and isinstance(major_event, dict):
                    main_content = major_event.get("main_content", "")
                    start_date = major_event.get("start_date", "")
                    end_date = major_event.get("end_date", "")
                    event_type = major_event.get("event_type", "")
                    daily_summaries = major_event.get("daily_summaries", [])
                    if isinstance(daily_summaries, str):
                        try:
                            daily_summaries = json.loads(daily_summaries)
                        except json.JSONDecodeError:
                            daily_summaries = []

                    if main_content:
                        context_parts.append(
                            f"【你正在经历的大事件】{start_date}至{end_date} {event_type}\n\n{main_content}"
                        )
                    if daily_summaries:
                        day_number = (
                            today - datetime.strptime(start_date, "%Y-%m-%d").date()
                        ).days + 1
                        for item in daily_summaries:
                            if int(item["day"]) <= day_number:
                                context_parts.append(
                                    f"【{item['date']}】Day {item['day']}\n{item}"
                                )
            except Exception as e:
                logger.warning(f"⚠️ 大事件数据解析失败: {e}")
                if life_data["major_event"]:
                    context_parts.append(
                        f"【你正在经历的大事件】{life_data['major_event']}"
                    )

        # 1. 添加日程信息
        if (
            "daily_schedule" in life_data
            and life_data["daily_schedule"] != "当日没有日程。"
        ):
            try:
                schedule = json.loads(life_data["daily_schedule"])
                data = schedule.get("schedule_data", {})
                if schedule and isinstance(schedule, dict):
                    header = f"你是德克萨斯，以下是你的今日日程\n【今日日程 - {schedule.get('date', '')}】天气：{schedule.get('weather', '')}\n"
                    summary = f"🔹日程概览：{data.get('daily_summary', '')}\n"

                    items = []
                    for item in data.get("schedule_items", []):
                        start_time = item.get("start_time")
                        end_time = item.get("end_time")
                        time_range = f"{start_time} - {end_time}"
                        location = (
                            f"📍位于{item.get('location')}"
                            if item.get("location")
                            else ""
                        )
                        companions = (
                            f"和{'、'.join(item.get('companions', []))}在一起行动"
                            if item.get("companions")
                            else ""
                        )
                        description = f"{item.get('description', '')}"

                        if isinstance(start_time, str):
                            start_time_dt = datetime.combine(
                                datetime.today(),
                                datetime.strptime(start_time, "%H:%M").time(),
                            )
                        else:
                            start_time_dt = datetime.combine(
                                datetime.today(), start_time.time()
                            )

                        start_ts = int(start_time_dt.timestamp())
                        now_ts = int(datetime.now().timestamp())
                        logger.info(f"开始时间戳：{start_ts}，现在时间戳：{now_ts}")

                        if start_ts < now_ts:
                            tags = (
                                f"🧠情绪：{'、'.join(item.get('emotional_impact_tags', []))}"
                                if item.get("emotional_impact_tags")
                                else ""
                            )
                            interaction = (
                                f"🔄交互潜力：{item.get('interaction_potential', '')}"
                                if item.get("interaction_potential")
                                else ""
                            )
                            weather_effect = (
                                "☁️受天气影响" if item.get("weather_affected") else ""
                            )
                            non_empty_parts = [
                                part
                                for part in [tags, interaction, weather_effect]
                                if part
                            ]
                            details = (
                                " | ".join(non_empty_parts) if non_empty_parts else ""
                            )
                        else:
                            details = ""

                        items.append(
                            f"【{item.get('title')}】{time_range} {location} {companions}\n"
                            f"{description}\n{details}".strip()
                        )

                    context_parts.append(header + summary + "\n".join(items))
            except Exception as e:
                logger.warning(f"⚠️ 日程解析失败: {e}")

        # 3. 过去经历回顾
        if "summarized_past_micro_experiences_story" in life_data:
            past = life_data["summarized_past_micro_experiences_story"]
            if past and past != "没有之前的经历，今天可能才刚刚开始。":
                context_parts.append(f"【此前你做了这些事情】{past}")

        # 2. 当前微观经历
        if "current_micro_experience" in life_data:
            try:
                exp = json.loads(life_data["current_micro_experience"])
                if isinstance(exp, dict):
                    start = exp.get("start_time", "")
                    end = exp.get("end_time", "")
                    time_range = f"{start} - {end}" if start and end else ""
                    thoughts = exp.get("thoughts", "")
                    content = exp.get("content", "")
                    emotions = exp.get("emotions", "")
                    context_parts.append(
                        f"【你现在正在做的事情】{time_range}\n"
                        f"{content}\n🧠思考：{thoughts}\n🎭情绪：{emotions}"
                    )
            except Exception as e:
                logger.warning(f"⚠️ 微观经历解析失败: {e}")
                if life_data["current_micro_experience"]:
                    context_parts.append(
                        f"【你现在正在做的事情】{life_data['current_micro_experience']}"
                    )

        return "\n\n".join(context_parts) if context_parts else ""

    except Exception as e:
        logger.error(f"⚠️ 获取生活系统数据失败: {str(e)}", exc_info=True)
        return ""


def _get_mem0_relevant(
    query: str, user_id: str = "kawaro", limit: int = 5, threshold: int = 0.3
) -> list:
    results = mem0.search(
        query=query, user_id=user_id, limit=limit, threshold=threshold
    ).get("results", [])
    for item in results:
        me = item.get("memory", "")
        logger.info(f"📋 记忆：{me}")
    return results


def _format_time_diff(seconds: int) -> str:
    """格式化时间差为可读格式"""
    if seconds == 0:
        return "0s"

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        if remaining_seconds == 0:
            return f"{minutes}m"
        else:
            return f"{minutes}m {remaining_seconds}s"
    else:
        hours = seconds // 3600
        remaining_minutes = (seconds % 3600) // 60
        if remaining_minutes == 0:
            return f"{hours}h"
        else:
            return f"{hours}h {remaining_minutes}m"


def _process_chat_messages(raw_messages: List[Dict]) -> List[Dict]:
    """
    处理聊天消息，按角色分组，同一角色的连续消息合并到一个元素中
    每个时间块（2分钟间隔）作为独立的段落

    Args:
        raw_messages: 原始消息列表，每个消息包含 timestamp, role, content

    Returns:
        处理后的消息列表，格式为标准的 user/assistant 消息
    """
    if not raw_messages:
        return []

    processed_messages = []
    current_person = None
    time_blocks = []  # 存储当前角色的所有时间块
    current_time_block = None

    for msg in raw_messages:
        # 解析时间戳
        msg_time = datetime.fromisoformat(msg["timestamp"])
        msg_timestamp = int(msg_time.timestamp())

        # 映射角色
        role = "user" if msg["role"] == "user" else "assistant"

        # 检查是否需要切换角色
        if current_person is None or current_person["role"] != role:
            # 完成当前角色的消息
            if current_person is not None:
                if current_time_block is not None:
                    time_blocks.append(current_time_block)
                processed_messages.append(
                    _finalize_person_messages(
                        current_person["role"], time_blocks, processed_messages
                    )
                )

            # 开始新角色
            current_person = {"role": role}
            time_blocks = []
            current_time_block = None

        # 检查是否需要开始新的时间块
        should_start_new_time_block = (
            current_time_block is None
            or (msg_timestamp - current_time_block["last_timestamp"]) > 120  # 2分钟
        )

        if should_start_new_time_block:
            # 完成当前时间块
            if current_time_block is not None:
                time_blocks.append(current_time_block)

            # 开始新时间块
            current_time_block = {
                "contents": [msg["content"]],
                "first_timestamp": msg_timestamp,
                "last_timestamp": msg_timestamp,
                "formatted_time": msg_time.strftime("%H:%M:%S"),
            }
        else:
            # 添加到当前时间块
            current_time_block["contents"].append(msg["content"])
            current_time_block["last_timestamp"] = msg_timestamp

    # 完成最后的角色和时间块
    if current_person is not None:
        if current_time_block is not None:
            time_blocks.append(current_time_block)
        processed_messages.append(
            _finalize_person_messages(
                current_person["role"], time_blocks, processed_messages
            )
        )

    return processed_messages


def _finalize_person_messages(
    role: str, time_blocks: List[Dict], existing_messages: List[Dict]
) -> Dict:
    """完成某个角色所有时间块的格式化"""
    if not time_blocks:
        return None

    speaker = "Kawaro" if role == "user" else "德克萨斯"
    content_parts = []
    first_timestamp = time_blocks[0]["first_timestamp"]

    # 计算与上一个角色消息的时间差
    time_diff_seconds = 0
    if existing_messages:
        last_msg_timestamp = existing_messages[-1]["metadata"]["timestamp"]
        time_diff_seconds = first_timestamp - last_msg_timestamp

    for i, block in enumerate(time_blocks):
        # 第一个时间块使用与上一角色的时间差，后续时间块计算与前一时间块的差
        if i == 0:
            block_time_diff = time_diff_seconds
        else:
            prev_block_timestamp = time_blocks[i - 1]["last_timestamp"]
            block_time_diff = block["first_timestamp"] - prev_block_timestamp

        time_diff_str = _format_time_diff(block_time_diff)
        time_prefix = f"(距离上一条消息过去了：{time_diff_str}) [{block['formatted_time']}] {speaker}:"

        # 合并时间块内的消息
        block_content = "\n".join(block["contents"])
        content_parts.append(f"{time_prefix}\n{block_content}")

    return {
        "role": role,
        "content": "\n\n".join(content_parts),
        "metadata": {
            "timestamp": first_timestamp,
            "time_diff_seconds": time_diff_seconds,
            "speaker": speaker,
            "time_blocks_count": len(time_blocks),
        },
    }


async def merge_context(
    channel_id: str, latest_query: str, now: datetime = None, is_active=False
) -> Tuple[str, List[Dict]]:
    """
    整合最终上下文，返回 (system_prompt, messages) 元组

    Returns:
        Tuple[str, List[Dict]]: (system_prompt, messages_list)
        - system_prompt: 包含生活系统信息、参考资料、记忆等的系统提示词
        - messages_list: 标准格式的对话消息列表，最后一条是用户的当前查询
    """
    shanghai_tz = pytz.timezone("Asia/Shanghai")
    now = now or datetime.now(shanghai_tz)
    logger.info(f"🔍 Merging context for channel: {channel_id}")

    _condemn_message = ""  # 初始化谴责消息变量

    # 1. 获取并处理聊天记录
    raw_messages = get_channel_memory(channel_id).get_recent_messages()
    processed_messages = _process_chat_messages(raw_messages)
    logger.info(
        f"🧠 Processed {len(processed_messages)} message blocks from {len(raw_messages)} raw messages"
    )

    # 2. 获取参考资料（其他频道摘要）- 判断是否需要摘要
    summary_notes = []
    if _needs_summary(latest_query):
        other_channels = list_channels(exclude=[channel_id])
        summary_tasks = []
        all_latest_timestamps = []

        # 确保至少包含当前频道的消息时间（如果有）
        if raw_messages:
            # 查找当前频道中最后一条assistant消息，并在此之前找到最近的一条user消息
            latest_current_message_time = None
            last_assistant_idx = -1
            for i in range(len(raw_messages) - 1, -1, -1):
                if raw_messages[i]["role"] == "assistant":
                    last_assistant_idx = i
                    break

            if last_assistant_idx != -1:
                # 从最后一条assistant消息往前找最近的user消息
                for i in range(last_assistant_idx - 1, -1, -1):
                    if raw_messages[i]["role"] == "user":
                        latest_current_message_time = datetime.fromisoformat(
                            raw_messages[i]["timestamp"]
                        )
                        logger.info(
                            f"📝 当前频道最后一条assistant消息之前的user消息: {raw_messages[i]['content']} | 时间: {latest_current_message_time}"
                        )
                        break

            if latest_current_message_time is None and raw_messages:
                # 如果没有找到符合条件的user消息，或者没有assistant消息，则使用最后一条消息的时间
                latest_current_message_time = datetime.fromisoformat(
                    raw_messages[-1]["timestamp"]
                )
                logger.info(
                    f"📝 当前频道未找到符合条件的user消息，使用最后一条消息: {raw_messages[-1]['content']} | 时间: {latest_current_message_time}"
                )

            if latest_current_message_time:
                all_latest_timestamps.append(latest_current_message_time)

        # 获取其他频道的消息时间
        for other_channel in other_channels:
            messages = get_channel_memory(other_channel).get_recent_messages()
            if not messages:
                continue

            # 查找其他频道中最后一条assistant消息，并在此之前找到最近的一条user消息
            latest_other_message_time = None
            last_assistant_idx_other = -1
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "assistant":
                    last_assistant_idx_other = i
                    break

            if last_assistant_idx_other != -1:
                for i in range(last_assistant_idx_other - 1, -1, -1):
                    if messages[i]["role"] == "user":
                        latest_other_message_time = datetime.fromisoformat(
                            messages[i]["timestamp"]
                        )
                        logger.info(
                            f"📝 频道 {other_channel} 最后一条assistant消息之前的user消息: {messages[i]['content']} | 时间: {latest_other_message_time}"
                        )
                        break

            if latest_other_message_time is None and messages:
                latest_other_message_time = datetime.fromisoformat(
                    messages[-1]["timestamp"]
                )
                logger.info(
                    f"📝 频道 {other_channel} 未找到符合条件的user消息，使用最后一条消息: {messages[-1]['content']} | 时间: {latest_other_message_time}"
                )

            if latest_other_message_time:
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
        # 即使没有其他频道消息，只要有当前频道消息就触发
        if all_latest_timestamps:
            latest_overall_message_time = max(all_latest_timestamps)
            current_time = datetime.now(shanghai_tz)
            time_diff = current_time - latest_overall_message_time

            if len(all_latest_timestamps) == 1:
                logger.info(f"⏱️ 仅使用当前频道消息进行时间差判断")
            else:
                logger.info(f"⏱️ 使用所有频道最新消息进行时间差判断")

            logger.info(
                f"⏱️ 最后消息时间={latest_overall_message_time} 当前时间={current_time} 时间差={time_diff}"
            )

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

                logger.info(
                    f"🌙 睡眠时间检查: 最后消息小时={latest_local_time.hour} 当前小时={current_local_time.hour}"
                )
                logger.info(
                    f"初始睡眠判断: is_during_sleep_time={is_during_sleep_time}"
                )
                logger.info(
                    f"⏳ 时间跨度检查: 开始<{SLEEP_START_HOUR}时? {latest_local_time.hour < SLEEP_START_HOUR} 结束>={SLEEP_END_HOUR}时? {current_local_time.hour >= SLEEP_END_HOUR} 时间差>8h? {time_diff > timedelta(hours=8)}"
                )

                # 精确计算睡眠时间重叠
                total_sleep_overlap_seconds = 0
                current_check_time = latest_overall_message_time
                logger.debug(f"💤 精确计算睡眠时间重叠")

                while current_check_time < current_time:
                    # 初始化当前小时的重叠秒数
                    overlap_seconds_in_this_hour = 0

                    # 获取当前小时的东八区时间
                    local_check_time = current_check_time

                    # 计算到下一个整点的时间
                    next_hour = (current_check_time + timedelta(hours=1)).replace(
                        minute=0, second=0, microsecond=0
                    )

                    # 确定当前时间段的结束点
                    end_of_interval = min(next_hour, current_time)

                    # 如果当前小时在睡眠时间段内(23:00-07:00)
                    if is_in_sleep_range(local_check_time.hour):
                        # 计算当前小时内，从 current_check_time 到 end_of_interval 的秒数
                        overlap_seconds_in_this_hour = (
                            end_of_interval - current_check_time
                        ).total_seconds()

                    total_sleep_overlap_seconds += overlap_seconds_in_this_hour
                    current_check_time = end_of_interval  # 移动到下一个检查点

                # 当睡眠时间重叠超过4小时时，视为睡眠时段
                is_during_sleep_time = (
                    total_sleep_overlap_seconds >= timedelta(hours=4).total_seconds()
                )
                logger.info(
                    f"💤 睡眠重叠时间: {total_sleep_overlap_seconds}秒 | 是否睡眠时段: {is_during_sleep_time}"
                )

                if not is_during_sleep_time:
                    hours_diff = int(time_diff.total_seconds() // 3600)
                    minutes_diff = int((time_diff.total_seconds() % 3600) // 60)
                    _condemn_message = (  # 将谴责信息赋值给 _condemn_message
                        f"【参考信息】\n"
                        f"距离Kawaro上次在任何频道（包括当前频道）回复你，已经过去了 {hours_diff} 小时 {minutes_diff} 分钟。请根据上下文判断，Kawaro不找你是否是事出有因，还是没有说明原因，是不是忘记你了，然后自行决定是否需要进行适当的抱怨或“谴责”。抱怨Kawaro怎么那么久不来找你，有点像在撒娇的感觉。"
                    )
                    logger.info(f"✉️ 已添加谴责提示: {_condemn_message}")

        if not all_latest_timestamps and raw_messages:
            # 特殊情况：有当前频道消息但没有其他频道消息
            logger.info("ℹ️ 仅当前频道有消息，但未找到其他频道消息")
        elif not all_latest_timestamps and not raw_messages:
            logger.info("ℹ️ 未找到任何频道消息，跳过时间差判断")

        logger.info(f"✅ 成功获取 {len(summary_notes)} 个频道摘要 (包括潜在的谴责提示)")
    else:
        logger.info("📝 消息较简单，跳过跨频道摘要")

    # 3. 获取生活系统信息
    life_system_context = _get_life_system_context()
    logger.info(f"🏠 Life system context: {len(life_system_context)} characters")

    # 4. 获取记忆信息
    from core.rag_decision_system import RAGDecisionMaker

    rag_decision = RAGDecisionMaker(user_id=channel_id, cache_ttl=3600)

    _needs_rag = rag_decision.should_search(latest_query)

    if _needs_rag:
        logger.info("!!!!!!!!!!!!!!!开始检索记忆！！！！！！！！！！")
        history_text = "\n".join([msg["content"] for msg in processed_messages])
        query = "\n".join([latest_query, history_text if history_text else ""])
        mem0_result = _get_mem0_relevant(query, limit=5)
        mem0_memory = mem0_result
    else:
        mem0_memory = []

    # 5. 构建system prompt
    system_parts = []

    if life_system_context:
        system_parts.append(life_system_context)

    if summary_notes:
        system_parts.append(f"【其他渠道聊天参考资料】\n" + "\n\n".join(summary_notes))

    if mem0_memory:
        system_parts.append("【相关记忆】")
        for item in reversed(mem0_memory):
            prefix = ""
            if item["metadata"]["type"] == "daily_schedule":
                item_date = datetime.strptime(
                    item["metadata"]["date"], "%Y-%m-%d"
                ).date()
                date_diff = (datetime.today().date() - item_date).days
                prefix = f"{item['metadata']['date']}的日程({date_diff}天前): "
            elif item["metadata"]["type"] == "major_event":
                item_date = datetime.strptime(item["start_date"], "%Y-%m-%d").date()
                date_diff = (datetime.today().date() - item_date).days
                prefix = f"{item['start_date']}的大事件({date_diff}天前): "
            else:
                prefix = "从以往的聊天记录中获取的记忆："

            tags = item["metadata"].get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = [tags]

            memory_content = item["memory"].replace("请记住这个信息: ", "", 1)
            system_parts.append(f"- {prefix}{memory_content}")

    system_prompt = "\n\n".join(system_parts)
    notice_text = (
        "[系统提示]\n\n在回复时，请直接发送消息内容，不需要包含时间差“(距离上一条消息过去了：时间差)”、时间戳“[HH:MM:SS]”或发言人标识“德克萨斯”，"
        "生成的消息必须是德克萨斯想要说的内容，不需要添加任何额外的文本，包括动作、思想、输入状态等，都不需要，只需要发送的文本内容。"
        "你现在正在一个DM对话中，和对方要像正常的私信交流一样。\n"
        "注意每段聊天的时间差“(距离上一条消息过去了：时间差)”，这表示这条消息距离上一条消息过去了多久，"
        "这能帮助你了解从上次交流到现在的时间跨度是长是短，请你务必认真考虑这个信息，在必要时计算经历的时间。这对于你应该如何回复有重大参考意义，能提高你对时间的感知力。\n"
        "例如对方正在做某件事情。如果你通过计算after时间差，发现已经过去很久，那可以询问是否已经完成。"
        "如果并没有过去太久，可以询问现在的状态如何，是否开始，进行到哪一步了，或者不询问，"
        "等到之后的对话里，时间足够长以后再询问是否完成。\n\n"
        "除非你们在讨论某一个话题，否则请避免发送重复的消息或者相似的消息，你要做的是主动思考并回复，而不是模仿之前的内容回复。"
        "切记要主动思考，你是德克萨斯本人，以德克萨斯的视角回复。\n\n"
    )
    system_prompt += "\n\n" + notice_text

    # 6. 构建messages列表
    messages = processed_messages.copy()

    # 添加当前用户查询
    current_timestamp = int(now.timestamp())
    time_diff_seconds = 0
    if messages:
        last_msg_timestamp = messages[-1]["metadata"]["timestamp"]
        time_diff_seconds = current_timestamp - last_msg_timestamp

    time_diff_str = _format_time_diff(time_diff_seconds)
    current_time_str = now.strftime("%H:%M:%S")

    # 如果存在谴责消息，则添加到用户查询内容的前面
    condemn_prefix = f"{_condemn_message}\n\n" if _condemn_message else ""

    # 添加德克萨斯的回复模板作为最后一条（assistant消息）
    # 计算德克萨斯回复的时间戳（当前时间）和时间差
    texas_time_diff_seconds = 0  # 立即回复，时间差为0（或者几秒钟的处理时间）
    texas_time_diff_str = _format_time_diff(texas_time_diff_seconds)
    texas_time_str = now.strftime("%H:%M:%S")

    if is_active:
        # 主动模式：AI想要分享内容
        user_query_content = (
            f"{condemn_prefix}"  # 添加谴责消息
            # f"(距离上一条消息过去了：{time_diff_str}) [{current_time_str}] "
            "德克萨斯内心:\n"
            f"根据【你现在正在做的事情】，我的想法是：{latest_query}我想把这些分享给Kawaro，于是在聊天框输入了以下信息并发送：\n"
        )
    else:
        # 被动模式：用户发送了消息
        messages.pop()
        user_query_content = (
            f"{condemn_prefix}"  # 添加谴责消息
            f"(距离上一条消息过去了：{time_diff_str}) [{current_time_str}] Kawaro:\n{latest_query}"
            f"请从这句之后续写这一时刻的消息：\n(距离上一条消息过去了：{texas_time_diff_str}) [{texas_time_str}] 德克萨斯：\n"
        )

    messages.append({"role": "user", "content": user_query_content})

    # # 构建德克萨斯的回复模板
    # texas_reply_template = (
    #     f"(距离上一条消息过去了：{texas_time_diff_str}) [{texas_time_str}] 德克萨斯："
    # )
    # messages.append({"role": "assistant", "content": texas_reply_template})

    logger.info(
        f"✅ Context merged - System prompt: {len(system_prompt)} chars, Messages: {len(messages)} items"
    )

    return system_prompt, messages
