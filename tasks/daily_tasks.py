import httpx
import time
from datetime import datetime, timedelta
from celery import shared_task
from app.config import settings
from services.memory_data_collector import MemoryDataCollector
from services.memory_summarizer import MemorySummarizer
from services.memory_storage import MemoryStorage
import logging
import shutil
import os

logger = logging.getLogger(__name__)



@shared_task
def generate_daily_memories():
    """生成每日记忆并存储到Redis"""
    try:
        collector = MemoryDataCollector()
        summarizer = MemorySummarizer()
        storage = MemoryStorage()

        # 处理三类记忆数据
        for data_type, collector_method in [
            ("chat", collector.get_unembedded_chats),
            ("schedule", collector.get_yesterday_schedule_experiences),
            ("event", collector.get_major_events),
        ]:
            logger.info(f"💡 开始处理 {data_type} 数据")
            data = collector_method()
            if data:
                # 提取ID用于后续标记
                if data_type == "chat":
                    ids = [item["id"] for item in data]
                elif data_type == "schedule":
                    ids = [item["id"] for item in data]
                elif data_type == "event":
                    ids = [item["id"] for item in data]

                memories = summarizer.summarize(data_type, data)
                # 确保memories是列表形式
                if not isinstance(memories, list):
                    memories = [memories]
                storage.store_memory(memories)

                # 标记数据为已嵌入
                if data_type == "chat":
                    collector.mark_chats_embedded(ids)
                elif data_type == "schedule":
                    for schedule_id in ids:
                        collector.mark_schedule_embedded(schedule_id)
                elif data_type == "event":
                    for event_id in ids:
                        collector.mark_event_embedded(event_id)
                
                logger.info(f"✅ 成功处理 {data_type} 数据，生成 {len(memories)} 条记忆。")

    except Exception as e:
        logger.error(f"生成每日记忆失败: {str(e)}")
        raise
    
    logger.info("🎉 每日记忆生成任务完成。")

@shared_task
def clean_generated_content():
    """每天清空generated_content文件夹"""
    try:
        dir_path = "generated_content"
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            os.makedirs(dir_path)
            logger.info(f"✅ 成功清空目录: {dir_path}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"清空目录失败: {str(e)}")
        return {"status": "error", "message": str(e)}


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
