from celery import Celery
from celery.schedules import crontab
from app.config import settings
from datetime import datetime, timedelta
from .daily_tasks import generate_daily_life_task
from .life_data_tasks import fetch_and_store_life_data_task
from .interaction_tasks import process_scheduled_interactions

celery_app = Celery(
    "texas_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_log_level="DEBUG",  # 设置 worker 的日志级别为 DEBUG
    worker_redirect_stdouts_level="DEBUG",  # 重定向标准输出的日志级别
    beat_schedule={
        "generate-daily-life": {
            "task": "tasks.daily_tasks.generate_daily_life_task",
            "schedule": crontab(hour=20, minute=0),  # 每天20点触发
        },
        "generate-daily-memories": {
            "task": "tasks.daily_tasks.generate_daily_memories",
            "schedule": crontab(hour=20, minute=0),  # 每天20点触发
        },
        "process-scheduled-interactions": {
            "task": "tasks.interaction_tasks.process_scheduled_interactions",
            "schedule": 300,  # 每5分钟执行一次
        },
        "fetch-and-store-life-data": {
            "task": "tasks.life_data_tasks.fetch_and_store_life_data_task",
            "schedule": 300,  # 每5分钟执行一次
        },
    },
)
