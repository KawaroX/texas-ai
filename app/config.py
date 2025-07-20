from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_NAME: str = "TexasAI"

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    REDIS_URL: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    MATTERMOST_HOST: str
    MATTERMOST_TOKEN: str

    OPENAI_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""
    JINA_API_KEY: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
