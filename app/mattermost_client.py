import asyncio
import websockets
import json
import os
import logging
import httpx  # 添加这一行到顶部导入区
import datetime
import time
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
        self.chat_engine = ChatEngine()  # ✅ 初始化对话引擎
        
        # 消息缓冲相关
        self.channel_buffers: Dict = {}  # {channel_id: {"messages": [], "last_update": timestamp}}
        self.processing_tasks: Dict = {}  # {channel_id: asyncio.Task}

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
        retries = 5
        delay = 5  # seconds
        for i in range(retries):
            try:
                await self.fetch_bot_user_id()
                logging.info(f"Connecting to {self.websocket_url}...")
                self.connection = await websockets.connect(
                    self.websocket_url, extra_headers={"Authorization": f"Bearer {self.token}"}
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

                logging.info(
                    f"💬 Received message: {message} from channel {channel_id} by {user_id}"
                )
                
                # 存储到内存缓冲区
                get_channel_memory(channel_id).add_message("user", message)
                get_channel_memory(channel_id).persist_if_needed()

                # 添加到消息缓冲区并启动智能处理
                await self._add_to_buffer_and_process(channel_id, message)

    async def _add_to_buffer_and_process(self, channel_id: str, message: str):
        """添加消息到缓冲区并启动智能处理"""
        current_time = time.time()
        
        # 检查是否是简单消息且缓冲区为空
        # 注意：这里调用 chat_engine 的 _needs_summary 方法，需要传入列表
        is_simple_message = not self.chat_engine._needs_summary([message])
        buffer_is_empty = channel_id not in self.channel_buffers or not self.channel_buffers[channel_id]["messages"]

        if is_simple_message and buffer_is_empty:
            logging.info(f"⚡ 收到简单消息 '{message}'，立即回复。")
            # 立即处理简单消息，不经过缓冲和延迟
            buffer = ""
            async for segment in self.chat_engine.stream_reply_single(channel_id, message):
                # 合并连续内容
                if not buffer:
                    buffer = segment
                else:
                    buffer += "\n" + segment

                # 当积累到一定长度或遇到自然断点时发送
                if len(buffer) > 80 or segment.endswith(
                    (".", "?", "!", "。", "？", "！")
                ):
                    if buffer.strip():
                        # 移除末尾的句号或句号
                        cleaned_buffer = buffer.strip()
                        if cleaned_buffer.endswith((".", "。")):
                            cleaned_buffer = cleaned_buffer[:-1]
                        await self.send_message(channel_id, cleaned_buffer)
                        # 按字数延迟，每个字0.5秒
                        await asyncio.sleep(len(cleaned_buffer) * 0.5)
                        buffer = ""

            # 发送最后剩余内容
            if buffer.strip():
                # 移除末尾的句号或句号
                cleaned_buffer = buffer.strip()
                if cleaned_buffer.endswith((".", "。")):
                    cleaned_buffer = cleaned_buffer[:-1]
                await self.send_message(channel_id, cleaned_buffer)
                # 按字数延迟，每个字0.5秒
                await asyncio.sleep(len(cleaned_buffer) * 0.5)
            return # 简单消息处理完毕，直接返回

        # 否则，消息进入正常缓冲流程
        # 初始化或更新缓冲区
        if channel_id not in self.channel_buffers:
            self.channel_buffers[channel_id] = {
                "messages": [],
                "last_update": current_time
            }
        
        # 添加新消息
        self.channel_buffers[channel_id]["messages"].append(message)
        self.channel_buffers[channel_id]["last_update"] = current_time
        
        logging.info(f"📝 添加消息到缓冲区，频道 {channel_id} 现有 {len(self.channel_buffers[channel_id]['messages'])} 条消息")
        
        # 如果已有处理任务在运行，取消它
        if channel_id in self.processing_tasks:
            self.processing_tasks[channel_id].cancel()
        
        # 启动新的智能延迟处理任务
        self.processing_tasks[channel_id] = asyncio.create_task(
            self._smart_delay_and_process(channel_id)
        )

    async def _smart_delay_and_process(self, channel_id: str):
        """智能延迟处理：2秒超时 OR 信息收集完成"""
        try:
            messages = self.channel_buffers[channel_id]["messages"].copy()
            logging.info(f"🤔 开始智能处理，频道 {channel_id}，消息数：{len(messages)}")
            
            # 同时启动两个任务：信息收集和2秒延迟
            info_task = asyncio.create_task(
                self.chat_engine._collect_context_info(channel_id, messages)
            )
            delay_task = asyncio.create_task(asyncio.sleep(4.0))
            
            # 等待任一任务完成
            done, pending = await asyncio.wait(
                [info_task, delay_task], 
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 取消未完成的任务
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            # 开始生成回复
            context_info = info_task.result() if info_task.done() else None
            await self._generate_and_send_reply(channel_id, messages, context_info)
            
        except asyncio.CancelledError:
            logging.info(f"⚠️ 处理任务被取消，频道 {channel_id}")
            # 当任务被取消时，不需要做额外处理，因为新的任务会接管
        except Exception as e:
            logging.error(f"❌ 智能处理出错，频道 {channel_id}: {e}")
        finally:
            # 清理处理任务记录
            # 只有当任务正常完成（没有被取消）时才清理，否则新的任务会覆盖它
            if channel_id in self.processing_tasks and self.processing_tasks[channel_id].done():
                del self.processing_tasks[channel_id]

    async def _generate_and_send_reply(self, channel_id: str, processed_messages: List[str], context_info=None):
        """生成并发送回复"""
        try:
            # 获取当前缓冲区中的所有消息，这是最新的消息集合
            # 注意：这里不再使用传入的 processed_messages，而是从缓冲区获取最新状态
            if channel_id not in self.channel_buffers:
                logging.warning(f"缓冲区中没有频道 {channel_id} 的消息，可能已被其他任务处理或清空。")
                return
            
            current_messages_in_buffer = self.channel_buffers[channel_id]["messages"]
            
            logging.info(f"🧠 开始生成回复，频道 {channel_id}，处理消息数：{len(current_messages_in_buffer)}")
            
            # 流式生成回复
            buffer = ""
            async for segment in self.chat_engine.stream_reply(channel_id, current_messages_in_buffer, context_info):
                # 合并连续内容
                if not buffer:
                    buffer = segment
                else:
                    buffer += "\n" + segment

                # 当积累到一定长度或遇到自然断点时发送
                if len(buffer) > 80 or segment.endswith(
                    (".", "?", "!", "。", "？", "！")
                ):
                    if buffer.strip():
                        # 移除末尾的句号或句号
                        cleaned_buffer = buffer.strip()
                        if cleaned_buffer.endswith((".", "。")):
                            cleaned_buffer = cleaned_buffer[:-1]
                        await self.send_message(channel_id, cleaned_buffer)
                        # 按字数延迟，每个字0.5秒
                        await asyncio.sleep(len(cleaned_buffer) * 0.5)
                        buffer = ""

            # 发送最后剩余内容
            if buffer.strip():
                # 移除末尾的句号或句号
                cleaned_buffer = buffer.strip()
                if cleaned_buffer.endswith((".", "。")):
                    cleaned_buffer = cleaned_buffer[:-1]
                await self.send_message(channel_id, cleaned_buffer)
                # 按字数延迟，每个字0.5秒
                await asyncio.sleep(len(cleaned_buffer) * 0.5)
            
            # 成功发送回复后，清空该频道的缓冲区
            if channel_id in self.channel_buffers:
                del self.channel_buffers[channel_id]
                logging.info(f"🧹 清空频道 {channel_id} 的消息缓冲区")
                
        except Exception as e:
            logging.error(f"❌ 生成回复出错，频道 {channel_id}: {e}")

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
