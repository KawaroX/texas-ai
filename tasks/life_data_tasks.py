from services.life_data_service import life_data_service
import asyncio
from celery import shared_task
from .daily_tasks import generate_daily_life_task
from app.life_system import LifeSystemQuery
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)

@shared_task
def fetch_and_store_life_data_task():
    """供Celery调用的生活数据存储任务"""
    logger.info("Fetching and storing life data...")
    today = date.today()
    
    # 检查今天的数据是否已存在
    daily_schedule = asyncio.run(LifeSystemQuery(today).get_daily_schedule_info())
    if not daily_schedule:
        logger.warning(f"No daily schedule found for {today}. Triggering generate_daily_life_task...")
        # 触发生成每日生活任务
        generate_daily_life_task.delay(today.strftime("%Y-%m-%d"))
        # 可以选择等待生成完成，或者直接返回，让下一次调度来处理
        # 为了避免长时间阻塞，这里选择不等待，让下一次调度来获取数据
        return {"status": "triggered_generation", "message": f"No data for {today}, triggered generation."}

    try:
        result = asyncio.run(life_data_service.fetch_and_store_today_data())
        logger.info(f"Successfully stored life data for {today}: {result}")
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Error fetching life data for {today}: {e}")
        return {"status": "error", "message": str(e)}
