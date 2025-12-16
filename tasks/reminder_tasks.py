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

    # 判断提醒类型（用于给AI更明确的指导）
    if time_desc in ["现在", "马上"]:
        reminder_type = "即时提醒"
        hint = "时间已到，应该提醒kawaro立即行动"
    elif "分钟" in time_desc:
        try:
            minutes = int(time_desc.replace("还有", "").replace("分钟", ""))
            if minutes <= 10:
                reminder_type = "临近提醒"
                hint = "时间快到了，提醒kawaro准备"
            else:
                reminder_type = "提前提醒"
                hint = "提醒kawaro注意即将到来的事件"
        except:
            reminder_type = "提前提醒"
            hint = "提醒kawaro注意即将到来的事件"
    else:
        reminder_type = "提前提醒"
        hint = "提醒kawaro注意即将到来的事件"

    # 使用AI生成自然的提醒
    from services.ai_service import call_openai

    prompt = f"""你是德克萨斯，现在是【提醒触发时刻】，需要提醒kawaro一件事。

【提醒场景】
- 提醒类型：{reminder_type}
- 事件：{event['event_summary']}
- 距离事件时间：{time_desc}
- 用户原话：{event['event_text']}

【指导说明】
{hint}

【要求】
- 1-2句话，简洁自然
- 符合德克萨斯的性格：冷静、专业、关心但不过分热情
- 根据距离事件的时间调整措辞：
  * 如果是"现在"或"马上"：直接催促行动，如"时间到了，该吃饭了"
  * 如果是"还有X分钟"（≤10分钟）：提醒准备，如"快到时间了，准备一下吧"
  * 如果是更长时间：提前通知，如"再过30分钟该吃饭了，记得准备"
- 直接输出消息内容，不要任何额外标记

【示例】
场景1（即时提醒，距离0-2分钟）：
- "时间到了，该吃饭了。"
- "kawaro，该去做那件事了。"

场景2（临近提醒，距离3-10分钟）：
- "再过5分钟就该吃饭了，准备一下吧。"
- "快到约定的时间了，准备好了吗？"

场景3（提前提醒，距离>10分钟）：
- "kawaro，再过30分钟就要考试了，记得带准考证。"
- "提醒一下，今晚九点你说要去喝酒的，别忘了。"

直接输出提醒消息："""

    try:
        reminder_text = await call_openai(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini"
        )
        return reminder_text.strip()

    except Exception as e:
        logger.error(f"[reminder_task] AI生成提醒失败: {e}")
        # Fallback到智能模板
        if time_desc in ["现在", "马上"]:
            return f"时间到了，该{event['event_summary']}了。"
        elif "分钟" in time_desc:
            return f"{time_desc}就该{event['event_summary']}了，准备一下吧。"
        else:
            return f"提醒：{event['event_summary']}（{time_desc}）"


def _calculate_time_description(event: dict) -> str:
    """
    计算时间描述（用于提醒消息生成）

    Args:
        event: 事件数据

    Returns:
        包含提醒语境的时间描述
    """
    if not event.get('event_date'):
        return "即将"

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

        # 计算剩余时间
        now = datetime.now()
        time_delta = event_datetime - now
        total_seconds = time_delta.total_seconds()

        # 根据剩余时间生成不同的描述
        if total_seconds <= 0:
            # 事件时间已到或已过
            return "现在"
        elif total_seconds <= 300:  # ≤5分钟
            # 即时提醒：时间几乎到了
            minutes = max(1, int(total_seconds / 60))
            if minutes <= 1:
                return "马上"
            else:
                return f"还有{minutes}分钟"
        elif total_seconds <= 1800:  # 5-30分钟
            # 临近提醒
            minutes = int(total_seconds / 60)
            return f"还有{minutes}分钟"
        elif total_seconds < 3600:  # 30分钟-1小时
            # 提前提醒
            minutes = int(total_seconds / 60)
            return f"还有{minutes}分钟"
        elif total_seconds < 86400:  # 1-24小时
            hours = int(total_seconds / 3600)
            return f"还有{hours}小时"
        else:
            # 超过1天
            days = time_delta.days
            if days == 1:
                return "明天"
            else:
                return f"{days}天后"

    except Exception as e:
        logger.error(f"[reminder_task] 计算时间描述失败: {e}")
        return "即将"


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
