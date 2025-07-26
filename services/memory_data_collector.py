import os
from datetime import datetime, timedelta
import pytz
from typing import List, Dict
import utils.postgres_service as pg_service # 导入为别名

class MemoryDataCollector:
    def __init__(self):
        # 不再需要实例化PostgresService，直接调用pg_service中的函数
        pass

    def get_unembedded_chats(self) -> List[Dict]:
        """获取未嵌入的聊天记录"""
        conn = pg_service.get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT id, channel_id, content, created_at 
                    FROM messages 
                    WHERE is_embedded = FALSE
                    ORDER BY created_at
                """
                cur.execute(query)
                columns = [desc[0] for desc in cur.description]
                results = []
                for row in cur.fetchall():
                    item = dict(zip(columns, row))
                    if 'created_at' in item and isinstance(item['created_at'], datetime):
                        item['created_at'] = item['created_at'].isoformat()
                    results.append(item)
                return results
        finally:
            conn.close()

    def get_yesterday_schedule_experiences(self) -> List[Dict]:
        """获取前一天的日程和微观经历，并关联大事件信息"""
        yesterday = (datetime.now(pytz.timezone('Asia/Shanghai')) - timedelta(days=1)).date()
        conn = pg_service.get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT 
                        s.id, 
                        s.schedule_data, 
                        m.experiences, 
                        s.is_in_major_event, 
                        s.major_event_id
                    FROM daily_schedules s
                    LEFT JOIN micro_experiences m ON s.id = m.daily_schedule_id
                    WHERE s.date = %s
                """
                cur.execute(query, (yesterday,))
                columns = [desc[0] for desc in cur.description]
                results = []
                for row in cur.fetchall():
                    item = dict(zip(columns, row))
                    
                    # 处理 datetime 对象
                    if 'created_at' in item and isinstance(item['created_at'], datetime):
                        item['created_at'] = item['created_at'].isoformat()
                    
                    # 如果日程在大事件中，获取大事件信息
                    if item.get('is_in_major_event') and item.get('major_event_id'):
                        major_event_info = pg_service.get_major_event_by_id(item['major_event_id'])
                        if major_event_info:
                            item['major_event_details'] = major_event_info
                    results.append(item)
                return results
        finally:
            conn.close()

    def get_major_events(self) -> List[Dict]:
        """检测和获取已结束的大事件数据"""
        yesterday = (datetime.now(pytz.timezone('Asia/Shanghai')) - timedelta(days=1)).date() # 使用上海时区
        conn = pg_service.get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT id, start_date, end_date, main_content
                    FROM major_events 
                    WHERE end_date = %s
                """
                cur.execute(query, (yesterday,))
                columns = [desc[0] for desc in cur.description]
                results = []
                for row in cur.fetchall():
                    item = dict(zip(columns, row))
                    if 'start_date' in item and isinstance(item['start_date'], datetime):
                        item['start_date'] = item['start_date'].isoformat()
                    if 'end_date' in item and isinstance(item['end_date'], datetime):
                        item['end_date'] = item['end_date'].isoformat()
                    if 'created_at' in item and isinstance(item['created_at'], datetime):
                        item['created_at'] = item['created_at'].isoformat()
                    results.append(item)
                return results
        finally:
            conn.close()

    def mark_chats_embedded(self, chat_ids: List[int]):
        """标记聊天记录为已嵌入"""
        if not chat_ids:
            return
        conn = pg_service.get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    UPDATE messages
                    SET is_embedded = TRUE, embedded_at = NOW()
                    WHERE id = ANY(%s)
                """
                cur.execute(query, (chat_ids,))
        finally:
            conn.close()

    def mark_schedule_embedded(self, schedule_id: str):
        """标记日程为已嵌入"""
        conn = pg_service.get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    UPDATE daily_schedules
                    SET is_embedded = TRUE, embedded_at = NOW()
                    WHERE id = %s
                """
                cur.execute(query, (schedule_id,))
        finally:
            conn.close()

    def mark_event_embedded(self, event_id: str):
        """标记大事件为已嵌入"""
        conn = pg_service.get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    UPDATE major_events
                    SET is_embedded = TRUE, embedded_at = NOW()
                    WHERE id = %s
                """
                cur.execute(query, (event_id,))
        finally:
            conn.close()
