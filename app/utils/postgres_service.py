import psycopg2
import os

conn = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
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
            INSERT INTO messages (channel_id, sender, content, timestamp)
            VALUES (%s, %s, %s, %s)
            """,
            messages,
        )
