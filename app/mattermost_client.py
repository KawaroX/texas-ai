import asyncio
import websockets
import json
import os
import logging
import httpx  # 添加这一行到顶部导入区
import datetime
from config import settings
from core.memory_buffer import get_channel_memory
from core.chat_engine import ChatEngine

logging.basicConfig(level=logging.INFO)


class MattermostWebSocketClient:
    def __init__(self):
        self.http_base_url = settings.MATTERMOST_HOST
        self.websocket_url = (
            self.http_base_url.replace("http", "ws") + "/api/v4/websocket"
        )
        self.token = settings.MATTERMOST_TOKEN
        self.user_id = None
        self.chat_engine = ChatEngine()  # ✅ 初始化对话引擎

    async def fetch_bot_user_id(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/users/me", headers=headers
            )
            if resp.status_code == 200:
                self.user_id = resp.json()["id"]
                logging.info(f"✅ Bot user ID: {self.user_id}")
            else:
                logging.error("❌ Failed to fetch bot user ID")

    async def connect(self):
        await self.fetch_bot_user_id()  # 新增
        logging.info(f"Connecting to {self.websocket_url}...")
        self.connection = await websockets.connect(
            self.websocket_url, extra_headers={"Authorization": f"Bearer {self.token}"}
        )
        logging.info("✅ WebSocket connected.")
        await self.listen()

    async def listen(self):
        async for message in self.connection:
            data = json.loads(message)
            event = data.get("event")

            if event == "posted":
                post_data = json.loads(data["data"]["post"])
                user_id = post_data["user_id"]
                message = post_data["message"]
                channel_id = post_data["channel_id"]

                if user_id == self.user_id:
                    continue
                if message.startswith("🤖"):
                    continue

                logging.info(f"💬 Received message: {message}")
                get_channel_memory(channel_id).add_message("user", message)
                get_channel_memory(channel_id).persist_if_needed()

                # ✅ 流式生成 AI 回复
                buffer = ""
                async for segment in self.chat_engine.stream_reply(channel_id, message):
                    # 合并连续内容
                    if not buffer:
                        buffer = segment
                    else:
                        buffer += "\n" + segment
                    
                    # 当积累到一定长度或遇到自然断点时发送
                    if len(buffer) > 80 or segment.endswith(('.', '?', '!', '。', '？', '！')):
                        if buffer.strip():
                            await self.send_message(channel_id, buffer)
                            # 按字数延迟，每个字0.5秒
                            await asyncio.sleep(len(buffer.strip()) * 0.5)
                            buffer = ""
                
                # 发送最后剩余内容
                if buffer.strip():
                    await self.send_message(channel_id, buffer)
                    # 按字数延迟，每个字0.5秒
                    await asyncio.sleep(len(buffer.strip()) * 0.5)

    async def send_message(self, channel_id, text):
        payload = {"channel_id": channel_id, "message": text}
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.http_base_url}/api/v4/posts", json=payload, headers=headers
            )

        if response.status_code == 201:
            logging.info(f"✅ Replied with: {text}")
            get_channel_memory(channel_id).add_message("assistant", text)
            get_channel_memory(channel_id).persist_if_needed()
        else:
            logging.error(
                f"❌ Failed to send message: {response.status_code} - {response.text}"
            )


if __name__ == "__main__":
    asyncio.run(MattermostWebSocketClient().connect())
