"""
from utils.logging_config import get_logger

logger = get_logger(__name__)

AI Provider 抽象基类

定义了所有AI服务提供商必须实现的统一接口。
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional


class AIProviderBase(ABC):
    """AI服务提供商抽象基类"""
    
    @abstractmethod
    async def stream_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话接口"""
        pass
    
    @abstractmethod
    async def call_chat(self, messages: list, model: Optional[str] = None, **kwargs) -> str:
        """同步对话接口"""
        pass
    
    @abstractmethod  
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置是否有效"""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """获取提供商名称"""
        pass


class ConfigurableProvider(AIProviderBase):
    """支持配置管理的AI提供商基类"""
    
    def __init__(self):
        self._config = self._load_default_config()
    
    @abstractmethod
    def _load_default_config(self) -> Dict[str, Any]:
        """加载默认配置"""
        pass
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """更新配置"""
        if self.validate_config(config):
            self._config.update(config)
        else:
            raise ValueError(f"Invalid config for {self.get_provider_name()}")
    
    def get_config(self, key: str = None) -> Any:
        """获取配置"""
        if key is None:
            return self._config.copy()
        return self._config.get(key)