from utils.logging_config import get_logger

logger = get_logger(__name__)

import psycopg2
import json
from psycopg2 import sql
from app.config import settings


def get_db_connection():
    """
    获取数据库连接
    """
    try:
        conn = psycopg2.connect(
            dbname=settings.POSTGRES_DB,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host="db",  # 容器内部用服务名连接
            port=5432,
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"数据库连接失败: {e}")
        raise


def insert_messages(messages):
    """
    messages: List of tuples (channel_id, role, content, timestamp)
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO messages (channel_id, role, content, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                messages,
            )
    finally:
        conn.close()


# --- daily_schedules 表操作 ---
def insert_daily_schedule(
    date: str,
    schedule_data: dict,
    weather: str,
    is_in_major_event: bool = False,
    major_event_id: str = None,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_schedules (date, schedule_data, weather, is_in_major_event, major_event_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    date,
                    json.dumps(schedule_data, ensure_ascii=False),
                    weather,
                    is_in_major_event,
                    major_event_id,
                ),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_daily_schedule_by_date(date: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, date, schedule_data, weather, is_in_major_event, major_event_id, created_at, updated_at
                FROM daily_schedules
                WHERE date = %s;
                """,
                (date,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "date": row[1].strftime("%Y-%m-%d"),
                    "schedule_data": row[2],
                    "weather": row[3],
                    "is_in_major_event": row[4],
                    "major_event_id": row[5],
                    "created_at": row[6].isoformat(),
                    "updated_at": row[7].isoformat(),
                }
            return None
    finally:
        conn.close()


def update_daily_schedule(
    schedule_id: str,
    schedule_data: dict = None,
    weather: str = None,
    is_in_major_event: bool = None,
    major_event_id: str = None,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            updates = []
            params = []
            if schedule_data is not None:
                updates.append("schedule_data = %s")
                params.append(json.dumps(schedule_data, ensure_ascii=False))
            if weather is not None:
                updates.append("weather = %s")
                params.append(weather)
            if is_in_major_event is not None:
                updates.append("is_in_major_event = %s")
                params.append(is_in_major_event)
            if major_event_id is not None:
                updates.append("major_event_id = %s")
                params.append(major_event_id)

            if not updates:
                return False  # No updates to perform

            params.append(schedule_id)
            query = sql.SQL("UPDATE daily_schedules SET {} WHERE id = %s;").format(
                sql.SQL(", ").join(map(sql.SQL, updates))
            )
            cur.execute(query, params)
            return cur.rowcount > 0
    finally:
        conn.close()


def delete_daily_schedule(schedule_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM daily_schedules
                WHERE id = %s;
                """,
                (schedule_id,),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


# --- major_events 表操作 ---
def insert_major_event(
    start_date: str,
    end_date: str,
    duration_days: int,
    main_content: str,
    daily_summaries: dict,
    event_type: str,
    status: str = "planned",
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO major_events (start_date, end_date, duration_days, main_content, daily_summaries, event_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    start_date,
                    end_date,
                    duration_days,
                    main_content,
                    json.dumps(daily_summaries, ensure_ascii=False),
                    event_type,
                    status,
                ),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_major_event_by_id(event_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, start_date, end_date, duration_days, main_content, daily_summaries, event_type, status, created_at
                FROM major_events
                WHERE id = %s;
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "start_date": row[1].strftime("%Y-%m-%d"),
                    "end_date": row[2].strftime("%Y-%m-%d"),
                    "duration_days": row[3],
                    "main_content": row[4],
                    "daily_summaries": row[5],
                    "event_type": row[6],
                    "status": row[7],
                    "created_at": row[8].isoformat(),
                }
            return None
    finally:
        conn.close()


def get_major_event_by_date(target_date: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, start_date, end_date, duration_days, main_content, daily_summaries, event_type, status, created_at
                FROM major_events
                WHERE %s BETWEEN start_date AND end_date;
                """,
                (target_date,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "start_date": row[1].strftime("%Y-%m-%d"),
                    "end_date": row[2].strftime("%Y-%m-%d"),
                    "duration_days": row[3],
                    "main_content": row[4],
                    "daily_summaries": row[5],
                    "event_type": row[6],
                    "status": row[7],
                    "created_at": row[8].isoformat(),
                }
            return None
    finally:
        conn.close()


def update_major_event(
    event_id: str,
    main_content: str = None,
    daily_summaries: dict = None,
    event_type: str = None,
    status: str = None,
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            updates = []
            params = []
            if main_content is not None:
                updates.append("main_content = %s")
                params.append(main_content)
            if daily_summaries is not None:
                updates.append("daily_summaries = %s")
                params.append(json.dumps(daily_summaries, ensure_ascii=False))
            if event_type is not None:
                updates.append("event_type = %s")
                params.append(event_type)
            if status is not None:
                updates.append("status = %s")
                params.append(status)

            if not updates:
                return False

            params.append(event_id)
            query = sql.SQL("UPDATE major_events SET {} WHERE id = %s;").format(
                sql.SQL(", ").join(map(sql.SQL, updates))
            )
            cur.execute(query, params)
            return cur.rowcount > 0
    finally:
        conn.close()


def delete_major_event(event_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM major_events
                WHERE id = %s;
                """,
                (event_id,),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


# --- micro_experiences 表操作 (新结构) ---
def insert_micro_experience(
    date: str, daily_schedule_id: str, experiences: list, related_item_id: str = None
):
    """
    插入微观经历项 (新结构)
    experiences: 包含多个经历项的列表
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO micro_experiences (date, daily_schedule_id, related_item_id, experiences)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    date,
                    daily_schedule_id,
                    related_item_id,
                    json.dumps(experiences, ensure_ascii=False),
                ),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_micro_experiences_by_daily_schedule_id(daily_schedule_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, date, daily_schedule_id, related_item_id, experiences, created_at
                FROM micro_experiences
                WHERE daily_schedule_id = %s;
                """,
                (daily_schedule_id,),
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "id": row[0],
                        "date": row[1].strftime("%Y-%m-%d"),
                        "daily_schedule_id": row[2],
                        "related_item_id": row[3],
                        "experiences": row[4],
                        "created_at": row[5].isoformat(),
                    }
                )
            return results
    finally:
        conn.close()


def get_micro_experiences_by_related_item_id(related_item_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, date, daily_schedule_id, related_item_id, experiences, created_at
                FROM micro_experiences
                WHERE related_item_id = %s;
                """,
                (related_item_id,),
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "id": row[0],
                        "date": row[1].strftime("%Y-%m-%d"),
                        "daily_schedule_id": row[2],
                        "related_item_id": row[3],
                        "experiences": row[4],
                        "created_at": row[5].isoformat(),
                    }
                )
            return results
    finally:
        conn.close()


def delete_micro_experience(experience_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM micro_experiences
                WHERE id = %s;
                """,
                (experience_id,),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


# ==================== Future Events 表操作 ====================

def insert_future_event(event_data: dict) -> str:
    """
    插入未来事件

    Args:
        event_data: {
            'event_text': str,
            'event_summary': str,
            'event_date': str (YYYY-MM-DD) or None,
            'event_time': str (HH:MM) or None,
            'need_reminder': bool,
            'reminder_datetime': str (ISO format) or None,
            'reminder_advance_minutes': int,
            'source_channel': str,
            'created_by': str,
            'context_messages': list,
            'extraction_confidence': float,
            'metadata': dict
        }

    Returns:
        event_id (UUID string)
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO future_events (
                    event_text, event_summary, event_date, event_time,
                    need_reminder, reminder_datetime, reminder_advance_minutes,
                    source_channel, created_by, context_messages,
                    extraction_confidence, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    event_data['event_text'],
                    event_data['event_summary'],
                    event_data.get('event_date'),
                    event_data.get('event_time'),
                    event_data.get('need_reminder', False),
                    event_data.get('reminder_datetime'),
                    event_data.get('reminder_advance_minutes', 30),
                    event_data['source_channel'],
                    event_data['created_by'],
                    json.dumps(event_data.get('context_messages', [])),
                    event_data.get('extraction_confidence', 0.5),
                    json.dumps(event_data.get('metadata', {}))
                ),
            )
            event_id = cur.fetchone()[0]
            return str(event_id)
    finally:
        conn.close()


def get_future_event(event_id: str) -> dict:
    """获取单个未来事件"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_text, event_summary, event_date, event_time,
                       status, need_reminder, reminder_datetime, reminder_sent,
                       reminder_advance_minutes, source_channel, created_by,
                       context_messages, extraction_confidence, metadata,
                       created_at, updated_at, archived_to_mem0, mem0_memory_id
                FROM future_events
                WHERE id = %s;
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            return {
                'id': str(row[0]),
                'event_text': row[1],
                'event_summary': row[2],
                'event_date': row[3],
                'event_time': row[4],
                'status': row[5],
                'need_reminder': row[6],
                'reminder_datetime': row[7],
                'reminder_sent': row[8],
                'reminder_advance_minutes': row[9],
                'source_channel': row[10],
                'created_by': row[11],
                'context_messages': row[12],
                'extraction_confidence': row[13],
                'metadata': row[14],
                'created_at': row[15],
                'updated_at': row[16],
                'archived_to_mem0': row[17],
                'mem0_memory_id': row[18]
            }
    finally:
        conn.close()


def get_active_future_events(user_id: str, days_ahead: int = 7) -> list:
    """
    获取用户未来N天的活跃事件

    Args:
        user_id: 用户ID
        days_ahead: 未来多少天

    Returns:
        事件列表
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_text, event_summary, event_date, event_time,
                       status, need_reminder, reminder_datetime, reminder_sent,
                       source_channel, metadata, created_at
                FROM future_events
                WHERE created_by = %s
                  AND status IN ('pending', 'active')
                  AND (
                      event_date IS NULL
                      OR event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '%s days'
                  )
                ORDER BY
                    CASE WHEN event_date IS NULL THEN 1 ELSE 0 END,
                    event_date,
                    event_time NULLS LAST;
                """,
                (user_id, days_ahead),
            )

            events = []
            for row in cur.fetchall():
                events.append({
                    'id': str(row[0]),
                    'event_text': row[1],
                    'event_summary': row[2],
                    'event_date': row[3],
                    'event_time': row[4],
                    'status': row[5],
                    'need_reminder': row[6],
                    'reminder_datetime': row[7],
                    'reminder_sent': row[8],
                    'source_channel': row[9],
                    'metadata': row[10],
                    'created_at': row[11]
                })
            return events
    finally:
        conn.close()


def update_future_event(event_id: str, updates: dict) -> bool:
    """
    更新未来事件

    Args:
        event_id: 事件ID
        updates: 要更新的字段字典

    Returns:
        是否成功
    """
    if not updates:
        return False

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 动态构建UPDATE语句
            set_clauses = []
            values = []

            for key, value in updates.items():
                if key in ['metadata', 'context_messages'] and isinstance(value, (dict, list)):
                    set_clauses.append(f"{key} = %s")
                    values.append(json.dumps(value))
                else:
                    set_clauses.append(f"{key} = %s")
                    values.append(value)

            values.append(event_id)

            query = f"""
                UPDATE future_events
                SET {', '.join(set_clauses)}
                WHERE id = %s;
            """

            cur.execute(query, values)
            return cur.rowcount > 0
    finally:
        conn.close()


def mark_reminder_sent(event_id: str) -> bool:
    """标记提醒已发送"""
    return update_future_event(event_id, {'reminder_sent': True})


def cancel_future_event(event_id: str, reason: str = None) -> bool:
    """取消事件"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 更新事件状态
            cur.execute(
                """
                UPDATE future_events
                SET status = 'cancelled'
                WHERE id = %s;
                """,
                (event_id,),
            )

            # 记录历史
            if reason:
                cur.execute(
                    """
                    INSERT INTO future_events_history (event_id, action, reason)
                    VALUES (%s, 'cancel', %s);
                    """,
                    (event_id, reason),
                )

            return cur.rowcount > 0
    finally:
        conn.close()


def get_upcoming_reminders(start_time, end_time) -> list:
    """
    获取指定时间范围内需要发送的提醒

    Args:
        start_time: 开始时间 (datetime)
        end_time: 结束时间 (datetime)

    Returns:
        提醒列表
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_text, event_summary, event_date, event_time,
                       reminder_datetime, source_channel, created_by, metadata
                FROM future_events
                WHERE need_reminder = true
                  AND reminder_sent = false
                  AND status = 'active'
                  AND reminder_datetime BETWEEN %s AND %s
                ORDER BY reminder_datetime;
                """,
                (start_time, end_time),
            )

            reminders = []
            for row in cur.fetchall():
                reminders.append({
                    'id': str(row[0]),
                    'event_text': row[1],
                    'event_summary': row[2],
                    'event_date': row[3],
                    'event_time': row[4],
                    'reminder_datetime': row[5],
                    'source_channel': row[6],
                    'created_by': row[7],
                    'metadata': row[8]
                })
            return reminders
    finally:
        conn.close()


def expire_past_events_db() -> list:
    """调用数据库函数标记过期事件"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM expire_past_events();")
            expired = []
            for row in cur.fetchall():
                expired.append({
                    'id': str(row[0]),
                    'event_summary': row[1],
                    'event_date': row[2],
                    'event_time': row[3]
                })
            return expired
    finally:
        conn.close()


def archive_event_to_mem0(event_id: str, mem0_memory_id: str) -> bool:
    """标记事件已归档到Mem0"""
    return update_future_event(event_id, {
        'archived_to_mem0': True,
        'mem0_memory_id': mem0_memory_id
    })


# ==================== 微观经历图片字段更新 ====================

def update_micro_experience_image_fields(
    exp_id: str,
    need_image: bool,
    image_type: str,
    image_reason: str
) -> bool:
    """
    更新微观经历的图片相关字段

    注意：这需要在JSONB数组中找到对应ID的item并更新

    Args:
        exp_id: 微观经历的ID
        need_image: 是否需要图片
        image_type: 图片类型（selfie/scene）
        image_reason: 图片原因

    Returns:
        是否成功更新
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 使用PostgreSQL的JSONB函数更新数组中的元素
            cur.execute(
                """
                UPDATE micro_experiences
                SET experiences = (
                    SELECT jsonb_agg(
                        CASE
                            WHEN elem->>'id' = %s THEN
                                elem || jsonb_build_object(
                                    'need_image', %s::boolean,
                                    'image_type', %s,
                                    'image_reason', %s
                                )
                            ELSE elem
                        END
                    )
                    FROM jsonb_array_elements(experiences) elem
                )
                WHERE experiences @> jsonb_build_array(jsonb_build_object('id', %s));
                """,
                (exp_id, need_image, image_type, image_reason, exp_id)
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"更新微观经历图片字段失败 (ID={exp_id}): {e}")
        return False
    finally:
        conn.close()


def set_default_image_fields_for_all_experiences(date_str: str) -> int:
    """
    为当天所有微观经历设置默认图片字段（need_image=false）

    Args:
        date_str: 日期字符串 (YYYY-MM-DD)

    Returns:
        更新的记录数
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE micro_experiences
                SET experiences = (
                    SELECT jsonb_agg(
                        elem || jsonb_build_object(
                            'need_image', false,
                            'image_type', null,
                            'image_reason', null
                        )
                    )
                    FROM jsonb_array_elements(experiences) elem
                )
                WHERE date = %s;
                """,
                (date_str,)
            )
            return cur.rowcount
    except Exception as e:
        logger.error(f"设置默认图片字段失败 (date={date_str}): {e}")
        return 0
    finally:
        conn.close()


# ==================== Intimacy Records (CG Gallery) ====================

def init_intimacy_table():
    """初始化亲密记录表"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intimacy_records (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    trigger_type VARCHAR(50),
                    body_part VARCHAR(100),
                    act_type VARCHAR(100),
                    summary TEXT,
                    full_story TEXT,
                    tags JSONB,
                    intensity INTEGER
                );
            """)
    except Exception as e:
        logger.error(f"初始化 intimacy_records 表失败: {e}")
    finally:
        conn.close()

def insert_intimacy_record(record_data: dict) -> str:
    """
    插入亲密行为记录
    Args:
        record_data: {
            'trigger_type': str,
            'body_part': str,
            'act_type': str,
            'summary': str,
            'full_story': str,
            'tags': list,
            'intensity': int
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO intimacy_records (
                    trigger_type, body_part, act_type, summary, full_story, tags, intensity
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    record_data.get('trigger_type', 'release'),
                    record_data.get('body_part', 'Unknown'),
                    record_data.get('act_type', 'Unknown'),
                    record_data.get('summary', ''),
                    record_data.get('full_story', ''),
                    json.dumps(record_data.get('tags', []), ensure_ascii=False),
                    record_data.get('intensity', 1)
                ),
            )
            return str(cur.fetchone()[0])
    finally:
        conn.close()

def get_intimacy_records(limit: int = 20, offset: int = 0) -> list:
    """获取亲密记录列表"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, recorded_at, body_part, act_type, summary, tags, intensity
                FROM intimacy_records
                ORDER BY recorded_at DESC
                LIMIT %s OFFSET %s;
                """,
                (limit, offset)
            )
            records = []
            for row in cur.fetchall():
                records.append({
                    'id': str(row[0]),
                    'recorded_at': row[1].isoformat(),
                    'body_part': row[2],
                    'act_type': row[3],
                    'summary': row[4],
                    'tags': row[5],
                    'intensity': row[6]
                })
            return records
    finally:
        conn.close()

def get_intimacy_record_detail(record_id: str) -> dict:
    """获取单条记录详情"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, recorded_at, body_part, act_type, summary, full_story, tags, intensity
                FROM intimacy_records
                WHERE id = %s;
                """,
                (record_id,)
            )
            row = cur.fetchone()
            if row:
                return {
                    'id': str(row[0]),
                    'recorded_at': row[1].isoformat(),
                    'body_part': row[2],
                    'act_type': row[3],
                    'summary': row[4],
                    'full_story': row[5],
                    'tags': row[6],
                    'intensity': row[7]
                }
            return None
    finally:
        conn.close()

def get_intimacy_stats() -> dict:
    """获取部位和行为方式统计"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Body Part Stats
            cur.execute(
                """
                SELECT body_part, COUNT(*) as count
                FROM intimacy_records
                GROUP BY body_part
                ORDER BY count DESC;
                """
            )
            body_parts = {row[0]: row[1] for row in cur.fetchall()}

            # 2. Act Type Stats
            cur.execute(
                """
                SELECT act_type, COUNT(*) as count
                FROM intimacy_records
                GROUP BY act_type
                ORDER BY count DESC;
                """
            )
            act_types = {row[0]: row[1] for row in cur.fetchall()}

            return {
                "body_parts": body_parts,
                "act_types": act_types
            }
    finally:
        conn.close()

def delete_intimacy_record(record_id: str) -> bool:
    """删除亲密记录"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM intimacy_records
                WHERE id = %s;
                """,
                (record_id,)
            )
            return cur.rowcount > 0
    finally:
        conn.close()

def get_latest_intimacy_record(within_seconds: int = 600) -> dict:
    """
    获取最近的亲密记录（在指定时间窗口内）
    Args:
        within_seconds: 时间窗口（秒），默认600秒（10分钟）
    Returns:
        最近的记录字典，如果没有则返回None
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, recorded_at, trigger_type, body_part, act_type, summary, full_story, tags, intensity
                FROM intimacy_records
                WHERE recorded_at > NOW() - INTERVAL '%s seconds'
                ORDER BY recorded_at DESC
                LIMIT 1;
                """,
                (within_seconds,)
            )
            row = cur.fetchone()
            if row:
                return {
                    'id': str(row[0]),
                    'recorded_at': row[1].isoformat(),
                    'trigger_type': row[2],
                    'body_part': row[3],
                    'act_type': row[4],
                    'summary': row[5],
                    'full_story': row[6],
                    'tags': row[7],
                    'intensity': row[8]
                }
            return None
    finally:
        conn.close()

def update_intimacy_record(record_id: str, record_data: dict) -> bool:
    """
    更新亲密记录（用于防抖期内的CG替换）
    Args:
        record_id: 记录ID
        record_data: 新的记录数据
    Returns:
        是否更新成功
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE intimacy_records
                SET trigger_type = %s,
                    body_part = %s,
                    act_type = %s,
                    summary = %s,
                    full_story = %s,
                    tags = %s,
                    intensity = %s,
                    recorded_at = NOW()
                WHERE id = %s;
                """,
                (
                    record_data.get('trigger_type', 'release'),
                    record_data.get('body_part', 'Unknown'),
                    record_data.get('act_type', 'Unknown'),
                    record_data.get('summary', ''),
                    record_data.get('full_story', ''),
                    json.dumps(record_data.get('tags', []), ensure_ascii=False),
                    record_data.get('intensity', 1),
                    record_id
                ),
            )
            return cur.rowcount > 0
    finally:
        conn.close()

def get_last_release_timestamp() -> float:
    """
    从 intimacy_records 表中获取最后一次释放的时间戳
    用于在 Redis 状态丢失后恢复 last_release_time

    Returns:
        时间戳（float），如果没有记录则返回 0.0
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # v3.9 修复：只查询 trigger_type = 'release' 的记录
            cur.execute(
                """
                SELECT recorded_at FROM intimacy_records
                WHERE trigger_type = 'release'
                ORDER BY recorded_at DESC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
            if row:
                # 将 PostgreSQL TIMESTAMP 转换为 Unix 时间戳
                return row[0].timestamp()
            return 0.0
    except Exception as e:
        logger.error(f"获取最后释放时间戳失败: {e}")
        return 0.0
    finally:
        conn.close()
