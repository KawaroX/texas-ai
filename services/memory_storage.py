import os
import json
import redis
import logging
from typing import Dict
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


class MemoryStorage:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("REDIS_URL环境变量未设置")
        self.client = redis.Redis.from_url(redis_url)
        logger.info("[MemoryStorage] Redis client initialized with URL: %s", redis_url)

    def store_memory(self, memory_data) -> bool:
        """存储记忆到Redis（24小时过期），支持单个记忆或多个记忆列表"""
        try:
            # 如果是单个记忆项，转换为列表
            memories = (
                [memory_data] if not isinstance(memory_data, list) else memory_data
            )

            for memory in memories:
                # 确保每个记忆有唯一ID
                if "id" not in memory:
                    memory_id = f"memory_{datetime.now(pytz.utc).strftime('%Y%m%d%H%M%S%f')}"
                    memory["id"] = memory_id
                else:
                    memory_id = memory["id"]
                
                # 获取类型和日期，用于构建新的key格式
                # 假设 memory 中一定有 'type' 和 'date' 字段
                memory_type = memory.get("type", "unknown") 
                memory_date = memory.get("date", datetime.now(pytz.utc).date().isoformat())
                
                # 构建新的key格式：mem0:类型_日期:ID
                key = f"mem0:{memory_type}_{memory_date}:{memory_id}"
                
                logger.info("[MemoryStorage] Storing memory for key: %s", key)
                serialized = json.dumps(memory, ensure_ascii=False)
                self.client.setex(key, 86400, serialized)

            logger.info(
                "[MemoryStorage] %d memories stored successfully.", len(memories)
            )
            return True
        except Exception as e:
            logger.error("[MemoryStorage] Failed to store memory: %s", str(e))
            raise RuntimeError(f"记忆存储失败: {str(e)}")
