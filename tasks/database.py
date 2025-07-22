import asyncpg
import os


class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DB"),
            host=os.getenv(
                "POSTGRES_HOST", "db"
            ),  # 默认连接 docker-compose 中定义的 postgres 服务名
            port=int(os.getenv("POSTGRES_PORT", "5432")),
        )

    async def save_message(self, channel_id: str, role: str, content: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (channel_id, role, content)
                VALUES ($1, $2, $3)
                """,
                channel_id,
                role,
                content,
            )

    async def load_recent_messages(self, channel_id: str, before_timestamp: str):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content FROM messages
                WHERE channel_id = $1 AND created_at < $2
                ORDER BY created_at DESC
                LIMIT 50
                """,
                channel_id,
                before_timestamp,
            )
            return list(rows)


db = Database()
