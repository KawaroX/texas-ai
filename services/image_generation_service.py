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
from .character_manager import character_manager
# 监控功能在 tasks 层使用，这里不需要导入
# from .image_generation_monitor import image_generation_monitor

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
        self.generation_timeout = 300  # 场景图生成超时（从120秒增加到300秒/5分钟）
        self.selfie_timeout = 480     # 自拍生成超时（从180秒增加到480秒/8分钟）
        self.multi_character_timeout = 600  # 多角色场景生成超时（从300秒增加到600秒/10分钟）
        self.download_timeout = 60    # 图片下载超时（从30秒增加到60秒）
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
            style_suggestion = "根据当前场景设计合适的日常服装：工作场合可以是简洁的工装服配热裤等得体搭配，休闲时刻可以是舒适的日常服或热裤等轻松搭配。整体保持好看和有个性。"
        
        return f"{clothing_prompt} {style_suggestion}"

    async def _build_multipart_data(self, image_data: bytes, prompt: str) -> Dict:
        """构建multipart/form-data格式的请求体，参考API最佳实践"""
        import uuid
        # 生成boundary，使用更简单的格式
        boundary = f"wL36Yn{uuid.uuid4().hex[:12]}SA4n1v9T"
        
        # 按示例格式构建dataList
        dataList = []
        
        # 图片部分
        dataList.append(f'--{boundary}'.encode('utf-8'))
        dataList.append('Content-Disposition: form-data; name=image; filename=base_image.png'.encode('utf-8'))
        dataList.append('Content-Type: image/png'.encode('utf-8'))
        dataList.append(b'')
        dataList.append(image_data)
        
        # prompt部分
        dataList.append(f'--{boundary}'.encode('utf-8'))
        dataList.append('Content-Disposition: form-data; name=prompt;'.encode('utf-8'))
        dataList.append('Content-Type: text/plain'.encode('utf-8'))
        dataList.append(b'')
        dataList.append(prompt.encode('utf-8'))
        
        # model部分
        dataList.append(f'--{boundary}'.encode('utf-8'))
        dataList.append('Content-Disposition: form-data; name=model;'.encode('utf-8'))
        dataList.append('Content-Type: text/plain'.encode('utf-8'))
        dataList.append(b'')
        dataList.append('gpt-image-1-all'.encode('utf-8'))
        
        # n部分
        dataList.append(f'--{boundary}'.encode('utf-8'))
        dataList.append('Content-Disposition: form-data; name=n;'.encode('utf-8'))
        dataList.append('Content-Type: text/plain'.encode('utf-8'))
        dataList.append(b'')
        dataList.append('1'.encode('utf-8'))
        
        # size部分
        dataList.append(f'--{boundary}'.encode('utf-8'))
        dataList.append('Content-Disposition: form-data; name=size;'.encode('utf-8'))
        dataList.append('Content-Type: text/plain'.encode('utf-8'))
        dataList.append(b'')
        dataList.append('1024x1536'.encode('utf-8'))
        
        # 结束boundary
        dataList.append(f'--{boundary}--'.encode('utf-8'))
        dataList.append(b'')
        
        # 组合body
        body = b'\r\n'.join(dataList)
        
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

        # 检测场景中是否包含其他角色
        detected_characters = character_manager.detect_characters_in_text(experience_description)
        logger.info(f"🔍 检测到场景中的角色: {detected_characters}")
        
        # 如果检测到角色，尝试使用角色图片增强生成
        if detected_characters:
            return await self._generate_scene_with_characters(experience_description, detected_characters)
        else:
            return await self._generate_scene_without_characters(experience_description)
    
    async def _generate_scene_without_characters(self, experience_description: str) -> Optional[str]:
        """生成不包含特定角色的场景图"""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"}
        prompt = (
            f"请根据下面的体验和想法或者经历，生成一张第一人称视角的场景图片。"
            f"视角要求：以拍摄者的第一人称视角构图，重点展现所处的环境、场景和氛围，画面中不要出现拍摄者本人。"
            f"构图重点：突出场景环境、物品、建筑、风景等，而非人物角色。如果场景中确实需要其他人物，应作为背景元素而非主体。"
            f"艺术风格要求：保持明日方舟游戏的二次元动漫画风，避免过于写实的三次元风格，色彩明亮，构图富有故事感。"
            f"场景描述: {experience_description}"
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
    
    async def _generate_scene_with_characters(self, experience_description: str, detected_characters: List[str]) -> Optional[str]:
        """生成包含特定角色的场景图"""
        logger.info(f"🎭 使用角色增强生成场景图: {detected_characters}")
        
        # 选择主要角色作为base图片（选择第一个检测到的角色）
        main_character = detected_characters[0]
        character_image_path = character_manager.get_character_image_path(main_character)
        
        if not character_image_path:
            logger.warning(f"❌ 未找到角色 {main_character} 的本地图片，回退到普通场景生成")
            return await self._generate_scene_without_characters(experience_description)
        
        # 读取角色图片
        try:
            with open(character_image_path, 'rb') as f:
                character_image_data = f.read()
            logger.info(f"✅ 成功读取角色图片: {main_character} -> {character_image_path}")
        except Exception as e:
            logger.error(f"❌ 无法读取角色图片: {e}")
            return await self._generate_scene_without_characters(experience_description)
        
        # 🆕 获取动态服装建议（借鉴自拍的设计理念）
        clothing_prompt = await self._get_weather_based_clothing_prompt()
        
        # 构建包含所有角色信息的提示词
        character_descriptions = self._build_character_descriptions(detected_characters, main_character)
        
        prompt = (
            f"请将这张角色图片作为基础，根据以下场景描述，生成一张高质量的二次元风格多角色场景图片。"
            f"艺术风格要求：保持明日方舟游戏的二次元动漫画风，避免过于写实的三次元风格，色彩明亮，构图富有故事感。"
            f"角色信息：{character_descriptions}"
            f"服装设计要求：所有角色都需要重新设计符合当前场景的服装，不要直接沿用底图原有服装。{clothing_prompt} 每个角色的服装应该体现其个性特色并与场景氛围协调。"
            f"神态表情要求：根据各角色性格特点设计表情神态 - 能天使（活泼开朗的笑容），可颂（慵懒随意的神情），空（安静温和的表情），拉普兰德（略带野性的神态），大帝（威严中带着亲和）等。神态要贴合当前场景情境。"
            f"动作姿态要求：角色的动作和姿态要自然融入场景，展现真实的互动感和生活感。避免死板的pose，要有生动的肢体语言和场景互动，体现角色间的关系。"
            f"场景融合要求：确保所有角色都真实自然地参与到场景中，服装、动作、表情都要与环境完美匹配，营造生动的生活画面。"
            f"场景描述: {experience_description}"
        )
        
        try:
            # 使用类似自拍的multipart上传方式
            multipart_data = await self._build_multipart_data(character_image_data, prompt)
            
            headers_multipart = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json", 
                "Content-Type": multipart_data["content_type"]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.edit_url,  # 使用edit端点，类似自拍
                    headers=headers_multipart,
                    content=multipart_data["body"],
                    timeout=self.multi_character_timeout  # 使用更长的超时时间
                )
                response.raise_for_status()
                result = response.json()
                data_item = result.get("data", [{}])[0]
                
                # 处理生成结果
                image_url = data_item.get("url")
                if image_url:
                    generated_image_data = await self._download_image(image_url)
                    if generated_image_data:
                        filepath = self._save_image(generated_image_data)
                        await bark_notifier.send_notification("德克萨斯AI-多角色场景图成功", f"包含角色: {', '.join(detected_characters)}", "TexasAIPics")
                        return filepath
                
                # 处理base64格式
                b64_json = data_item.get("b64_json")
                if b64_json:
                    import base64
                    try:
                        image_data = base64.b64decode(b64_json)
                        filepath = self._save_image(image_data)
                        await bark_notifier.send_notification("德克萨斯AI-多角色场景图成功", f"包含角色: {', '.join(detected_characters)}", "TexasAIPics")
                        return filepath
                    except Exception as decode_error:
                        logger.error(f"❌ base64解码失败: {decode_error}")
                
                logger.error(f"❌ 多角色场景图生成API未返回有效数据: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 多角色场景图生成异常: {e}")
            await bark_notifier.send_notification("德克萨斯AI-多角色场景图失败", f"错误: {str(e)[:100]}...", "TexasAIPics")
            return None
    
    def _build_character_descriptions(self, characters: List[str], main_character: str) -> str:
        """构建角色描述信息"""
        descriptions = []
        
        # 角色特征描述
        character_traits = {
            "能天使": "活泼开朗的天使族女孩，红色头发，头顶有光圈，多个长三角形组成的光翼，充满活力",
            "可颂": "乐观开朗活泼的企鹅物流成员，橙色头发",
            "空": "活泼开朗的干员，黄色头发，明快的表情",
            "拉普兰德": "过于开朗特别活泼的狼族干员，白色头发，狼耳朵，古灵精怪略带病娇的笑容",
            "大帝": "喜欢说唱的帝企鹅，戴着墨镜和大金链子，西海岸嘻哈风格，企鹅形态而非人形"
        }
        
        descriptions.append(f"主要角色：{main_character}（{character_traits.get(main_character, '明日方舟角色')}）")
        
        if len(characters) > 1:
            other_chars = [char for char in characters if char != main_character]
            other_descriptions = [f"{char}（{character_traits.get(char, '明日方舟角色')}）" for char in other_chars]
            descriptions.append(f"其他角色：{', '.join(other_descriptions)}")
        
        return " ".join(descriptions)

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
        
        # 检测场景中是否包含其他角色
        detected_characters = character_manager.detect_characters_in_text(experience_description)
        other_characters_desc = ""
        if detected_characters:
            logger.info(f"🔍 自拍场景中检测到其他角色: {detected_characters}")
            character_traits = {
                "能天使": "活泼开朗的天使族女孩，红色头发，头顶有光圈，多个长三角形组成的光翼，充满活力",
                "可颂": "乐观开朗活泼的企鹅物流成员，橙色头发",
                "空": "活泼开朗的干员，黄色头发，明快的表情",
                "拉普兰德": "过于开朗特别活泼的狼族干员，白色头发，狼耳朵，古灵精怪略带病娇的笑容",
                "大帝": "喜欢说唱的帝企鹅，戴着墨镜和大金链子，西海岸嘻哈风格，企鹅形态而非人形"
            }
            char_descriptions = [f"{char}（{character_traits.get(char, '明日方舟角色')}）" for char in detected_characters]
            other_characters_desc = f"场景中的其他角色：{', '.join(char_descriptions)}。"
        
        prompt = (
            f"请将这张人物图片作为基础，根据以下场景描述，生成一张人物在该场景下的高质量二次元风格自拍照片。"
            f"艺术风格要求：保持明日方舟游戏的二次元动漫画风，避免过于写实的三次元风格。"
            f"主角特征要求：德克萨斯（黑色头发，兽耳），必须保持独特的渐变色眼眸，BOTH EYES must have gradient colors from blue (top) to orange (bottom)，两只眼睛都是从蓝色（上半部分）渐变到橙色（下半部分），这是区别于其他角色的重要特征。"
            f"人物的面部特征、黑色发型和整体风格需要与原图保持高度一致。"
            f"{other_characters_desc}"
            f"性格表情要求：德克萨斯性格高冷内敛，通常表情淡漠不苟言笑。但面对信任的人时会微妙地放下防备，可能会有极其细微的笑意或温和神情，但绝不是明显的笑容。表情应该体现这种微妙的情感变化。"
            f"服装设计要求：{clothing_prompt}"
            f"构图要求：Selfie pose with one arm extended holding phone (but don't show the phone/camera in frame)，一只手臂自然伸出做自拍手势但画面中不要显示手机或相机设备。"
            f"场景融合：姿势、神态和背景需要完全融入新的场景，营造自然的自拍效果。"
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