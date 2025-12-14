"""
图片生成服务 Provider 基类

定义统一的接口，支持多图输入和不同的图片生成模型
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Union
from dataclasses import dataclass


@dataclass
class ImageGenerationRequest:
    """图片生成请求"""
    prompt: str
    images: Optional[List[bytes]] = None  # 多张底图（二进制数据）
    size: Optional[str] = None  # 图片尺寸
    watermark: bool = False

    # 高级参数
    sequential_generation: bool = False  # 是否顺序生成（SeeDream专用）
    response_modalities: Optional[List[str]] = None  # Gemini专用


@dataclass
class ImageGenerationResponse:
    """图片生成响应"""
    success: bool
    image_data: Optional[bytes] = None
    image_url: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None


class BaseImageProvider(ABC):
    """图片生成 Provider 基类"""

    def __init__(self, api_key: str, api_url: str):
        self.api_key = api_key
        self.api_url = api_url

    @abstractmethod
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """
        生成图片

        Args:
            request: 图片生成请求

        Returns:
            ImageGenerationResponse: 生成结果
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """获取 Provider 名称"""
        pass

    @abstractmethod
    def supports_multi_image_input(self) -> bool:
        """是否支持多图输入"""
        pass

    def _convert_to_base64_url(self, image_data: bytes) -> str:
        """将图片转换为 base64 data URL"""
        import base64
        base64_data = base64.b64encode(image_data).decode('utf-8')
        return f"data:image/png;base64,{base64_data}"

    def _convert_to_base64(self, image_data: bytes) -> str:
        """将图片转换为纯 base64（不带前缀）"""
        import base64
        return base64.b64encode(image_data).decode('utf-8')
