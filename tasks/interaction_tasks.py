import asyncio
import json
import logging
import redis
from datetime import datetime
from typing import List
from celery import shared_task
from app.config import settings
from app.mattermost_client import MattermostWebSocketClient
from core.context_merger import merge_context
from core.memory_buffer import get_channel_memory  # 假设需要记录主动交互的聊天记录

logger = logging.getLogger(__name__)

# 初始化 Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


@shared_task
def process_scheduled_interactions():
    """
    Celery 任务：处理需要主动交互的事件。
    每分钟执行一次，检查 Redis 中到期的 interaction_needed 事件。
    """
    logger.info("🚀 启动 process_scheduled_interactions Celery 任务...")
    current_timestamp = datetime.now().timestamp()
    logger.info(f"当前时间戳: {current_timestamp}!!!!!!!!!!!!!!!!!")

    # 假设 interaction_needed 的 key 是 interaction_needed:{YYYY-MM-DD}
    today_key = f"interaction_needed:{datetime.now().strftime('%Y-%m-%d')}"

    # 如果 Redis 中没有该 key，先触发一次采集请求
    if not redis_client.exists(today_key):
        logger.warning(f"⚠️ Redis 中不存在 key: {today_key}，将尝试采集交互事件")
        try:
            import httpx

            response = httpx.get("http://bot:8000/collect-interactions", timeout=10.0)
            logger.info(f"📡 请求采集接口返回状态: {response.status_code}")
            if response.status_code != 200:
                logger.warning("⚠️ 采集接口未成功响应，后续可能仍无数据")
        except Exception as e:
            logger.error(f"❌ 请求采集接口失败: {e}")

    # 获取所有到期事件
    expired_events = redis_client.zrangebyscore(today_key, 0, current_timestamp)

    if not expired_events:
        logger.info(f"ℹ️ {today_key} 中没有到期的主动交互事件。")
        return

    logger.info(f"✅ 发现 {len(expired_events)} 个到期的主动交互事件。")

    # 实例化 MattermostWebSocketClient
    ws_client = MattermostWebSocketClient()

    # 使用新的事件循环来运行异步代码
    try:
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _process_events_async(ws_client, today_key, expired_events)
            )
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"❌ 运行异步任务时发生错误: {e}")

    logger.info("✅ process_scheduled_interactions Celery 任务执行完毕。")


async def _process_events_async(
    ws_client: MattermostWebSocketClient, redis_key: str, events: List[str]
):
    """
    异步处理到期的主动交互事件。
    """
    # 确保 bot user ID 已获取，这是 Mattermost 客户端操作的前提
    if ws_client.user_id is None:
        await ws_client.fetch_bot_user_id()
        if ws_client.user_id is None:
            logger.error("❌ 无法获取 BOT user ID，跳过主动交互事件处理。")
            return

    # 获取 kawaro 的用户 ID 和私聊频道 ID
    kawaro_user_id = None
    kawaro_dm_channel_id = None

    users_data = ws_client.redis_client.hgetall("mattermost:users")
    for user_id, user_json in users_data.items():
        user_info = json.loads(user_json)
        if user_info.get("username") == "kawaro":
            kawaro_user_id = user_id
            break

    if not kawaro_user_id:
        logger.error("❌ 未找到 'kawaro' 用户 ID，无法发送主动交互消息。")
        return

    # 尝试获取或创建与 kawaro 的私聊频道
    # send_dm_to_kawaro 内部已经包含了创建或获取私聊频道的逻辑
    # 这里需要一个方法来直接获取 channel_id 而不是发送消息
    # 可以在 MattermostWebSocketClient 中添加一个 get_dm_channel_id 方法

    # 临时方案：复用 send_dm_to_kawaro 的部分逻辑来获取 channel_id
    # 更好的做法是 MattermostWebSocketClient 提供一个 create_or_get_direct_channel 方法

    # 假设 MattermostWebSocketClient 已经有一个 create_direct_channel 方法
    # 或者我们直接调用 send_dm_to_kawaro 的内部逻辑

    # 为了避免重复代码，我们可以在 MattermostWebSocketClient 中添加一个辅助方法
    # async def _get_kawaro_dm_channel_id(self):
    #     # ... 提取 send_dm_to_kawaro 中的逻辑 ...
    #     return channel_id

    # 这里先直接调用 send_dm_to_kawaro，但只为了获取 channel_id，不发送消息
    # 这是一个临时的、不优雅的解决方案，后续需要优化 MattermostWebSocketClient

    # 优化：直接调用 MattermostWebSocketClient 内部的 create_direct_channel
    # 假设 MattermostWebSocketClient 已经有这个方法
    try:
        kawaro_dm_channel_id = await ws_client.create_direct_channel(kawaro_user_id)
        if not kawaro_dm_channel_id:
            logger.error(f"❌ 无法获取或创建与 'kawaro' 的私聊频道。")
            return
    except Exception as e:
        logger.error(f"❌ 获取 'kawaro' 私聊频道时发生错误: {e}")
        return

    logger.info(f"✅ 已获取 'kawaro' 的私聊频道 ID: {kawaro_dm_channel_id}")

    # 辅助函数：将 HH:MM 格式的时间字符串转换为当天的 datetime 对象
    def time_str_to_datetime(date_obj: datetime.date, time_str: str) -> datetime:
        dt_str = f"{date_obj.strftime('%Y-%m-%d')} {time_str}"
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

    # 获取当天日期，用于构建 interacted_schedule_items key
    today_date = datetime.now().date()
    interacted_key = f"interacted_schedule_items:{today_date.strftime('%Y-%m-%d')}"

    processed_count = 0
    for event_json_str in events:
        try:
            event_data = json.loads(event_json_str)
            interaction_content = event_data.get("interaction_content")
            logger.info(f"Processing interaction content: {interaction_content}")

            experience_id = event_data.get("id")  # 使用微观经历的唯一ID
            start_time_str = event_data.get("start_time")
            end_time_str = event_data.get("end_time")

            if not (
                interaction_content
                and experience_id
                and start_time_str
                and end_time_str
            ):
                logger.warning(f"⚠️ 事件数据缺少必要字段，跳过: {event_json_str}")
                print(
                    f"DEBUG: 缺少字段 - interaction_content: {bool(interaction_content)}, experience_id: {bool(experience_id)}, start_time: {bool(start_time_str)}, end_time: {bool(end_time_str)}"
                )
                continue  # 不删除事件，保留以便后续重试

            # 检查是否已交互过
            if redis_client.sismember(interacted_key, experience_id):
                logger.info(f"ℹ️ 事件 {experience_id} 已交互过，跳过。")
                print(f"DEBUG: 事件 {experience_id} 已在交互记录中")
                # 仍然从 Sorted Set 中移除，因为已经处理过（即使是之前处理的）
                redis_client.zrem(redis_key, event_json_str)
                continue

            # 检查当前时间是否在事件的 start_time 和 end_time 之间
            current_time = datetime.now()
            event_start_dt = time_str_to_datetime(today_date, start_time_str)
            event_end_dt = time_str_to_datetime(today_date, end_time_str)

            print(
                f"DEBUG: 时间检查 - 当前时间: {current_time}, 事件开始: {event_start_dt}, 事件结束: {event_end_dt}"
            )

            if not (event_start_dt <= current_time < event_end_dt):
                logger.info(
                    f"ℹ️ 事件 {experience_id} 不在当前时间范围内 ({start_time_str}-{end_time_str})，跳过。"
                )
                print(f"DEBUG: 事件 {experience_id} 时间不匹配，跳过")
                # 不从 Sorted Set 中移除，等待下次到期或进入时间范围
                continue

            logger.info(
                f"处理事件: {interaction_content[:50]}... (ID: {experience_id})"
            )
            print(f"DEBUG: 开始处理事件 {experience_id}")

            kawaro_info = await ws_client.get_kawaro_user_and_dm_info()
            kawaro_user_id = kawaro_info["user_id"]
            kawaro_user_info = kawaro_info["user_info"]
            kawaro_dm_channel_id = await ws_client.create_direct_channel(kawaro_user_id)
            kawaro_channel_info = kawaro_info["channel_info"]
            logger.info(f"Kawaro 用户信息: {kawaro_user_info}")
            logger.info(f"Kawaro 频道信息: {kawaro_channel_info}")

            context = await merge_context(
                channel_id=kawaro_dm_channel_id,
                latest_query=interaction_content,
            )

            logger.info(f"Context: {context}")

            await ws_client.send_ai_generated_message(
                channel_id=kawaro_dm_channel_id,
                processed_messages=[interaction_content],
                context_info=context,
                channel_info=kawaro_channel_info,
                user_info=kawaro_user_info,
                is_active_interaction=True,
            )

            # 成功处理后，从 Redis Sorted Set 中移除该事件
            redis_client.zrem(redis_key, event_json_str)
            # 将 experience_id 添加到已交互 Set 中，并设置过期时间与 interaction_needed 相同
            redis_client.sadd(interacted_key, experience_id)
            redis_client.expire(interacted_key, 86400)  # 24小时过期

            processed_count += 1
            logger.info(
                f"✅ 成功处理并发送主动交互消息，并从 Redis 移除事件: {experience_id}"
            )
            print(f"DEBUG: 成功处理事件 {experience_id}，已添加到交互记录")

        except json.JSONDecodeError as e:
            logger.error(f"❌ 解析事件 JSON 失败，跳过: {event_json_str} - {e}")
        except Exception as e:
            logger.error(f"❌ 处理主动交互事件时发生错误: {event_json_str} - {e}")
            # 考虑是否需要重试机制或将失败事件放入死信队列

    logger.info(f"✨ 成功处理了 {processed_count} 个主动交互事件。")
