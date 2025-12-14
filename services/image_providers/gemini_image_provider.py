"""
Gemini-2.5-Flash-Image Provider

支持多图输入的图片生成
"""

import httpx
import base64
from typing import List, Optional
from utils.logging_config import get_logger
from .base import BaseImageProvider, ImageGenerationRequest, ImageGenerationResponse

logger = get_logger(__name__)


class GeminiImageProvider(BaseImageProvider):
    """Gemini-2.5-Flash-Image Provider"""

    def __init__(self, api_key: str, api_url: str = "https://yunwu.ai/v1beta"):
        super().__init__(api_key, api_url)
        self.model = "gemini-2.5-flash-image"
        self.generation_url = f"{api_url}/models/{self.model}:generateContent"
        self.generation_timeout = 300

    def get_provider_name(self) -> str:
        return "Gemini-2.5-Flash-Image"

    def supports_multi_image_input(self) -> bool:
        return True

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """
        生成图片

        Gemini 使用 contents/parts 结构，支持多图输入
        """
        try:
            # 构建 parts 数组
            parts = []

            # 添加图片（如果有）
            if request.images:
                for img_data in request.images:
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": self._convert_to_base64(img_data)
                        }
                    })
                logger.info(f"[Gemini] 多图模式，图片数量: {len(request.images)}")

            # 添加文本 prompt
            # 为了保持面部特征，我们使用之前测试成功的 prompt 结构
            face_preservation_text = (
                "CRITICAL REQUIREMENTS:\n"
                "1. DO NOT modify the character's facial features, face shape, or facial structure\n"
                "2. KEEP the exact same hair color, hairstyle, and any distinctive features from the reference image\n"
                "3. KEEP the exact same eye color and eye shape\n"
                "4. PRESERVE the character's facial identity completely - only change clothing, pose, and background as specified\n"
                "5. The person's face must remain identical to the reference image\n\n"
                f"Now, based on the reference image(s) while preserving all facial features exactly, create: {request.prompt}"
            )
            parts.append({"text": face_preservation_text})

            # 构建 payload
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": parts
                    }
                ],
                "generationConfig": {
                    "responseModalities": request.response_modalities or ["TEXT", "IMAGE"]
                }
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            logger.info(f"[Gemini] 开始生成图片...")
            logger.debug(f"[Gemini] Prompt: {request.prompt[:100]}...")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.generation_url}?key={self.api_key}",
                    headers=headers,
                    json=payload,
                    timeout=self.generation_timeout
                )
                response.raise_for_status()

                result = response.json()
                logger.debug(f"[Gemini] 响应结构: {list(result.keys())}")

                # 解析 Gemini 的响应格式
                candidates = result.get("candidates", [])
                if not candidates:
                    error_msg = "API未返回candidates"
                    logger.error(f"[Gemini] ❌ {error_msg}")
                    return ImageGenerationResponse(success=False, error=error_msg)

                parts_response = candidates[0].get("content", {}).get("parts", [])

                # 查找图片数据
                for part in parts_response:
                    inline_data = part.get("inlineData") or part.get("inline_data")
                    if inline_data:
                        image_b64 = inline_data.get("data")
                        if image_b64:
                            image_data = base64.b64decode(image_b64)
                            logger.info(f"[Gemini] ✅ 图片生成成功，大小: {len(image_data)} bytes")
                            return ImageGenerationResponse(
                                success=True,
                                image_data=image_data,
                                metadata={"provider": "gemini", "model": self.model}
                            )

                # 未找到图片
                error_msg = "API未返回图片数据"
                logger.error(f"[Gemini] ❌ {error_msg}")
                logger.debug(f"[Gemini] 完整响应: {result}")
                return ImageGenerationResponse(success=False, error=error_msg)

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP错误 {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"[Gemini] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)

        except Exception as e:
            error_msg = f"生成失败: {str(e)}"
            logger.error(f"[Gemini] ❌ {error_msg}")
            return ImageGenerationResponse(success=False, error=error_msg)
