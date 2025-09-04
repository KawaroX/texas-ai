"""
Gemini配置管理模块

从Redis加载和管理Gemini API的配置。
"""

import os
import json
import logging
from typing import Dict, Any

from utils.redis_manager import get_async_redis_client

logger = logging.getLogger(__name__)

# 配置常量
REDIS_GEMINI_CFG_KEY = os.getenv("REDIS_GEMINI_CFG_KEY", "texas:llm:gemini_cfg")
DEFAULT_GEMINI_CFG = {
    "model": "gemini-2.5-pro",
    "connect_timeout": 10.0,
    "read_timeout": 60.0,
    "write_timeout": 60.0,
    "pool_timeout": 60.0,
    "stop_sequences": ["NO_REPLY"],
    "include_thoughts": True,
    "thinking_budget": 32768,
    "response_mime_type": "text/plain",
}


class GeminiConfigManager:
    """Gemini配置管理器"""
    
    def __init__(self):
        self._redis = get_async_redis_client()
    
    async def load_config(self) -> Dict[str, Any]:
        """
        从 Redis 读取一次性配置快照；失败或缺项时使用默认值兜底。
        """
        try:
            raw = await self._redis.get(REDIS_GEMINI_CFG_KEY)
            if not raw:
                # Redis 无配置时，写入默认值并返回
                try:
                    await self._redis.set(
                        REDIS_GEMINI_CFG_KEY,
                        json.dumps(DEFAULT_GEMINI_CFG, ensure_ascii=False),
                    )
                    logger.debug("[GeminiConfig] Redis 无配置，写入默认 Gemini 配置")
                except Exception as se:
                    logger.warning(f"⚠️ 写入默认 Gemini 配置到 Redis 失败: {se}")
                return DEFAULT_GEMINI_CFG.copy()
            
            user_cfg = json.loads(raw)
            # 合并默认值，避免缺字段
            merged = {**DEFAULT_GEMINI_CFG, **(user_cfg or {})}
            return merged
        except Exception as e:
            logger.warning(f"⚠️ 读取 Gemini 配置失败，使用默认值: {e}")
            return DEFAULT_GEMINI_CFG.copy()
    
    async def save_config(self, config: Dict[str, Any]) -> bool:
        """保存配置到Redis"""
        try:
            await self._redis.set(
                REDIS_GEMINI_CFG_KEY,
                json.dumps(config, ensure_ascii=False),
            )
            logger.debug("[GeminiConfig] 配置已保存到 Redis")
            return True
        except Exception as e:
            logger.error(f"❌ 保存 Gemini 配置到 Redis 失败: {e}")
            return False
    
    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return DEFAULT_GEMINI_CFG.copy()