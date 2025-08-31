import json
import logging
import redis
import os
from datetime import datetime
from typing import List
from celery import shared_task
from app.config import settings
from app.mattermost_client import MattermostWebSocketClient
from core.context_merger import merge_context

logger = logging.getLogger(__name__)

# 初始化 Redis 客户端
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)

# 图片生成任务中定义的 Redis Key，用于存储 interaction_id -> image_path 的映射
PROACTIVE_IMAGES_KEY = "proactive_interaction_images"


@shared_task
def process_scheduled_interactions():
    """
    Celery 任务：处理需要主动交互的事件。
    每分钟执行一次，检查 Redis 中到期的 interaction_needed 事件。
    """
    logger.info("[interactions] 启动定时主动交互任务")
    current_timestamp = datetime.now().timestamp()
    logger.debug(f"[interactions] 当前时间戳: {current_timestamp}")

    # 假设 interaction_needed 的 key 是 interaction_needed:{YYYY-MM-DD}
    today_key = f"interaction_needed:{datetime.now().strftime('%Y-%m-%d')}"

    # 如果 Redis 中没有该 key，先触发一次采集请求
    if not redis_client.exists(today_key):
        logger.warning(f"⚠️ Redis 中不存在 key: {today_key}，将尝试采集交互事件")
        try:
            import httpx

            response = httpx.get("http://bot:8000/collect-interactions", timeout=10.0)
            logger.debug(f"[interactions] 采集接口返回状态: {response.status_code}")
            if response.status_code != 200:
                logger.warning("⚠️ 采集接口未成功响应，后续可能仍无数据")
        except Exception as e:
            logger.error(f"❌ 请求采集接口失败: {e}")

    # 获取所有到期事件
    expired_events = redis_client.zrangebyscore(today_key, 0, current_timestamp)

    if not expired_events:
        logger.debug(f"[interactions] {today_key} 中没有到期的主动交互事件")
        return

    logger.debug(f"[interactions] 到期的主动交互事件数量: {len(expired_events)}")

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

    logger.info("[interactions] 定时主动交互任务完成")


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

    try:
        kawaro_dm_channel_id = await ws_client.create_direct_channel(kawaro_user_id)
        if not kawaro_dm_channel_id:
            logger.error("❌ 无法获取或创建与 'kawaro' 的私聊频道。")
            return
    except Exception as e:
        logger.error(f"❌ 获取 'kawaro' 私聊频道时发生错误: {e}")
        return

    logger.debug(f"[interactions] 已获取 'kawaro' 私聊频道 ID: {kawaro_dm_channel_id}")

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
            logger.debug(
                f"[interactions] Processing interaction content: {interaction_content}"
            )

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
                logger.debug(f"[interactions] 事件 {experience_id} 已交互过，跳过。")
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
                logger.debug(
                    f"[interactions] 事件 {experience_id} 不在当前时间范围内 ({start_time_str}-{end_time_str})，跳过"
                )
                print(f"DEBUG: 事件 {experience_id} 时间不匹配，跳过")
                # 不从 Sorted Set 中移除，等待下次到期或进入时间范围
                continue

            logger.debug(
                f"[interactions] 处理事件: {interaction_content[:50]}... (ID: {experience_id})"
            )
            print(f"DEBUG: 开始处理事件 {experience_id}")

            kawaro_info = await ws_client.get_kawaro_user_and_dm_info()
            kawaro_user_id = kawaro_info["user_id"]
            kawaro_user_info = kawaro_info["user_info"]
            kawaro_dm_channel_id = await ws_client.create_direct_channel(kawaro_user_id)
            kawaro_channel_info = kawaro_info["channel_info"]
            logger.debug(f"[interactions] Kawaro 用户信息: {kawaro_user_info}")
            logger.debug(f"[interactions] Kawaro 频道信息: {kawaro_channel_info}")

            context = await merge_context(
                channel_id=kawaro_dm_channel_id,
                latest_query=interaction_content,
                is_active=True,
            )

            # logger.info(f"Context:\n {context[0][:100]}...")

            # 检查是否有预生成的图片与此事件关联
            image_path = redis_client.hget(PROACTIVE_IMAGES_KEY, experience_id)
            has_image = image_path and os.path.exists(image_path)
            
            if has_image:
                logger.info(f"[interactions] 找到关联图片: {image_path}，将发送带图片的消息")
                
                try:
                    # 先生成AI回复内容
                    from services.ai_service import stream_ai_chat
                    from core.persona import PersonaManager
                    
                    persona_manager = PersonaManager()
                    
                    # 使用现有的AI服务生成回复
                    messages = [{"role": "user", "content": interaction_content}]
                    # 如果有上下文信息，添加到系统消息中
                    if context:
                        system_prompt, chat_messages = context
                        if system_prompt:
                            messages.insert(0, {"role": "system", "content": system_prompt})
                        messages.extend(chat_messages)
                    
                    # 使用流式API生成内容并拼接
                    ai_response_parts = []
                    async for chunk in stream_ai_chat(messages):
                        ai_response_parts.append(chunk)
                    ai_response = "".join(ai_response_parts)
                    
                    if ai_response and ai_response.strip():
                        # 应用persona过滤
                        filtered_response = persona_manager.apply_persona_filter(ai_response)
                        
                        try:
                            # 尝试发送带图片的消息
                            await ws_client.post_message_with_image(
                                channel_id=kawaro_dm_channel_id,
                                message=filtered_response,
                                image_path=image_path
                            )
                            
                            # 成功发送后从Redis中移除已使用的图片映射
                            redis_client.hdel(PROACTIVE_IMAGES_KEY, experience_id)
                            logger.info(f"[interactions] ✅ 成功发送带图片的主动交互消息，移除图片映射: {experience_id}")
                            
                        except Exception as img_send_error:
                            logger.error(f"❌ 发送图片消息失败，降级为纯文本消息: {img_send_error}")
                            # 降级处理：发送纯文本消息
                            await ws_client.send_message(kawaro_dm_channel_id, filtered_response)
                            # 清理无效的图片映射
                            redis_client.hdel(PROACTIVE_IMAGES_KEY, experience_id)
                            logger.info(f"[interactions] 📝 降级发送纯文本消息成功，已清理图片映射: {experience_id}")
                            
                    else:
                        logger.warning(f"[interactions] AI未生成有效回复，使用默认消息发送方式")
                        # 清理图片映射，因为无法生成对应的消息内容
                        redis_client.hdel(PROACTIVE_IMAGES_KEY, experience_id)
                        await ws_client.send_ai_generated_message(
                            channel_id=kawaro_dm_channel_id,
                            processed_messages=[interaction_content],
                            context_info=context,
                            channel_info=kawaro_channel_info,
                            user_info=kawaro_user_info,
                            is_active_interaction=True,
                        )
                        
                except Exception as ai_error:
                    logger.error(f"❌ AI服务调用失败，使用默认消息发送方式: {ai_error}")
                    # 清理图片映射
                    redis_client.hdel(PROACTIVE_IMAGES_KEY, experience_id)
                    await ws_client.send_ai_generated_message(
                        channel_id=kawaro_dm_channel_id,
                        processed_messages=[interaction_content],
                        context_info=context,
                        channel_info=kawaro_channel_info,
                        user_info=kawaro_user_info,
                        is_active_interaction=True,
                    )
            else:
                # 没有图片，使用原有的消息发送方式
                if image_path:
                    logger.warning(f"[interactions] 图片文件不存在: {image_path}，但保留映射（图片文件永久保留策略）")
                
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
            logger.debug(
                f"[interactions] 成功处理并发送主动交互消息，已从 Redis 移除事件: {experience_id}"
            )
            print(f"DEBUG: 成功处理事件 {experience_id}，已添加到交互记录")

        except json.JSONDecodeError as e:
            logger.error(f"❌ 解析事件 JSON 失败，跳过: {event_json_str} - {e}")
        except Exception as e:
            logger.error(f"❌ 处理主动交互事件时发生错误: {event_json_str} - {e}")
            # 考虑是否需要重试机制或将失败事件放入死信队列

    logger.info(f"[interactions] 主动交互处理完成 count={processed_count}")
