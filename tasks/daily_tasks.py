import httpx
import time
from datetime import datetime, timedelta
from celery import shared_task
from app.config import settings
from services.memory_data_collector import MemoryDataCollector
from services.memory_summarizer import MemorySummarizer
from services.memory_storage import MemoryStorage
from typing import List, Dict
import logging
import shutil
import os
from datetime import date, timedelta
import glob

logger = logging.getLogger(__name__)


@shared_task
def generate_daily_memories():
    """生成每日记忆并存储到Redis（不包括聊天记录）"""
    try:
        collector = MemoryDataCollector()
        summarizer = MemorySummarizer()
        storage = MemoryStorage()

        # 处理两类记忆数据（不包括聊天记录）
        for data_type, collector_method in [
            ("schedule", collector.get_yesterday_schedule_experiences),
            ("event", collector.get_major_events),
        ]:
            logger.info(f"[daily_tasks] 开始处理 {data_type} 数据")
            data = collector_method()
            if data:
                # 提取ID用于后续标记
                if data_type == "schedule":
                    ids = [item["id"] for item in data]
                elif data_type == "event":
                    ids = [item["id"] for item in data]

                memories = summarizer.summarize(data_type, data)
                # 确保memories是列表形式
                if not isinstance(memories, list):
                    memories = [memories]
                storage.store_memory(memories)

                # 标记数据为已嵌入
                if data_type == "schedule":
                    for schedule_id in ids:
                        collector.mark_schedule_embedded(schedule_id)
                elif data_type == "event":
                    for event_id in ids:
                        collector.mark_event_embedded(event_id)

                logger.debug(
                    f"[daily_tasks] 成功处理 {data_type} 数据，生成 {len(memories)} 条记忆"
                )

    except Exception as e:
        logger.error(f"生成每日记忆失败: {str(e)}")
        raise

    logger.info("[daily_tasks] 每日记忆生成任务完成")


@shared_task
def generate_chat_memories():
    """生成聊天记录记忆并存储到Redis，每3小时执行一次"""
    try:
        collector = MemoryDataCollector()
        summarizer = MemorySummarizer()
        storage = MemoryStorage()

        # 获取所有未嵌入的聊天记录
        all_chats = collector.get_unembedded_chats()

        if not all_chats:
            logger.debug("[daily_tasks] 没有未嵌入的聊天记录需要处理")
            return

        # 按时间分段处理（如果时间跨度超过3小时）
        # 获取最早和最晚的聊天记录时间
        earliest_time = min(chat["created_at"] for chat in all_chats)
        latest_time = max(chat["created_at"] for chat in all_chats)

        # 如果是字符串格式的时间，转换为datetime对象
        if isinstance(earliest_time, str):
            earliest_time = datetime.fromisoformat(earliest_time.replace("Z", "+00:00"))
        if isinstance(latest_time, str):
            latest_time = datetime.fromisoformat(latest_time.replace("Z", "+00:00"))

        # 计算时间跨度
        time_span = latest_time - earliest_time

        # 如果时间跨度超过3小时，则分段处理
        if time_span > timedelta(hours=3):
            logger.debug(
                f"[daily_tasks] 聊天记录时间跨度超过3小时 ({time_span})，分段处理"
            )

            # 按3小时分段处理
            current_start = earliest_time
            while current_start < latest_time:
                current_end = current_start + timedelta(hours=3)
                # 确保不超出最晚时间
                if current_end > latest_time:
                    current_end = latest_time

                # 获取当前时间段的聊天记录
                chats_in_period = [
                    chat
                    for chat in all_chats
                    if datetime.fromisoformat(chat["created_at"].replace("Z", "+00:00"))
                    >= current_start
                    and datetime.fromisoformat(
                        chat["created_at"].replace("Z", "+00:00")
                    )
                    < current_end
                ]

                if chats_in_period:
                    logger.debug(
                        f"[daily_tasks] 处理时间段 {current_start}~{current_end} 聊天记录 {len(chats_in_period)} 条"
                    )
                    process_chat_batch(chats_in_period, collector, summarizer, storage)
                else:
                    logger.debug(
                        f"[daily_tasks] 时间段 {current_start}~{current_end} 没有聊天记录"
                    )

                current_start = current_end
        else:
            # 时间跨度不超过3小时，一次性处理
            logger.debug(
                f"[daily_tasks] 聊天记录时间跨度未超过3小时 ({time_span})，一次性处理"
            )
            process_chat_batch(all_chats, collector, summarizer, storage)

    except Exception as e:
        logger.error(f"生成聊天记录记忆失败: {str(e)}")
        raise

    logger.info("[daily_tasks] 聊天记录记忆生成任务完成")


def process_chat_batch(
    chats: List[Dict],
    collector: MemoryDataCollector,
    summarizer: MemorySummarizer,
    storage: MemoryStorage,
):
    """处理一批聊天记录"""
    if not chats:
        return

    # 提取ID用于后续标记
    ids = [item["id"] for item in chats]

    # 生成记忆
    memories = summarizer.summarize("chat", chats)
    # 确保memories是列表形式
    if not isinstance(memories, list):
        memories = [memories]
    storage.store_memory(memories)

    # 标记数据为已嵌入
    collector.mark_chats_embedded(ids)

    logger.debug(
        f"[daily_tasks] 已处理聊天记录 {len(chats)} 条，生成记忆 {len(memories)} 条"
    )


@shared_task
def clean_generated_content():
    """
    删除 generated_content 文件夹中前一天相关的文件（文件名包含前一天日期字符串，格式为 YYYY-MM-DD）。
    """
    try:
        dir_path = "generated_content"
        if not os.path.exists(dir_path):
            logger.debug(f"[daily_tasks] 目录不存在: {dir_path}")
            return {"status": "success", "removed": 0}
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        pattern = os.path.join(dir_path, f"*{yesterday}*")
        files = glob.glob(pattern)
        removed_count = 0
        for file_path in files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.debug(f"[daily_tasks] 已删除文件: {file_path}")
                    removed_count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    logger.debug(f"[daily_tasks] 已删除文件夹: {file_path}")
                    removed_count += 1
            except Exception as file_err:
                logger.error(f"删除文件失败: {file_path}: {file_err}")
        logger.info(
            f"[daily_tasks] 清理完成，删除 {removed_count} 个包含日期 {yesterday} 的项"
        )
        return {"status": "success", "removed": removed_count}
    except Exception as e:
        logger.error(f"清理 generated_content 目录失败: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def generate_daily_life_task(date: str | None = None):
    try:
        # 动态生成明天日期（格式为 YYYY-MM-DD）
        if not date:
            date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")  # 明天

        logger.info(f"[daily_tasks] 开始触发生成日程 date={date}")
        response = httpx.get(
            f"http://bot:8000/generate-daily-life?target_date={date}",
            headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
        )
        response.raise_for_status()
        return {"status": "success", "response": response.json()}
    except Exception as e:
        return {"status": "error", "message": str(e)}
