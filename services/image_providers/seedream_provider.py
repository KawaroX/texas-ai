"""
SeeDream 图片生成 Provider

支持单图和多图输入的图片生成
"""

import httpx
from typing import List, Optional
from utils.logging_config import get_logger
from .base import BaseImageProvider, ImageGenerationRequest, ImageGenerationResponse

logger = get_logger(__name__)


class SeeDreamProvider(BaseImageProvider):
    """SeeDream (doubao-seedream-4-5-251128) Provider"""

    def __init__(self, api_key: str, api_url: str = "https://yunwu.ai/v1"):
        super().__init__(api_key, api_url)
        self.generation_url = f"{api_url}/images/generations"
        self.model = "doubao-seedream-4-5-251128"
        self.download_timeout = 60
        self.generation_timeout = 300

    def get_provider_name(self) -> str:
        return "SeeDream"

    def supports_multi_image_input(self) -> bool:
        return True

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """
        生成图片

        支持三种模式：
        1. 纯文字生成（无底图）
        2. 单图生成（1张底图）
        3. 多图生成（多张底图）
        """
        try:
            # 构建 payload
            payload = {
                "model": self.model,
                "prompt": request.prompt,
                "size": request.size or "2K",
                "watermark": request.watermark,
                "response_format": "b64_json"  # 强制使用 base64 格式返回
            }

            # 处理底图
            if request.images:
                if len(request.images) == 1:
                    # 单图模式：image 是字符串
                    image_data_url = self._convert_to_base64_url(request.images[0])
                    payload["image"] = image_data_url
                    logger.info(f"[SeeDream] 单图模式，底图大小: {len(request.images[0])} bytes")
                else:
                    # 多图模式：image 是数组
                    image_data_urls = [self._convert_to_base64_url(img) for img in request.images]
                    payload["image"] = image_data_urls
                    payload["sequential_image_generation"] = "enabled" if request.sequential_generation else "disabled"
                    logger.info(f"[SeeDream] 多图模式，图片数量: {len(request.images)}")
            else:
                # 纯文字生成模式
                logger.info(f"[SeeDream] 纯文字生成模式")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            logger.info(f"[SeeDream] 开始生成图片...")
            logger.debug(f"[SeeDream] Prompt: {request.prompt[:100]}...")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.generation_url,
                    headers=headers,
                    json=payload,
                    timeout=self.generation_timeout
                )
                response.raise_for_status()

                result = response.json()
                data_item = result.get("data", [{}])[0]

                # 优先处理URL格式
                image_url = data_item.get("url")
                if image_url:
                    logger.info(f"[SeeDream] 下载生成的图片...")
                    image_data = await self._download_image(image_url)
                    if image_data:
                        logger.info(f"[SeeDream] ✅ 图片生成成功，大小: {len(image_data)} bytes")
                        return ImageGenerationResponse(
                            success=True,
                            image_data=image_data,
                            image_url=image_url,
                            metadata={"provider": "seedream", "model": self.model}
                        )

                # 处理base64格式
                b64_json = data_item.get("b64_json")
                if b64_json:
                    import base64
                    image_data = base64.b64decode(b64_json)
                    logger.info(f"[SeeDream] ✅ 图片生成成功（base64），大小: {len(image_data)} bytes")
                    return ImageGenerationResponse(
                        success=True,
                        image_data=image_data,
                        metadata={"provider": "seedream", "model": self.model}
                    )

                # 未返回有效数据
                error_msg = "API未返回有效的图片数据"
                logger.error(f"[SeeDream] ❌ {error_msg}: {result}")
                return ImageGenerationResponse(success=False, error=error_msg)

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP错误 {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"[SeeDream] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

        except Exception as e:
            error_msg = f"生成失败: {str(e)}"
            logger.error(f"[SeeDream] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True, timeout=self.download_timeout)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"[SeeDream] 下载图片失败: {e}")
            return None
