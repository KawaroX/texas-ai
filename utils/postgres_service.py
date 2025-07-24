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
def insert_daily_schedule(date: str, schedule_data: dict, weather: str, is_in_major_event: bool = False, major_event_id: str = None):
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
                (date,)
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

def update_daily_schedule(schedule_id: str, schedule_data: dict = None, weather: str = None, is_in_major_event: bool = None, major_event_id: str = None):
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
                return False # No updates to perform

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
                (schedule_id,)
            )
            return cur.rowcount > 0
    finally:
        conn.close()

# --- major_events 表操作 ---
def insert_major_event(start_date: str, end_date: str, duration_days: int, main_content: str, daily_summaries: dict, event_type: str, status: str = 'planned'):
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
                (event_id,)
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
                (target_date,)
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

def update_major_event(event_id: str, main_content: str = None, daily_summaries: dict = None, event_type: str = None, status: str = None):
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
                params.append(json.dumps(daily_summaries))
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
                (event_id,)
            )
            return cur.rowcount > 0
    finally:
        conn.close()

# --- micro_experiences 表操作 (新结构) ---
def insert_micro_experience(
    date: str, 
    daily_schedule_id: str, 
    experiences: list,
    related_item_id: str = None
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
                (daily_schedule_id,)
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row[0],
                    "date": row[1].strftime("%Y-%m-%d"),
                    "daily_schedule_id": row[2],
                    "related_item_id": row[3],
                    "experiences": row[4],
                    "created_at": row[5].isoformat(),
                })
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
                (related_item_id,)
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row[0],
                    "date": row[1].strftime("%Y-%m-%d"),
                    "daily_schedule_id": row[2],
                    "related_item_id": row[3],
                    "experiences": row[4],
                    "created_at": row[5].isoformat(),
                })
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
                (experience_id,)
            )
            return cur.rowcount > 0
    finally:
        conn.close()
