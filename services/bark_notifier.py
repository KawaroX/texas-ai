import httpx
import logging
from urllib.parse import quote
from app.config import settings

logger = logging.getLogger(__name__)


class BarkNotifier:
    def __init__(self):
        self.base_url = f"https://api.day.app/h9F6jTtz4QYaZjkvFo7SxQ"
        # Bark不需要单独的API key，URL中已包含设备token
        self.api_key = True  # 设置为True表示启用通知

    async def send_notification(
        self, title: str, body: str, group: str, image_url: str = None
    ):
        if not self.api_key:
            return

        # URL编码标题和内容，防止特殊字符中断URL
        encoded_title = quote(title)
        encoded_body = quote(body)

        url = f"{self.base_url}/{encoded_title}/{encoded_body}?group={group}"
        if image_url:
            url += f"&icon={quote(image_url)}"  # Bark 使用 icon 参数来显示图片

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10)
                # Bark API 通常即使失败也会返回200，但我们还是检查一下以防万一
                if response.status_code == 200:
                    logger.info(f"📢 Bark 推送成功: {title}")
                else:
                    logger.warning(
                        f"⚠️ Bark 推送可能失败，状态码: {response.status_code}"
                    )
        except Exception as e:
            logger.error(f"❌ 发送 Bark 推送时发生异常: {e}")


# 创建一个单例供其他服务使用
bark_notifier = BarkNotifier()
