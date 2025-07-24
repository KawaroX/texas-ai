import httpx
from celery import shared_task
from app.config import settings


@shared_task
def generate_daily_life_task(target_date: str):
    try:
        response = httpx.get(
            f"http://bot:8000/generate-daily-life?target_date={target_date}",
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
        )
        response.raise_for_status()
        return {"status": "success", "response": response.json()}
    except Exception as e:
        return {"status": "error", "message": str(e)}
