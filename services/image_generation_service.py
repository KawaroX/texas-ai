import httpx
import logging
import os
import random
import uuid
import redis
from datetime import datetime
from typing import List, Optional

from app.config import settings
# 修正：导入新的 Bark 推送服务
from .bark_notifier import bark_notifier

logger = logging.getLogger(__name__)

IMAGE_SAVE_DIR = "/app/generated_content/images"  # 在 Docker 容器内的路径
os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)


class ImageGenerationService:
    def __init__(self):
        # 使用专用的图片生成API Key
        self.api_key = settings.IMAGE_GENERATION_API_KEY
        base_url = settings.IMAGE_GENERATION_API_URL
        self.generation_url = f"{base_url}/generations"
        self.edit_url = f"{base_url}/edits"
        
        # 超时配置 (秒)
        self.generation_timeout = 120  # 场景图生成超时
        self.selfie_timeout = 180     # 自拍生成超时  
        self.download_timeout = 30    # 图片下载超时
        self.selfie_base_urls = [
            "https://media.prts.wiki/6/65/%E7%AB%8B%E7%BB%98_%E7%BC%84%E9%BB%98%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_1.png?image_process=format,webp/quality,Q_90",
            "https://inf.moei.xyz/file/images/sign/fdba305f99405a1e418e5b61fa07e8bb/item/b9bc7380a3bf1f7aa2e0b15011140d01.jpg",
            "https://media.prts.wiki/f/fc/%E7%AB%8B%E7%BB%98_%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_1.png?image_process=format,webp/quality,Q_90",
            "https://media.prts.wiki/1/1f/%E7%AB%8B%E7%BB%98_%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_skin1.png?image_process=format,webp/quality,Q_90",
            "https://media.prts.wiki/2/2b/%E7%AB%8B%E7%BB%98_%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_skin2.png?image_process=format,webp/quality,Q_90"
        ]
        self.redis_client = redis.StrictRedis.from_url(
            settings.REDIS_URL, decode_responses=True
        )

    async def _get_daily_base_image_url(self) -> Optional[str]:
        """获取当天的基础自拍图片URL，如果未选定则随机选择并存入Redis。"""
        if not self.selfie_base_urls:
            logger.warning("⚠️ 未配置 TEXAS_SELFIE_BASE_URLS，无法生成自拍。")
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        redis_key = f"daily_selfie_base_url:{today}"

        cached_url = self.redis_client.get(redis_key)
        if cached_url:
            logger.info(f"📸 从Redis缓存中获取到今天的自拍底图: {cached_url}")
            return cached_url
        else:
            new_url = random.choice(self.selfie_base_urls)
            self.redis_client.set(redis_key, new_url, ex=90000)  # 25小时过期
            logger.info(f"📸 今天首次生成自拍，已选定新的底图并存入Redis: {new_url}")
            await bark_notifier.send_notification(
                title="德克萨斯AI-每日自拍底图已选定",
                body=f"今日用于自拍的基础图片已选定，URL为: {new_url}",
                group="TexasAIPics",
                image_url=new_url
            )
            return new_url

    def _get_dynamic_clothing_prompt(self) -> str:
        """根据季节和星期动态生成服装建议。"""
        month = datetime.now().month
        weekday = datetime.now().weekday() # Monday is 0 and Sunday is 6

        # 季节判断
        if month in [12, 1, 2]:
            seasonal_suggestion = "穿着暖和的冬装，比如厚外套、毛衣或围巾。"
        elif month in [3, 4, 5]:
            seasonal_suggestion = "穿着舒适的春季服装，比如夹克或长袖衫。"
        elif month in [6, 7, 8]:
            seasonal_suggestion = "穿着清凉的夏日服装，比如T恤、短袖或连衣裙。"
        else: # 9, 10, 11
            seasonal_suggestion = "穿着时尚的秋季服装，比如风衣或薄毛衣。"

        # 星期判断
        if weekday >= 5: # Saturday or Sunday
            style_suggestion = "可以是时尚漂亮的周末私服，风格可以大胆一些。"
        else:
            style_suggestion = "请设计成一套合身得体的日常便服。"
        
        return f"{seasonal_suggestion} {style_suggestion}"

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片内容"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True, timeout=self.download_timeout)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ 下载图片失败 (HTTP Status): {e.response.status_code} for URL: {url}")
            return None
        except Exception as e:
            logger.error(f"❌ 下载图片时发生未知异常: {e} for URL: {url}")
            return None

    def _save_image(self, image_data: bytes, extension: str = "png") -> str:
        """将图片数据保存到本地文件"""
        today_dir = os.path.join(IMAGE_SAVE_DIR, datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(today_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}.{extension}"
        filepath = os.path.join(today_dir, filename)
        with open(filepath, "wb") as f:
            f.write(image_data)
        logger.info(f"🖼️ 图片已保存到: {filepath}")
        return filepath

    async def generate_image_from_prompt(self, experience_description: str) -> Optional[str]:
        """根据经历描述生成图片"""
        await bark_notifier.send_notification("德克萨斯AI-开始生成场景图", f"内容: {experience_description[:50]}...", "TexasAIPics")
        if not self.api_key:
            logger.warning("⚠️ 未配置 OPENAI_API_KEY，跳过图片生成。")
            await bark_notifier.send_notification("德克萨斯AI-生成场景图失败", "错误: 未配置OPENAI_API_KEY", "TexasAIPics")
            return None

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"}
        prompt = (
            f"请根据下面的体验和想法或者经历, 生成一张符合这个场景的图片。"
            f"风格请偏向于日本动漫风格, 色彩明亮, 构图富有故事感。场景描述: {experience_description}"
        )
        payload = {"size": "1024x1536", "prompt": prompt, "model": "gpt-image-1", "n": 1}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.generation_url, headers=headers, json=payload, timeout=self.generation_timeout)
                response.raise_for_status()
                result = response.json()
                image_url = result.get("data", [{}])[0].get("url")
                if not image_url:
                    logger.error(f"❌ 图片生成API未返回有效的URL: {result}")
                    await bark_notifier.send_notification("德克萨斯AI-生成场景图失败", f"错误: API未返回URL。响应: {str(result)[:50]}...", "TexasAIPics")
                    return None
                image_data = await self._download_image(image_url)
                if image_data:
                    filepath = self._save_image(image_data)
                    await bark_notifier.send_notification("德克萨斯AI-生成场景图成功", f"图片已保存到 {filepath}", "TexasAIPics", image_url=image_url)
                    return filepath
                return None
        except Exception as e:
            logger.error(f"❌ 调用图片生成API时发生未知异常: {e}")
            await bark_notifier.send_notification("德克萨斯AI-生成场景图异常", f"错误: {str(e)[:100]}...", "TexasAIPics")
            return None

    async def generate_selfie(self, experience_description: str) -> Optional[str]:
        """根据经历描述和每日基础图片生成自拍，并加入季节性服装要求。"""
        await bark_notifier.send_notification("德克萨斯AI-开始生成自拍", f"内容: {experience_description[:50]}...", "TexasAIPics")
        if not self.api_key:
            logger.warning("⚠️ 未配置 OPENAI_API_KEY，跳过自拍生成。")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", "错误: 未配置OPENAI_API_KEY", "TexasAIPics")
            return None

        base_image_url = await self._get_daily_base_image_url()
        if not base_image_url:
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", "错误: 未配置或无法获取自拍底图URL", "TexasAIPics")
            return None

        base_image_data = await self._download_image(base_image_url)
        if not base_image_data:
            logger.error("❌ 无法下载每日基础自拍图片，取消生成。")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", f"错误: 无法下载底图 {base_image_url}", "TexasAIPics")
            return None

        clothing_prompt = self._get_dynamic_clothing_prompt()
        prompt = (
            f"请将这张人物图片作为基础, 根据以下场景描述, 生成一张人物在那个场景下的高质量自拍照。"
            f"重要：请为人物重新设计一套符合场景和季节的服装。{clothing_prompt}"
            f"人物的面部特征、发型和风格需要与原图保持高度一致, 但姿势、表情、特别是服装和背景需要完全融入新的场景。"
            f"风格需要自然, 就像手机自拍一样。场景描述: {experience_description}"
        )
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        files = {"image": ("base_image.png", base_image_data, "image/png")}
        data = {"prompt": prompt, "model": "gpt-image-1-all", "n": 1, "size": "1024x1536"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.edit_url, headers=headers, data=data, files=files, timeout=self.selfie_timeout)
                response.raise_for_status()
                result = response.json()
                image_url = result.get("data", [{}])[0].get("url")
                if not image_url:
                    logger.error(f"❌ 自拍生成API未返回有效的URL: {result}")
                    await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", f"错误: API未返回URL。响应: {str(result)[:50]}...", "TexasAIPics")
                    return None
                generated_image_data = await self._download_image(image_url)
                if generated_image_data:
                    filepath = self._save_image(generated_image_data)
                    await bark_notifier.send_notification("德克萨斯AI-生成自拍成功", f"图片已保存到 {filepath}", "TexasAIPics", image_url=image_url)
                    return filepath
                return None
        except Exception as e:
            logger.error(f"❌ 调用自拍生成API时发生未知异常: {e}")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍异常", f"错误: {str(e)[:100]}...", "TexasAIPics")
            return None

image_generation_service = ImageGenerationService()