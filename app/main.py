import logging
from fastapi import FastAPI, HTTPException
from app.config import settings
import asyncio

# 配置日志，包含时间戳、级别、名称和消息
logging.basicConfig(
    level=logging.INFO, # 可以根据需要调整日志级别
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

from app.mattermost_client import MattermostWebSocketClient
from services.redis_cleanup_service import start_redis_cleanup
from app.life_system import generate_and_store_daily_life, collect_interaction_experiences
from datetime import date

app = FastAPI(title=settings.BOT_NAME)

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.BOT_NAME}!"}

@app.get("/generate-daily-life")
async def generate_daily_life_endpoint(target_date: str = None):
    """
    触发生成指定日期的德克萨斯生活日程。
    如果未指定日期，则生成今天的日程。
    """
    if target_date:
        try:
            target_date_obj = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正确，请使用 YYYY-MM-DD 格式。")
    else:
        target_date_obj = date.today()
    
    await generate_and_store_daily_life(target_date_obj)
    return {"message": f"已触发生成 {target_date_obj.strftime('%Y-%m-%d')} 的每日日程。请查看日志和 'generated_content' 文件夹。"}

@app.get("/collect-interactions")
async def collect_interactions_endpoint(target_date: str = None):
    """
    手动收集需要交互的微观经历并存入Redis
    """
    if target_date:
        try:
            target_date_obj = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正确，请使用 YYYY-MM-DD 格式。")
    else:
        target_date_obj = date.today()
    
    from app.life_system import collect_interaction_experiences
    success = await collect_interaction_experiences(target_date_obj)
    
    if success:
        return {"message": f"已成功收集 {target_date_obj.strftime('%Y-%m-%d')} 需要交互的微观经历"}
    else:
        raise HTTPException(status_code=404, detail=f"未找到 {target_date_obj.strftime('%Y-%m-%d')} 的日程数据或微观经历")

@app.on_event("startup")
async def startup_event():
    """启动 WebSocket 客户端和Redis清理服务"""
    # 启动 WebSocket 客户端
    ws_client = MattermostWebSocketClient()
    asyncio.create_task(ws_client.connect())
    
    # 启动 Redis 清理服务
    asyncio.create_task(start_redis_cleanup())
