"""
未来事件管理服务
负责事件的创建、更新、删除和提醒调度
"""

import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from utils.logging_config import get_logger

logger = get_logger(__name__)


class FutureEventManager:
    """未来事件管理器"""

    def __init__(self):
        from utils.postgres_service import (
            insert_future_event,
            get_future_event,
            get_active_future_events,
            update_future_event,
            mark_reminder_sent,
            cancel_future_event,
            get_upcoming_reminders,
            expire_past_events_db,
            archive_event_to_mem0
        )
        from utils.redis_manager import get_redis_client

        self.insert_event = insert_future_event
        self.get_event = get_future_event
        self.get_active_events_db = get_active_future_events
        self.update_event = update_future_event
        self.mark_sent = mark_reminder_sent
        self.cancel_event_db = cancel_future_event
        self.get_reminders = get_upcoming_reminders
        self.expire_events = expire_past_events_db
        self.archive_to_mem0 = archive_event_to_mem0

        self.redis = get_redis_client()

    async def create_event(
        self,
        event_data: Dict,
        channel_id: str,
        user_id: str,
        context_messages: List[Dict] = None
    ) -> Optional[str]:
        """
        创建新事件并调度提醒

        Args:
            event_data: 从AI提取的事件数据
            channel_id: 频道ID
            user_id: 用户ID
            context_messages: 对话上下文

        Returns:
            event_id 或 None
        """
        try:
            # 1. 计算提醒时间
            reminder_datetime = None
            if event_data.get('need_reminder') and event_data.get('event_date'):
                from services.event_extractor import calculate_reminder_datetime
                reminder_datetime = calculate_reminder_datetime(
                    event_data['event_date'],
                    event_data.get('event_time'),
                    event_data.get('reminder_advance_minutes', 30)
                )

            # 2. 准备数据库数据
            db_data = {
                'event_text': event_data['event_text'],
                'event_summary': event_data['event_summary'],
                'event_date': event_data.get('event_date'),
                'event_time': event_data.get('event_time'),
                'need_reminder': event_data.get('need_reminder', False),
                'reminder_datetime': reminder_datetime,
                'reminder_advance_minutes': event_data.get('reminder_advance_minutes', 30),
                'source_channel': channel_id,
                'created_by': user_id,
                'context_messages': context_messages or [],
                'extraction_confidence': event_data.get('confidence', 0.5),
                'metadata': event_data.get('metadata', {})
            }

            # 3. 插入数据库
            event_id = self.insert_event(db_data)

            if not event_id:
                logger.error("[event_manager] 插入数据库失败")
                return None

            logger.info(f"[event_manager] 事件已创建: {event_id} - {event_data['event_summary']}")

            # 4. 如果需要提醒，调度Celery任务
            if reminder_datetime:
                await self._schedule_reminder(event_id, reminder_datetime)

            # 5. 清除缓存
            self._invalidate_cache(user_id)

            return event_id

        except Exception as e:
            logger.error(f"[event_manager] 创建事件失败: {e}", exc_info=True)
            return None

    async def _schedule_reminder(self, event_id: str, reminder_datetime_str: str):
        """
        调度提醒任务（使用Celery ETA）

        Args:
            event_id: 事件ID
            reminder_datetime_str: 提醒时间（ISO格式字符串）
        """
        try:
            from tasks.reminder_tasks import send_reminder

            # 解析提醒时间
            reminder_time = datetime.fromisoformat(reminder_datetime_str)

            # 使用Celery的eta参数调度任务
            send_reminder.apply_async(
                args=[event_id],
                eta=reminder_time  # 在指定时间执行
            )

            logger.info(f"[event_manager] 提醒任务已调度: {event_id} at {reminder_time}")

        except Exception as e:
            logger.error(f"[event_manager] 调度提醒任务失败: {e}")

    async def update_event_data(
        self,
        event_id: str,
        updates: Dict
    ) -> bool:
        """
        更新事件数据

        如果修改了提醒时间，会重新调度提醒任务

        Args:
            event_id: 事件ID
            updates: 要更新的字段

        Returns:
            是否成功
        """
        try:
            # 1. 更新数据库
            success = self.update_event(event_id, updates)

            if not success:
                return False

            # 2. 如果修改了提醒时间，需要处理任务调度
            if 'reminder_datetime' in updates:
                # 取消旧任务（通过Redis标记）
                await self.redis.setex(
                    f"reminder_cancelled:{event_id}",
                    86400,  # 24小时过期
                    "1"
                )

                # 调度新任务
                new_reminder_time = updates['reminder_datetime']
                if new_reminder_time:
                    await self._schedule_reminder(event_id, new_reminder_time)

            logger.info(f"[event_manager] 事件已更新: {event_id}")
            return True

        except Exception as e:
            logger.error(f"[event_manager] 更新事件失败: {e}")
            return False

    async def cancel_event(self, event_id: str, reason: str = None) -> bool:
        """
        取消事件

        Args:
            event_id: 事件ID
            reason: 取消原因

        Returns:
            是否成功
        """
        try:
            # 1. 取消数据库中的事件
            success = self.cancel_event_db(event_id, reason)

            if not success:
                return False

            # 2. 取消提醒任务（通过Redis标记）
            await self.redis.setex(
                f"reminder_cancelled:{event_id}",
                86400,
                "1"
            )

            logger.info(f"[event_manager] 事件已取消: {event_id}")
            return True

        except Exception as e:
            logger.error(f"[event_manager] 取消事件失败: {e}")
            return False

    def get_active_events(self, user_id: str, days_ahead: int = 7) -> List[Dict]:
        """
        获取用户未来N天的活跃事件（带缓存）

        Args:
            user_id: 用户ID
            days_ahead: 未来多少天

        Returns:
            事件列表
        """
        cache_key = f"future_events:{user_id}:{days_ahead}"

        # 尝试从缓存读取
        cached = self.redis.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except:
                pass

        # 从数据库查询
        events = self.get_active_events_db(user_id, days_ahead)

        # 缓存5分钟
        self.redis.setex(cache_key, 300, json.dumps(events, default=str))

        return events

    def mark_reminder_sent(self, event_id: str) -> bool:
        """标记提醒已发送"""
        return self.mark_sent(event_id)

    def _invalidate_cache(self, user_id: str):
        """清除用户的事件缓存"""
        try:
            # 删除所有相关缓存
            pattern = f"future_events:{user_id}:*"
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
        except Exception as e:
            logger.warning(f"[event_manager] 清除缓存失败: {e}")

    async def expire_and_archive_events(self) -> int:
        """
        标记过期事件并归档到Mem0

        Returns:
            归档的事件数量
        """
        try:
            # 1. 标记过期事件
            expired_events = self.expire_events()

            if not expired_events:
                logger.debug("[event_manager] 没有需要归档的过期事件")
                return 0

            logger.info(f"[event_manager] 找到 {len(expired_events)} 个过期事件")

            # 2. 归档到Mem0
            archived_count = 0
            for event in expired_events:
                try:
                    # 获取完整事件数据
                    full_event = self.get_event(event['id'])
                    if not full_event:
                        continue

                    # 归档到Mem0
                    success = await self._archive_event(full_event)
                    if success:
                        archived_count += 1

                except Exception as e:
                    logger.error(f"[event_manager] 归档事件失败: {event['id']} - {e}")

            logger.info(f"[event_manager] 已归档 {archived_count} 个事件到Mem0")
            return archived_count

        except Exception as e:
            logger.error(f"[event_manager] 过期和归档流程失败: {e}")
            return 0

    async def _archive_event(self, event: Dict) -> bool:
        """
        将事件归档到Mem0

        Args:
            event: 事件数据

        Returns:
            是否成功
        """
        try:
            from utils.mem0_service import mem0

            # 构建记忆文本
            date_str = event['event_date'].strftime("%Y年%m月%d日") if event.get('event_date') else "未指定日期"
            time_str = f" {event['event_time'].strftime('%H:%M')}" if event.get('event_time') else ""

            memory_text = (
                f"在{date_str}{time_str}，kawaro{event['event_summary']}。"
                f"原始描述：{event['event_text']}"
            )

            # 添加到Mem0
            memory_id = await mem0.add_memory(
                messages=[{"role": "user", "content": memory_text}],
                user_id=event['created_by']
            )

            # 更新数据库
            self.archive_to_mem0(event['id'], memory_id)

            logger.info(f"[event_manager] 事件已归档到Mem0: {event['id']} -> {memory_id}")
            return True

        except Exception as e:
            logger.error(f"[event_manager] 归档到Mem0失败: {e}")
            return False


# 全局实例
future_event_manager = FutureEventManager()
