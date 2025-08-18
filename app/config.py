from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="allow")

    BOT_NAME: str = "TexasAI"

    # 添加内部API密钥用于服务间认证
    INTERNAL_API_KEY: str

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: str
    POSTGRES_DB: str

    REDIS_URL: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    MATTERMOST_HOST: str
    MATTERMOST_TOKEN: str

    OPENAI_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""

settings = Settings()