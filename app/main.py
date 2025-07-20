from fastapi import FastAPI
from app.config import settings
import asyncio

from app.mattermost_client import MattermostWebSocketClient

app = FastAPI(title=settings.BOT_NAME)

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.BOT_NAME}!"}

@app.on_event("startup")
async def startup_event():
    """启动 WebSocket 客户端"""
    ws_client = MattermostWebSocketClient()
    asyncio.create_task(ws_client.connect_to_mattermost())