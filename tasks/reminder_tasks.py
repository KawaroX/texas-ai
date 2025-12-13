"""
未来事件提醒任务
使用Celery ETA实现精确的提醒调度
"""

import asyncio
import json
from datetime import datetime, timedelta
from celery import shared_task
from utils.logging_config import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3)
def send_reminder(self, event_id: str):
    """
    发送单个事件提醒

    Args:
        event_id: 事件ID

    Note:
        - 使用bind=True可以访问self.retry()
        - max_retries=3表示最多重试3次
        - 任务通过apply_async(eta=...)调度，在指定时间执行
    """
    from utils.redis_manager import get_redis_client
    from services.future_event_manager import future_event_manager

    redis_client = get_redis_client()

    logger.info(f"[reminder_task] 开始发送提醒: {event_id}")

    try:
        # 1. 检查是否已取消
        cancelled = redis_client.get(f"reminder_cancelled:{event_id}")
        if cancelled:
            logger.info(f"[reminder_task] 提醒已取消: {event_id}")
            redis_client.delete(f"reminder_cancelled:{event_id}")
            return {"status": "cancelled", "event_id": event_id}

        # 2. 获取事件数据
        event = future_event_manager.get_event(event_id)

        if not event:
            logger.warning(f"[reminder_task] 事件不存在: {event_id}")
            return {"status": "not_found", "event_id": event_id}

        # 3. 检查是否已发送
        if event.get('reminder_sent'):
            logger.info(f"[reminder_task] 提醒已发送过: {event_id}")
            return {"status": "already_sent", "event_id": event_id}

        # 4. 检查事件状态
        if event.get('status') not in ['pending', 'active']:
            logger.info(f"[reminder_task] 事件状态不允许提醒: {event_id} - {event['status']}")
            return {"status": "invalid_status", "event_id": event_id}

        # 5. 使用异步事件循环发送提醒
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_reminder_async(event))
        finally:
            loop.close()

        # 6. 标记已发送
        future_event_manager.mark_reminder_sent(event_id)

        logger.info(f"[reminder_task] 提醒发送成功: {event_id}")
        return {"status": "sent", "event_id": event_id, "message": result}

    except Exception as e:
        logger.error(f"[reminder_task] 发送提醒失败: {event_id} - {e}", exc_info=True)

        # 重试机制
        if self.request.retries < self.max_retries:
            # 1分钟后重试
            raise self.retry(exc=e, countdown=60)
        else:
            logger.error(f"[reminder_task] 重试次数已达上限: {event_id}")
            return {"status": "failed", "event_id": event_id, "error": str(e)}


async def _send_reminder_async(event: dict) -> str:
    """
    异步发送提醒消息

    Args:
        event: 事件数据

    Returns:
        发送的消息文本
    """
    # 1. 生成提醒消息
    reminder_message = await _generate_reminder_message(event)

    # 2. 发送到Mattermost频道
    from app.mattermost_client import MattermostWebSocketClient

    ws_client = MattermostWebSocketClient()

    # 确保bot user ID已获取
    if ws_client.user_id is None:
        await ws_client.fetch_bot_user_id()

    # 发送消息
    channel_id = event['source_channel']
    await ws_client.send_message(channel_id, reminder_message)

    logger.info(f"[reminder_task] 消息已发送到频道: {channel_id}")

    return reminder_message


async def _generate_reminder_message(event: dict) -> str:
    """
    AI生成自然的提醒消息

    Args:
        event: 事件数据

    Returns:
        提醒消息文本
    """
    # 计算距离事件多久
    time_desc = _calculate_time_description(event)

    # 使用AI生成自然的提醒
    from services.ai_service import call_openai

    prompt = f"""你是德克萨斯，需要提醒kawaro一件事。

事件信息：
- 事件：{event['event_summary']}
- 时间：{time_desc}
- 原始描述：{event['event_text']}

请生成一条自然、简洁的提醒消息，符合德克萨斯的性格（冷静、专业、关心但不过分热情）。

要求：
- 1-2句话
- 不要过于正式，像朋友提醒一样
- 可以加一句关心或鼓励的话（可选）
- 直接输出消息内容，不要任何额外标记

示例：
- "kawaro，再过30分钟就要考试了，记得带准考证。"
- "提醒一下，今晚九点你说要去喝酒的，别忘了。"
- "马上到约定的时间了，准备好了吗？"

直接输出提醒消息："""

    try:
        reminder_text = await call_openai(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini"
        )
        return reminder_text.strip()

    except Exception as e:
        logger.error(f"[reminder_task] AI生成提醒失败: {e}")
        # Fallback到简单模板
        return f"提醒：{event['event_summary']}（{time_desc}）"


def _calculate_time_description(event: dict) -> str:
    """
    计算时间描述

    Args:
        event: 事件数据

    Returns:
        时间描述文本
    """
    if not event.get('event_date'):
        return "即将发生"

    try:
        # 构建事件时间
        if event.get('event_time'):
            event_datetime = datetime.combine(
                event['event_date'],
                event['event_time']
            )
        else:
            event_datetime = datetime.combine(
                event['event_date'],
                datetime.min.time()
            )

        # 计算时间差
        now = datetime.now()
        time_delta = event_datetime - now

        # 生成描述
        if time_delta.total_seconds() < 0:
            return "现在"
        elif time_delta.total_seconds() < 3600:  # 1小时内
            minutes = int(time_delta.total_seconds() / 60)
            return f"{minutes}分钟后"
        elif time_delta.total_seconds() < 86400:  # 24小时内
            hours = int(time_delta.total_seconds() / 3600)
            return f"{hours}小时后"
        else:
            days = time_delta.days
            if days == 1:
                return "明天"
            else:
                return f"{days}天后"

    except Exception as e:
        logger.error(f"[reminder_task] 计算时间描述失败: {e}")
        return "即将发生"


@shared_task
def expire_past_events_task():
    """
    定期任务：标记过期事件并归档到Mem0
    每天凌晨0:05执行一次
    """
    from services.future_event_manager import future_event_manager

    logger.info("[reminder_task] 开始执行过期事件归档任务")

    try:
        # 使用异步事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            archived_count = loop.run_until_complete(
                future_event_manager.expire_and_archive_events()
            )
        finally:
            loop.close()

        logger.info(f"[reminder_task] 过期事件归档完成: {archived_count} 个")
        return {"archived_count": archived_count}

    except Exception as e:
        logger.error(f"[reminder_task] 过期事件归档失败: {e}", exc_info=True)
        return {"error": str(e)}
