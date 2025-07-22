import psycopg2
from app.config import settings

# 使用 config.settings 获取数据库连接信息
conn = psycopg2.connect(
    dbname=settings.POSTGRES_DB,
    user=settings.POSTGRES_USER,
    password=settings.POSTGRES_PASSWORD,
    host="db",  # 容器内部用服务名连接
    port=5432,
)
conn.autocommit = True


def insert_messages(messages):
    """
    messages: List of tuples (channel_id, role, content, timestamp)
    """
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO messages (channel_id, role, content, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            messages,
        )
