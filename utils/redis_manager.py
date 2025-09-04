"""
统一的Redis连接管理器
提供单例模式的Redis连接池，避免重复创建连接
"""

import os
import redis
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RedisManager:
    """Redis连接管理器单例类"""
    
    _instance: Optional['RedisManager'] = None
    _redis_client: Optional[redis.Redis] = None
    _async_redis_client = None  # 用于异步操作
    
    def __new__(cls) -> 'RedisManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._redis_client is None:
            self._initialize_connections()
    
    def _initialize_connections(self):
        """初始化Redis连接"""
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("REDIS_URL环境变量未设置")
        
        try:
            # 同步Redis客户端
            self._redis_client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30,
                max_connections=20,  # 连接池最大连接数
                retry_on_timeout=True
            )
            
            # 测试连接
            self._redis_client.ping()
            logger.info("✅ Redis连接池初始化成功")
            
        except Exception as e:
            logger.error(f"❌ Redis连接池初始化失败: {e}")
            raise
    
    @property
    def client(self) -> redis.Redis:
        """获取同步Redis客户端"""
        if self._redis_client is None:
            self._initialize_connections()
        return self._redis_client
    
    @property
    def async_client(self):
        """获取异步Redis客户端（如果需要）"""
        if self._async_redis_client is None:
            import redis.asyncio as aioredis
            redis_url = os.getenv("REDIS_URL")
            self._async_redis_client = aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20
            )
        return self._async_redis_client
    
    def health_check(self) -> bool:
        """Redis健康检查"""
        try:
            self.client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis健康检查失败: {e}")
            return False
    
    def get_connection_info(self) -> dict:
        """获取连接信息"""
        try:
            info = self.client.info()
            return {
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "redis_version": info.get("redis_version", "unknown"),
                "total_connections_received": info.get("total_connections_received", 0)
            }
        except Exception as e:
            logger.error(f"获取Redis连接信息失败: {e}")
            return {}


# 全局单例实例
redis_manager = RedisManager()

# 为了保持向后兼容，提供简单的获取函数
def get_redis_client() -> redis.Redis:
    """获取Redis客户端（向后兼容函数）"""
    return redis_manager.client

def get_async_redis_client():
    """获取异步Redis客户端"""
    return redis_manager.async_client