"""
GPT-Image-1.5-All Provider

支持 gpt-image-1.5-all 模型的图片生成
- 纯文字生成（Text-to-Image）
- 单图生图（Single Image-to-Image）
- 不支持多图生图
"""

import httpx
from typing import Optional
from utils.logging_config import get_logger
from .base import BaseImageProvider, ImageGenerationRequest, ImageGenerationResponse

logger = get_logger(__name__)


class GPTImageProvider(BaseImageProvider):
    """GPT-Image-1.5-All Provider"""

    def __init__(self, api_key: str, api_url: str = "https://yunwu.ai/v1"):
        super().__init__(api_key, api_url)
        self.model = "gpt-image-1.5-all"
        self.download_timeout = 60
        self.generation_timeout = 600  # 10分钟超时

    def get_provider_name(self) -> str:
        return "GPT-Image-1.5-All"

    def supports_multi_image_input(self) -> bool:
        """不支持多图输入"""
        return False

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """
        生成图片

        支持两种模式：
        1. 纯文字生成（无底图）- 使用 /v1/images/generations
        2. 单图生成（1张底图）- 使用 /v1/images/edits
        3. 多图生成 - 不支持，返回错误
        """
        try:
            # 检查是否为多图请求
            if request.images and len(request.images) > 1:
                error_msg = f"{self.get_provider_name()} 不支持多图输入，请使用其他 Provider"
                logger.error(f"[GPTImage] ❌ {error_msg}")
                return ImageGenerationResponse(success=False, error=error_msg)

            # 根据是否有底图选择不同的端点
            if request.images and len(request.images) == 1:
                # 单图模式：使用 /v1/images/edits
                return await self._generate_with_single_image(request)
            else:
                # 纯文字模式：使用 /v1/images/generations
                return await self._generate_text_to_image(request)

        except Exception as e:
            error_msg = f"生成失败: {str(e)}"
            logger.error(f"[GPTImage] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

    async def _generate_text_to_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """纯文字生成"""
        try:
            logger.info(f"[GPTImage] 纯文字生成模式")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "prompt": request.prompt,
                "size": request.size or "1024x1536",
                "n": 1
            }

            logger.info(f"[GPTImage] 开始生成图片 (纯文字)...")
            logger.debug(f"[GPTImage] Prompt: {request.prompt[:100]}...")

            async with httpx.AsyncClient(timeout=self.generation_timeout) as client:
                response = await client.post(
                    f"{self.api_url}/images/generations",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

            # 处理响应
            return await self._process_response(result)

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP错误 {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"[GPTImage] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

    async def _generate_with_single_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """单图生成（使用 /v1/images/edits）"""
        try:
            logger.info(f"[GPTImage] 单图生成模式")

            # 将图片保存到临时文件
            from tempfile import NamedTemporaryFile
            import os

            temp_file = NamedTemporaryFile(delete=False, suffix='.png')
            temp_file.write(request.images[0])
            temp_file.flush()
            temp_file.close()

            try:
                headers = {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }

                # 准备表单数据
                data = {
                    'prompt': request.prompt,
                    'model': self.model,
                    'n': '1',
                    'size': request.size or "1024x1536"
                }

                # 准备文件上传
                with open(temp_file.name, 'rb') as f:
                    files = {
                        'image': ('image.png', f, 'image/png')
                    }

                    logger.info(f"[GPTImage] 开始生成图片 (单图)...")
                    logger.debug(f"[GPTImage] Prompt: {request.prompt[:100]}...")

                    async with httpx.AsyncClient(timeout=self.generation_timeout) as client:
                        response = await client.post(
                            f"{self.api_url}/images/edits",
                            headers=headers,
                            data=data,
                            files=files
                        )
                        response.raise_for_status()
                        result = response.json()

                # 处理响应
                return await self._process_response(result)

            finally:
                # 删除临时文件
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP错误 {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"[GPTImage] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

    async def _process_response(self, result: dict) -> ImageGenerationResponse:
        """处理API响应"""
        try:
            data_item = result.get("data", [{}])[0]

            # 优先处理 URL 格式
            image_url = data_item.get("url")
            if image_url:
                logger.info(f"[GPTImage] 下载生成的图片...")
                image_data = await self._download_image(image_url)
                if image_data:
                    logger.info(f"[GPTImage] ✅ 图片生成成功，大小: {len(image_data)} bytes")
                    return ImageGenerationResponse(
                        success=True,
                        image_data=image_data,
                        image_url=image_url,
                        metadata={"provider": "gpt-image", "model": self.model}
                    )

            # 处理 base64 格式
            b64_json = data_item.get("b64_json")
            if b64_json:
                import base64
                image_data = base64.b64decode(b64_json)
                logger.info(f"[GPTImage] ✅ 图片生成成功（base64），大小: {len(image_data)} bytes")
                return ImageGenerationResponse(
                    success=True,
                    image_data=image_data,
                    metadata={"provider": "gpt-image", "model": self.model}
                )

            # 未返回有效数据
            error_msg = "API未返回有效的图片数据"
            logger.error(f"[GPTImage] ❌ {error_msg}: {result}")
            return ImageGenerationResponse(success=False, error=error_msg)

        except Exception as e:
            error_msg = f"处理响应失败: {str(e)}"
            logger.error(f"[GPTImage] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片"""
        try:
            async with httpx.AsyncClient(timeout=self.download_timeout) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"[GPTImage] 下载图片失败: {e}")
            return None
