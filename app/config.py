from utils.logging_config import get_logger

logger = get_logger(__name__)

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

    # 图片生成专用配置
    IMAGE_GENERATION_API_KEY: str = ""
    IMAGE_GENERATION_API_URL: str = "https://yunwu.ai/v1/images"

try:
    settings = Settings()
    logger.info(f"配置加载成功 - BOT: {settings.BOT_NAME}")
    logger.debug(f"数据库连接: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    logger.debug(f"Mattermost主机: {settings.MATTERMOST_HOST}")
    
    # 记录API密钥状态（不记录密钥本身）
    api_status = []
    if settings.OPENAI_API_KEY:
        api_status.append("OpenAI")
    if settings.CLAUDE_API_KEY:
        api_status.append("Claude") 
    if settings.IMAGE_GENERATION_API_KEY:
        api_status.append("ImageGen")
    
    if api_status:
        logger.info(f"已配置的API服务: {', '.join(api_status)}")
    else:
        logger.warning("未配置任何API密钥")
        
except Exception as e:
    logger.error(f"配置加载失败: {e}")
    raise
