import httpx
from datetime import datetime, timedelta
from celery import shared_task
from app.config import settings
import logging

logger = logging.getLogger(__name__)

@shared_task
def generate_daily_life_task():
    try:
        # 动态生成明天日期（格式为 YYYY-MM-DD）
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"📅 正在生成 {tomorrow} 的日程")
        response = httpx.get(
            f"http://bot:8000/generate-daily-life?target_date={tomorrow}",
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
        )
        response.raise_for_status()
        return {"status": "success", "response": response.json()}
    except Exception as e:
        return {"status": "error", "message": str(e)}
