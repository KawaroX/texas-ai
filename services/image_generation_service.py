import httpx
import logging
import os
import uuid
import redis
from datetime import datetime
from typing import List, Optional, Dict

from app.config import settings
# 修正：导入新的 Bark 推送服务
from .bark_notifier import bark_notifier
from .selfie_base_image_manager import selfie_manager

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
        self.redis_client = redis.StrictRedis.from_url(
            settings.REDIS_URL, decode_responses=True
        )

    async def _get_daily_base_image_path(self) -> Optional[str]:
        """获取当天的基础自拍图片本地路径，如果未选定则随机选择并存入Redis。"""
        today = datetime.now().strftime("%Y-%m-%d")
        redis_key = f"daily_selfie_base_path:{today}"

        cached_path = self.redis_client.get(redis_key)
        if cached_path:
            logger.info(f"📸 从Redis缓存中获取到今天的自拍底图路径: {cached_path}")
            return cached_path
        else:
            # 使用本地图片管理器随机选择底图
            new_path = selfie_manager.get_random_local_image()
            if not new_path:
                logger.error("❌ 没有可用的本地自拍底图")
                return None
            
            self.redis_client.set(redis_key, new_path, ex=90000)  # 25小时过期
            logger.info(f"📸 今天首次生成自拍，已选定新的底图路径: {new_path}")
            await bark_notifier.send_notification(
                title="德克萨斯AI-每日自拍底图已选定",
                body=f"今日用于自拍的基础图片已选定: {os.path.basename(new_path)}",
                group="TexasAIPics"
            )
            return new_path

    async def _get_weather_based_clothing_prompt(self) -> str:
        """根据实际天气和星期动态生成服装建议。"""
        try:
            # 获取今天的天气信息
            today = datetime.now().strftime('%Y-%m-%d')
            weather_key = f"life_system:{today}"
            daily_schedule_str = self.redis_client.hget(weather_key, "daily_schedule")
            
            if daily_schedule_str:
                import json, re
                daily_data = json.loads(daily_schedule_str)
                weather_str = daily_data.get('weather', '')
                
                # 解析温度范围，例如 "28°C~33°C"
                temp_match = re.search(r'气温(\d+)°C~(\d+)°C', weather_str)
                if temp_match:
                    min_temp = int(temp_match.group(1))
                    max_temp = int(temp_match.group(2))
                    avg_temp = (min_temp + max_temp) // 2
                else:
                    avg_temp = 25  # 默认温度
                
                # 根据平均温度决定服装
                if avg_temp >= 28:
                    temp_suggestion = "穿着清凉舒适的夏日服装，比如薄T恤、短袖衫或轻薄连衣裙。"
                elif avg_temp >= 22:
                    temp_suggestion = "穿着舒适的轻便服装，比如薄长袖、衬衫或轻薄外套。"
                elif avg_temp >= 15:
                    temp_suggestion = "穿着适中的秋季服装，比如毛衣、薄外套或长袖衫。"
                elif avg_temp >= 7.5:
                    temp_suggestion = "穿着保暖的冬季服装，比如厚外套、毛衣或围巾。"
                else:
                    temp_suggestion = "穿着厚实的严寒服装，比如羽绒服、厚围巾和手套。"
                
                # 根据天气状况调整
                if '雨' in weather_str or '雷' in weather_str:
                    weather_suggestion = "考虑到雨天，可以搭配雨具或选择不易湿透的服装。"
                elif '雪' in weather_str:
                    weather_suggestion = "考虑到雪天，选择防寒保暖的服装。"
                elif '多云' in weather_str:
                    weather_suggestion = "天气较为温和，适合多种服装搭配。"
                else:
                    weather_suggestion = ""
                    
                clothing_prompt = f"{temp_suggestion} {weather_suggestion}".strip()
            else:
                # 没有天气数据时使用默认逻辑
                month = datetime.now().month
                if month in [12, 1, 2]:
                    clothing_prompt = "穿着保暖的冬季服装，比如厚外套、毛衣或围巾。"
                elif month in [3, 4, 5]:
                    clothing_prompt = "穿着舒适的春季服装，比如衬衫或轻薄外套。"
                elif month in [6, 7, 8]:
                    clothing_prompt = "穿着清凉的夏日服装，比如T恤、短袖或连衣裙。"
                else: # 9, 10, 11
                    clothing_prompt = "穿着舒适的秋季服装，比如薄毛衣或轻便外套。"
        except Exception as e:
            logger.warning(f"获取天气信息失败，使用默认服装建议: {e}")
            clothing_prompt = "穿着舒适得体的日常服装。"
        
        # 星期判断
        weekday = datetime.now().weekday() # Monday is 0 and Sunday is 6
        if weekday >= 5: # Saturday or Sunday
            style_suggestion = "可以是时尚漂亮的周末私服，风格可以大胆一些。"
        else:
            style_suggestion = "请设计成一套合身得体的日常便服。"
        
        return f"{clothing_prompt} {style_suggestion}"

    async def _build_multipart_data(self, image_data: bytes, prompt: str) -> Dict:
        """构建multipart/form-data格式的请求体，参考API最佳实践"""
        # 生成boundary
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        
        # 构建body部分
        body = b''
        
        # 图片部分
        body += f'--{boundary}\r\n'.encode('utf-8')
        body += b'Content-Disposition: form-data; name="image"; filename="base_image.png"\r\n'
        body += b'Content-Type: image/png\r\n\r\n'
        body += image_data
        body += b'\r\n'
        
        # prompt部分
        body += f'--{boundary}\r\n'.encode('utf-8')
        body += b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        body += prompt.encode('utf-8')
        body += b'\r\n'
        
        # model部分
        body += f'--{boundary}\r\n'.encode('utf-8')
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += b'gpt-image-1-all\r\n'
        
        # n部分
        body += f'--{boundary}\r\n'.encode('utf-8')
        body += b'Content-Disposition: form-data; name="n"\r\n\r\n'
        body += b'1\r\n'
        
        # size部分
        body += f'--{boundary}\r\n'.encode('utf-8')
        body += b'Content-Disposition: form-data; name="size"\r\n\r\n'
        body += b'1024x1536\r\n'
        
        # 结束boundary
        body += f'--{boundary}--\r\n'.encode('utf-8')
        
        return {
            "body": body,
            "content_type": f"multipart/form-data; boundary={boundary}"
        }

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
                data_item = result.get("data", [{}])[0]
                
                # 优先处理URL格式
                image_url = data_item.get("url")
                if image_url:
                    image_data = await self._download_image(image_url)
                    if image_data:
                        filepath = self._save_image(image_data)
                        await bark_notifier.send_notification("德克萨斯AI-生成场景图成功", f"图片已保存到 {filepath}", "TexasAIPics", image_url=image_url)
                        return filepath
                
                # 处理base64格式
                b64_json = data_item.get("b64_json")
                if b64_json:
                    import base64
                    try:
                        image_data = base64.b64decode(b64_json)
                        filepath = self._save_image(image_data)
                        await bark_notifier.send_notification("德克萨斯AI-生成场景图成功", f"图片已保存到 {filepath}", "TexasAIPics")
                        return filepath
                    except Exception as decode_error:
                        logger.error(f"❌ base64解码失败: {decode_error}")
                
                # 如果两种格式都没有
                logger.error(f"❌ 图片生成API未返回有效的图片数据: {result}")
                await bark_notifier.send_notification("德克萨斯AI-生成场景图失败", f"错误: API未返回有效数据。响应: {str(result)[:50]}...", "TexasAIPics")
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

        base_image_path = await self._get_daily_base_image_path()
        if not base_image_path:
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", "错误: 无法获取本地自拍底图", "TexasAIPics")
            return None

        # 读取本地底图文件
        try:
            with open(base_image_path, 'rb') as f:
                base_image_data = f.read()
            logger.info(f"✅ 成功读取本地底图: {base_image_path}")
        except Exception as e:
            logger.error(f"❌ 无法读取本地基础自拍图片: {e}")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", f"错误: 无法读取底图文件 {base_image_path}", "TexasAIPics")
            return None

        clothing_prompt = await self._get_weather_based_clothing_prompt()
        prompt = (
            f"请将这张人物图片作为基础，根据以下场景描述，生成一张人物在该场景下的高质量二次元风格近距离人物照片。"
            f"艺术风格要求：保持明日方舟游戏的二次元动漫画风，避免过于写实的三次元风格。"
            f"角色特征要求：人物必须保持独特的渐变色眼眸（上半部分是蓝色，下半部分是橙色，两只眼睛都是这样的渐变），这是区别于其他角色的重要特征。"
            f"人物的面部特征、银白色发型和整体风格需要与原图保持高度一致。"
            f"性格表情要求：德克萨斯性格高冷内敛，通常表情淡漠不苟言笑。但面对信任的人时会微妙地放下防备，可能会有极其细微的笑意或温和神情，但绝不是明显的笑容。表情应该体现这种微妙的情感变化。"
            f"服装设计要求：{clothing_prompt}"
            f"构图要求：画面应该是从近距离拍摄的效果，不要显示任何拍照设备（手机、相机等），画面中只显示人物和背景场景。"
            f"场景融合：姿势、神态和背景需要完全融入新的场景，营造自然的近距离拍摄效果。"
            f"场景描述: {experience_description}"
        )

        try:
            # 使用优化的multipart上传方式，参考API最佳实践
            multipart_data = await self._build_multipart_data(base_image_data, prompt)
            
            headers_multipart = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": multipart_data["content_type"]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.edit_url, 
                    headers=headers_multipart, 
                    content=multipart_data["body"], 
                    timeout=self.selfie_timeout
                )
                response.raise_for_status()
                result = response.json()
                data_item = result.get("data", [{}])[0]
                
                # 优先处理URL格式
                image_url = data_item.get("url")
                if image_url:
                    generated_image_data = await self._download_image(image_url)
                    if generated_image_data:
                        filepath = self._save_image(generated_image_data)
                        await bark_notifier.send_notification("德克萨斯AI-生成自拍成功", f"图片已保存到 {filepath}", "TexasAIPics", image_url=image_url)
                        return filepath
                
                # 处理base64格式
                b64_json = data_item.get("b64_json")
                if b64_json:
                    import base64
                    try:
                        generated_image_data = base64.b64decode(b64_json)
                        filepath = self._save_image(generated_image_data)
                        await bark_notifier.send_notification("德克萨斯AI-生成自拍成功", f"图片已保存到 {filepath}", "TexasAIPics")
                        return filepath
                    except Exception as decode_error:
                        logger.error(f"❌ 自拍base64解码失败: {decode_error}")
                
                # 如果两种格式都没有
                logger.error(f"❌ 自拍生成API未返回有效的图片数据: {result}")
                await bark_notifier.send_notification("德克萨斯AI-生成自拍失败", f"错误: API未返回有效数据。响应: {str(result)[:50]}...", "TexasAIPics")
                return None
        except Exception as e:
            logger.error(f"❌ 调用自拍生成API时发生未知异常: {e}")
            await bark_notifier.send_notification("德克萨斯AI-生成自拍异常", f"错误: {str(e)[:100]}...", "TexasAIPics")
            return None

image_generation_service = ImageGenerationService()