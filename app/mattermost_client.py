import asyncio
import websockets
import json
import os
import logging
import httpx
import datetime, time
import redis  # 导入 redis
import random
from typing import Dict, List
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
        self.chat_engine = ChatEngine()

        # 消息缓冲相关
        self.processing_tasks: Dict = {}  # {channel_id: asyncio.Task}
        self.redis_client = redis.StrictRedis.from_url(
            settings.REDIS_URL, decode_responses=True
        )  # 初始化 Redis 客户端

        # 缓存
        self.channel_info_cache = {}
        self.user_info_cache = {}

        # 频道活动状态跟踪
        self.channel_activity = {}  # {channel_id: {"last_activity": timestamp}}

    async def get_channel_info(self, channel_id):
        if channel_id in self.channel_info_cache:
            return self.channel_info_cache[channel_id]

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/channels/{channel_id}", headers=headers
            )
            if resp.status_code == 200:
                data = resp.json()
                info = {
                    "name": data["name"],
                    "display_name": data["display_name"],
                    "type": data["type"],
                }
                self.channel_info_cache[channel_id] = info
                return info
            else:
                logging.warning(f"⚠️ 无法获取频道信息: {resp.status_code} - {resp.text}")
                return None

    async def get_user_info(self, user_id):
        if user_id in self.user_info_cache:
            return self.user_info_cache[user_id]

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/users/{user_id}", headers=headers
            )
            if resp.status_code == 200:
                data = resp.json()
                info = {
                    "username": data["username"],
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "nickname": data["nickname"],
                    "full_name": f"{data['first_name']} {data['last_name']}".strip(),
                }
                self.user_info_cache[user_id] = info
                return info
            else:
                logging.warning(f"⚠️ 无法获取用户信息: {resp.status_code} - {resp.text}")
                return None

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
        retries = 3
        delay = 10
        for i in range(retries):
            try:
                await self.fetch_bot_user_id()
                logging.info(f"Connecting to {self.websocket_url}...")
                self.connection = await websockets.connect(
                    self.websocket_url,
                    extra_headers={"Authorization": f"Bearer {self.token}"},
                )
                logging.info("✅ WebSocket connected.")
                await self.listen()
                return
            except Exception as e:
                logging.error(f"❌ Connection attempt {i+1}/{retries} failed: {e}")
                if i < retries - 1:
                    logging.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logging.error("❌ All connection attempts failed. Exiting.")
                    raise

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

                # 更新频道活动状态
                self.channel_activity[channel_id] = {"last_activity": time.time()}

                # 获取频道和用户信息
                channel_info = await self.get_channel_info(channel_id)
                user_info = await self.get_user_info(user_id)

                logging.info(
                    f"💬 Received message: {message} from channel {channel_id} ({channel_info['display_name'] if channel_info else 'Unknown'}) by {user_info['username'] if user_info else user_id}"
                )

                # 存储到内存缓冲区
                get_channel_memory(channel_id).add_message("user", message)
                get_channel_memory(channel_id).persist_if_needed()

                # 添加到消息缓冲区并启动智能处理
                await self._add_to_buffer_and_process(
                    channel_id, message, channel_info, user_info
                )

            elif event == "user_typing":
                # 处理用户打字事件
                typing_data = data["data"]
                channel_id = typing_data.get("channel_id")
                user_id = typing_data.get("user_id")

                if channel_id and user_id != self.user_id:
                    # 更新频道活动状态
                    self.channel_activity[channel_id] = {"last_activity": time.time()}
                    logging.debug(f"👀 User typing in channel {channel_id}")

    async def send_typing(self, channel_id: str):
        """发送打字指示器到指定频道"""
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.http_base_url}/api/v4/users/me/typing",
                    json={"channel_id": channel_id},
                    headers=headers
                )
                # if response.status_code == 200:
                #     logging.info(f"✅ 发送打字指示器成功，频道 {channel_id}")
                # else:
                #     logging.warning(f"⚠️ 发送打字指示器失败: {response.status_code} - {response.text}")
            except Exception as e:
                logging.warning(f"⚠️ 发送打字指示器异常: {e}")

    async def _add_to_buffer_and_process(
        self, channel_id: str, message: str, channel_info=None, user_info=None
    ):
        """添加消息到缓冲区并启动智能处理"""
        current_time = time.time()

        # 检查是否是简单消息且缓冲区为空
        is_simple_message = not self.chat_engine._needs_summary([message])
        # 检查 Redis List 是否为空
        buffer_is_empty = self.redis_client.llen(f"channel_buffer:{channel_id}") == 0

        if is_simple_message and buffer_is_empty:
            logging.info(f"⚡ 收到简单消息 '{message}'，立即回复。")
            # 立即处理简单消息，不经过缓冲和延迟
            buffer = ""
            async for segment in self.chat_engine.stream_reply_single(
                channel_id, message, channel_info, user_info
            ):
                if segment.strip():
                    cleaned_segment = segment.strip()
                    if cleaned_segment.endswith((".", "。")):
                        cleaned_segment = cleaned_segment[:-1]
                    # 在等待期间持续发送打字指示器
                    await self._send_message_with_typing(channel_id, cleaned_segment)
            return  # 简单消息处理完毕，直接返回

        # 否则，消息进入正常缓冲流程
        # 将消息添加到 Redis List
        self.redis_client.rpush(f"channel_buffer:{channel_id}", message)

        # 将新消息缓存到 Redis，供 context_merger 使用
        # 假设 user_info 包含 username
        username = user_info.get('username', '未知用户') if user_info else '未知用户'
        self.redis_client.setex(
            f"mattermost_cache:{channel_id}", 
            300,  # 5分钟有效期
            f"[{username}]：{message}"
        )

        logging.info(
            f"📝 添加消息到缓冲区，频道 {channel_id} 现有 {self.redis_client.llen(f'channel_buffer:{channel_id}')} 条消息"
        )

        # 如果已有处理任务在运行，取消它
        if channel_id in self.processing_tasks:
            self.processing_tasks[channel_id].cancel()

        # 启动新的智能延迟处理任务
        self.processing_tasks[channel_id] = asyncio.create_task(
            self._smart_delay_and_process(channel_id, channel_info, user_info)
        )

    async def _smart_delay_and_process(
        self, channel_id: str, channel_info=None, user_info=None
    ):
        """智能延迟处理：根据用户活动和超时进行处理"""
        start_time = time.time()

        try:
            while True:
                # 获取最新活动时间
                current_activity_time = self.channel_activity.get(channel_id, {}).get(
                    "last_activity", start_time
                )

                # 检查超时条件
                current_time = time.time()
                total_elapsed = current_time - start_time
                activity_elapsed = current_time - current_activity_time

                # 双重超时机制：总时长30s或连续10s无活动
                if total_elapsed > 30 or activity_elapsed > 10:
                    logging.info(f"⏳ 频道 {channel_id} 达到超时条件，开始处理消息。")
                    break

                await asyncio.sleep(1)  # 每秒检查一次

            # 从 Redis 获取当前缓冲区中的所有消息
            messages = self.redis_client.lrange(f"channel_buffer:{channel_id}", 0, -1)
            logging.info(f"🤔 开始智能处理，频道 {channel_info['name']}，消息数：{len(messages)}")

            # 收集上下文信息
            context_info = await self.chat_engine._collect_context_info(
                channel_id, messages
            )

            # 开始生成回复
            await self._generate_and_send_reply(
                channel_id, messages, context_info, channel_info, user_info
            )  # 传递从 Redis 获取的消息

        except asyncio.CancelledError:
            logging.info(f"⚠️ 处理任务被取消，频道 {channel_id}")
        except Exception as e:
            logging.error(f"❌ 智能处理出错，频道 {channel_id}: {e}")
        finally:
            # 清理处理任务记录
            if (
                channel_id in self.processing_tasks
                and self.processing_tasks[channel_id].done()
            ):
                del self.processing_tasks[channel_id]

    async def _generate_and_send_reply(
        self,
        channel_id: str,
        processed_messages: List[str],
        context_info=None,
        channel_info=None,
        user_info=None,
    ):
        """生成并发送回复"""
        try:
            # processed_messages 已经是当前缓冲区中的消息列表
            logging.info(
                f"🧠 开始生成回复，频道 {channel_id}，处理消息数：{len(processed_messages)}"
            )

            # 流式生成回复
            async for segment in self.chat_engine.stream_reply(
                channel_id, processed_messages, channel_info, user_info, context_info
            ):
                if segment.strip():
                    cleaned_segment = segment.strip()
                    if cleaned_segment.endswith((".", "。")):
                        cleaned_segment = cleaned_segment[:-1]
                    # 在等待期间持续发送打字指示器
                    await self._send_message_with_typing(channel_id, cleaned_segment)

            # 成功发送回复后，清空该频道的 Redis 缓冲区
            self.redis_client.delete(f"channel_buffer:{channel_id}")
            logging.info(f"🧹 清空频道 {channel_id} 的消息缓冲区")

        except Exception as e:
            logging.error(f"❌ 生成回复出错，频道 {channel_id}: {e}")

    def _generate_typing_delay(self, text_length: int) -> float:
        """
        生成符合正态分布的打字等待时间（秒）
        - 基于 text_length * 0.2 的正态分布
        - 添加动态最大等待时间（平均7秒，浮动±1秒）
        """
        mean = text_length * 0.2
        std_dev = mean * 0.2

        # 生成主等待时间
        delay = random.normalvariate(mean, std_dev)

        # 动态最大等待时间：平均7秒，标准差1秒，限制在6~8之间
        max_dynamic = random.normalvariate(7.0, 1.0)
        max_dynamic = max(6.0, min(8.0, max_dynamic))  # 限制最大上限浮动范围

        # 截断：确保在 0.3 到动态上限之间
        return min(max(0.3, delay), max_dynamic)

    async def _send_message_with_typing(self, channel_id: str, text: str):
        """在发送消息时持续发送打字指示器"""
        typing_task = None
        try:
            # 启动一个后台任务，每隔一段时间发送一次打字指示器
            async def continuous_typing():
                while True:
                    await self.send_typing(channel_id)
                    await asyncio.sleep(3)  # Mattermost typing indicator lasts for about 5 seconds

            typing_task = asyncio.create_task(continuous_typing())

            # 等待消息发送完成，使用正态分布的随机等待时间
            delay = self._generate_typing_delay(len(text))
            await asyncio.sleep(delay)
            await self.send_message(channel_id, text)

        finally:
            if typing_task:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

    async def send_message(self, channel_id, text):
        # 移除了不必要的 strip('=\n')，因为 AI 服务已经正确处理了分段
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
