import logging
from fastapi import FastAPI
from config import settings
import asyncio

# 配置日志，包含时间戳、级别、名称和消息
logging.basicConfig(
    level=logging.INFO, # 可以根据需要调整日志级别
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

from mattermost_client import MattermostWebSocketClient
from services.redis_cleanup_service import start_redis_cleanup

app = FastAPI(title=settings.BOT_NAME)

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.BOT_NAME}!"}

@app.on_event("startup")
async def startup_event():
    """启动 WebSocket 客户端和Redis清理服务"""
    # 启动 WebSocket 客户端
    ws_client = MattermostWebSocketClient()
    asyncio.create_task(ws_client.connect())
    
    # 启动 Redis 清理服务
    asyncio.create_task(start_redis_cleanup())
