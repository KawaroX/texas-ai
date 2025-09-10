import asyncio
import websockets
import json
import logging
import httpx
import time
import redis  # 导入 redis
import random
import io
import os
from typing import Dict, List, Optional, Tuple
from PIL import Image
from app.config import settings
from core.memory_buffer import get_channel_memory
from core.chat_engine import ChatEngine
from services.image_service import get_image_description
from utils.image_context_formatter import format_image_description, clean_ai_image_tags

# 日志配置在 app/main.py 统一设置


class MattermostWebSocketClient:
    def __init__(self):
        self.http_base_url = settings.MATTERMOST_HOST
        # 根据是否以 https 开头，确定使用 wss 还是 ws

        if self.http_base_url.startswith("https://"):
            scheme = "wss"
            host = self.http_base_url.removeprefix("https://")
        elif self.http_base_url.startswith("http://"):
            scheme = "ws"
            host = self.http_base_url.removeprefix("http://")
        else:
            # 默认使用 ws，如果未明确指定协议
            scheme = "ws"
            host = self.http_base_url

        self.websocket_url = f"{scheme}://{host}/api/v4/websocket"

        self.token = settings.MATTERMOST_TOKEN
        self.user_id = None
        self.chat_engine = ChatEngine()

        # 消息缓冲相关
        self.processing_tasks: Dict = {}  # {channel_id: asyncio.Task}
        from utils.redis_manager import get_redis_client
        self.redis_client = get_redis_client()  # 初始化 Redis 客户端

        # 缓存
        self.channel_info_cache = {}
        self.user_info_cache = {}
        self.team_info_cache = {}  # 新增：缓存 Team 信息

        # 频道活动状态跟踪
        self.channel_activity = {}  # {channel_id: {"last_activity": timestamp}}
        self.last_typing_time = {}  # 新增：记录各频道最后输入状态时间

    async def get_teams(self):
        """获取 BOT 加入的 Team 列表"""
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ BOT user ID 未知，无法获取 Team 列表。 সন")
                return []

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/users/{self.user_id}/teams",
                headers=headers,
            )
            if resp.status_code == 200:
                teams = resp.json()
                logging.debug(f"[mm] 成功获取 Team 数量: {len(teams)}")
                for team in teams:
                    self.team_info_cache[team["id"]] = team
                return teams
            else:
                logging.warning(
                    f"⚠️ 无法获取 Team 列表: {resp.status_code} - {resp.text}"
                )
                return []

    async def get_channels_for_team(self, team_id: str):
        """获取指定 Team 中所有频道（含 DM）"""
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ BOT user ID 未知，无法获取频道列表。 সন")
                return []

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/users/{self.user_id}/teams/{team_id}/channels",
                headers=headers,
            )
            if resp.status_code == 200:
                channels = resp.json()
                logging.debug(f"[mm] 成功获取 Team {team_id} 频道数: {len(channels)}")
                for channel in channels:
                    self.channel_info_cache[channel["id"]] = channel  # 缓存频道信息
                return channels
            else:
                logging.warning(
                    f"⚠️ 无法获取 Team {team_id} 的频道列表: {resp.status_code} - {resp.text}"
                )
                return []

    async def get_channel_members(self, channel_id: str):
        """获取私聊频道的成员列表"""
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/channels/{channel_id}/members",
                headers=headers,
            )
            if resp.status_code == 200:
                members = resp.json()
                logging.debug(f"[mm] 频道 {channel_id} 成员数: {len(members)}")
                return members
            else:
                logging.warning(
                    f"⚠️ 无法获取频道 {channel_id} 的成员列表: {resp.status_code} - {resp.text}"
                )
                return []

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
                    "full_name": f'{data["first_name"]} {data["last_name"]}'.strip(),
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
                logging.debug(f"[mm] Bot user ID: {self.user_id}")
            else:
                logging.error("❌ Failed to fetch bot user ID")

    async def _fetch_and_store_mattermost_data(self):
        """
        获取 Mattermost Team、频道和用户信息，并存储到 Redis。
        对用户名为 'kawaro' 的用户进行特殊标记。
        """
        logging.info("[mm] 开始同步 Mattermost 基础数据到 Redis")

        # 1. 获取 BOT 自身信息 (已在 fetch_bot_user_id 中处理)
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ 无法获取 BOT user ID，跳过数据同步。 সন")
                return

        # 2. 获取 BOT 加入的 Team 列表并存储
        teams = await self.get_teams()
        if teams:
            team_data_to_store = {
                team["id"]: json.dumps(team, ensure_ascii=False) for team in teams
            }
            self.redis_client.hset("mattermost:teams", mapping=team_data_to_store)
            logging.debug(f"[mm] 已将 {len(teams)} 个 Team 信息存储到 Redis")
        else:
            logging.warning("⚠️ 未获取到任何 Team 信息。 সন")

        # 3. 获取所有频道（含 DM）并存储
        all_channels = []
        for team in teams:
            channels = await self.get_channels_for_team(team["id"])
            all_channels.extend(channels)

        if all_channels:
            channel_data_to_store = {
                channel["id"]: json.dumps(channel, ensure_ascii=False)
                for channel in all_channels
            }
            self.redis_client.hset("mattermost:channels", mapping=channel_data_to_store)
            logging.debug(f"[mm] 已将 {len(all_channels)} 个频道信息存储到 Redis")
        else:
            logging.warning("⚠️ 未获取到任何频道信息。 সন")

        # 4. 获取所有用户并存储
        # 这是一个更全面的获取用户列表的方式，不依赖于 DM 频道
        all_users = []
        page = 0
        per_page = 200  # Mattermost API 默认每页100，最大200
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self.http_base_url}/api/v4/users",
                    params={"page": page, "per_page": per_page},
                    headers=headers,
                )
                if resp.status_code == 200:
                    users_page = resp.json()
                    if not users_page:
                        break  # 没有更多用户了
                    all_users.extend(users_page)
                    page += 1
                else:
                    logging.warning(
                        f"⚠️ 无法获取所有用户信息: {resp.status_code} - {resp.text}"
                    )
                    break

        if all_users:
            user_data_to_store = {}
            for user in all_users:
                user_details = {
                    "id": user.get("id"),
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "nickname": user.get("nickname"),
                    "email": user.get("email"),
                    "is_bot": user.get("is_bot", False),
                    "is_kawaro": False,  # 默认不标记
                }
                if user_details.get("username") == "kawaro":
                    user_details["is_kawaro"] = True
                    logging.debug(f'[mm] 标记用户 \'kawaro\' ({user_details["id"]})')

                user_data_to_store[user["id"]] = json.dumps(
                    user_details, ensure_ascii=False
                )

            self.redis_client.hset("mattermost:users", mapping=user_data_to_store)
            logging.debug(f"[mm] 已将 {len(all_users)} 个用户信息存储到 Redis")
        else:
            logging.warning("⚠️ 未获取到任何用户信息。 সন")

        # 5. 遍历 DM 频道，更新频道信息以包含对方用户 ID 和 is_special_user 标记
        # 这一步是为了完善频道信息，特别是 DM 频道，使其包含对方用户ID和特殊标记
        # 假设 all_channels 已经包含了所有频道，包括 DM 频道
        dm_channels_from_api = [c for c in all_channels if c.get("type") == "D"]
        logging.debug(f"[mm] DM 频道数量: {len(dm_channels_from_api)}")

        for dm_channel in dm_channels_from_api:
            dm_channel_id = dm_channel["id"]
            members = await self.get_channel_members(dm_channel_id)

            other_user_id = None
            for member in members:
                if member["user_id"] != self.user_id:
                    other_user_id = member["user_id"]
                    break

            if other_user_id:
                # 从 Redis 中获取对方用户详情，因为已经同步了所有用户
                other_user_details_str = self.redis_client.hget(
                    "mattermost:users", other_user_id
                )
                if other_user_details_str:
                    other_user_details = json.loads(other_user_details_str)
                    dm_channel["other_user_id"] = other_user_id
                    dm_channel["is_special_user"] = other_user_details.get(
                        "is_kawaro", False
                    )

                    # 更新 Redis 中的频道信息
                    self.redis_client.hset(
                        "mattermost:channels",
                        dm_channel_id,
                        json.dumps(dm_channel, ensure_ascii=False),
                    )
                    logging.debug(
                        f"[mm] 已更新 DM 频道 {dm_channel_id} 的对方用户信息与标记"
                    )
                else:
                    logging.warning(
                        f"⚠️ 无法从 Redis 获取用户 {other_user_id} 的详细信息，DM 频道 {dm_channel_id} 未完全更新。"
                    )
            else:
                logging.warning(f"⚠️ 无法找到 DM 频道 {dm_channel_id} 的对方用户。 সন")

        logging.info("[mm] Mattermost 基础数据同步完成")

    async def connect(self):
        retries = 5
        delay = 10
        for i in range(retries):
            try:
                await self.fetch_bot_user_id()
                logging.info(f"[mm] 连接 WebSocket: {self.websocket_url}")
                self.connection = await websockets.connect(
                    self.websocket_url,
                    extra_headers={"Authorization": f"Bearer {self.token}"},
                )
                logging.info("[mm] WebSocket 连接成功")

                # 在连接成功后，获取并存储 Mattermost 基础数据
                await self._fetch_and_store_mattermost_data()

                # 向 kawaro 发送上线通知
                # await self.send_dm_to_kawaro()

                await self.listen()
                return
            except Exception as e:
                logging.error(f"❌ 连接失败 {i + 1}/{retries}: {e}")
                if i < retries - 1:
                    logging.debug(f"[mm] {delay} 秒后重试连接")
                    await asyncio.sleep(delay)
                else:
                    logging.error("❌ 所有连接尝试失败，退出。 সন")
                    raise

    async def listen(self):
        async for message in self.connection:
            data = json.loads(message)
            event = data.get("event")
            # logging.info(f"📡 收到事件类型: {event}，完整内容如下：\n{json.dumps(data, ensure_ascii=False, indent=2)}")

            if event == "posted":
                post_data = json.loads(data["data"]["post"])
                user_id = post_data["user_id"]
                channel_id = post_data["channel_id"]

                if user_id == self.user_id:
                    continue

                original_message = post_data.get("message", "")
                if original_message.startswith("🤖 সন"):
                    continue

                # --- 图片处理逻辑 ---
                file_ids = post_data.get("file_ids")
                message_to_process = original_message

                if file_ids:
                    logging.info(
                        f'[mm] 消息 {post_data["id"]} 包含 {len(file_ids)} 个文件，开始处理'
                    )
                    tasks = [self._process_image_file(file_id) for file_id in file_ids]
                    descriptions = await asyncio.gather(*tasks)

                    valid_descriptions = [desc for desc in descriptions if desc]

                    if valid_descriptions:
                        formatted_descriptions = (
                            "\n\n[图片内容摘要：\n- "
                            + "\n- ".join(valid_descriptions)
                            + "]"
                        )
                        message_to_process += formatted_descriptions
                        logging.debug(
                            f"[mm] 追加图片描述后的消息: {message_to_process}"
                        )
                # --- 图片处理逻辑结束 ---

                # 更新频道活动状态
                self.channel_activity[channel_id] = {"last_activity": time.time()}

                # 获取频道和用户信息
                channel_info = await self.get_channel_info(channel_id)
                user_info = await self.get_user_info(user_id)

                logging.debug(
                    f"[mm] 收到消息: {message_to_process} channel={channel_id} user={user_info['username'] if user_info else user_id}"
                )

                # 存储到内存缓冲区
                get_channel_memory(channel_id).add_message("user", message_to_process)

                # 添加到消息缓冲区并启动智能处理
                await self._add_to_buffer_and_process(
                    channel_id, message_to_process, channel_info, user_info
                )

            elif event == "typing":
                logging.debug(f"[mm] 接收到 Typing 信号 ts={time.time()}")
                # 处理用户打字事件
                typing_data = data["data"]
                user_id = typing_data.get("user_id")
                broadcast_data = data["broadcast"]
                channel_id = broadcast_data.get("channel_id")
                if channel_id and (user_id != self.user_id):
                    # 独立记录输入状态时间
                    self.last_typing_time[channel_id] = time.time()
                    # 保持原活动状态更新
                    self.channel_activity[channel_id] = {"last_activity": time.time()}
                    logging.debug(f"⌨️ 更新频道 {channel_id} 输入状态时间")

    async def _process_image_file(self, file_id: str) -> Optional[str]:
        """处理单个图片文件：获取信息、下载、缩放并生成描述。"""
        try:
            file_info = await self._get_file_info(file_id)
            if not file_info:
                return None

            mime_type = file_info.get("mime_type", "")
            if not mime_type.startswith("image/"):
                logging.info(
                    f"[mm] 文件 {file_id} 不是图片 (MIME: {mime_type})，跳过处理。 সন"
                )
                return None

            logging.info(f"[mm] 下载图片文件 {file_id} ({mime_type})")
            image_data = await self._download_file(file_id)
            if not image_data:
                return None

            # --- 图片缩放逻辑 ---
            try:
                img = Image.open(io.BytesIO(image_data))

                # 定义最大尺寸，例如2048x2048
                max_size = (2048, 2048)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)

                # 将缩放后的图片保存到内存中的字节流
                output_buffer = io.BytesIO()
                # 统一保存为JPEG以提高效率，对于描述任务通常足够
                img.save(
                    output_buffer, format="JPEG", quality=85
                )  # quality参数可以调整
                processed_image_data = output_buffer.getvalue()
                processed_mime_type = "image/jpeg"

                original_size_kb = len(image_data) / 1024
                processed_size_kb = len(processed_image_data) / 1024
                logging.info(
                    f"[mm] 图片 {file_id} 缩放完成。 "
                    f"原始尺寸: {original_size_kb:.2f} KB -> "
                    f"处理后尺寸: {processed_size_kb:.2f} KB"
                )

            except Exception as img_err:
                logging.error(
                    f"❌ 图片 {file_id} 缩放失败: {img_err}。将尝试使用原图。 সন"
                )
                # 如果缩放出错，则退回使用原图
                processed_image_data = image_data
                processed_mime_type = mime_type
            # --- 图片缩放逻辑结束 ---

            logging.info(f"[mm] 为图片 {file_id} 生成描述...")
            description = await get_image_description(
                processed_image_data, processed_mime_type
            )
            logging.info(f"[mm] 图片 {file_id} 描述生成结果: {description}")
            return description

        except Exception as e:
            logging.error(f"❌ 处理文件 {file_id} 时发生未知异常: {e}")
            return None

    async def send_typing(self, channel_id: str):
        """发送打字指示器到指定频道"""
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"{self.http_base_url}/api/v4/users/me/typing",
                    json={"channel_id": channel_id},
                    headers=headers,
                )
            except Exception as e:
                logging.warning(f"⚠️ 发送打字指示器异常: {e}")

    async def _add_to_buffer_and_process(
        self,
        channel_id: str,
        message: str,
        channel_info=None,
        user_info=None,
    ):
        """添加消息到缓冲区并启动智能处理"""
        # current_time 可在需要时用于时间相关逻辑

        # 检查是否是简单消息且缓冲区为空
        from core.context_merger import _needs_summary

        is_simple_message = not _needs_summary(message)
        # 检查 Redis List 是否为空
        buffer_is_empty = self.redis_client.llen(f"channel_buffer:{channel_id}") == 0

        if is_simple_message and buffer_is_empty:
            logging.info(f"⚡ 收到简单消息 '{message}'，立即回复。 সন")
            # 立即处理简单消息，不经过缓冲和延迟
            async for segment in self.chat_engine.stream_reply_single(
                channel_id, message, channel_info, user_info
            ):
                if segment.strip():
                    cleaned_segment = segment.strip()
                    await self._send_message_with_typing(channel_id, cleaned_segment)
                    # 若遇到 'SEND'，立即停止后续发送
                    if "SEND" in cleaned_segment:
                        break
            return  # 简单消息处理完毕，直接返回

        # 否则，消息进入正常缓冲流程
        # 将消息添加到 Redis List
        self.redis_client.rpush(f"channel_buffer:{channel_id}", message)

        # 将新消息缓存到 Redis，供 context_merger 使用
        # 假设 user_info 包含 username
        username = user_info.get("username", "未知用户") if user_info else "未知用户"
        self.redis_client.setex(
            f"mattermost_cache:{channel_id}",
            300,  # 5分钟有效期
            f"[{username}]：{message}",
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
        self,
        channel_id: str,
        channel_info=None,
        user_info=None,
        first_run=True,
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

                # 获取最新输入状态时间
                current_typing_time = (
                    self.last_typing_time.get(channel_id, start_time) + 3
                )

                # 计算三种超时值
                total_elapsed = current_time - start_time
                activity_elapsed = current_time - current_activity_time
                typing_elapsed = current_time - current_typing_time

                # 三重超时条件（满足任意即触发）
                if (
                    total_elapsed > 30
                    or activity_elapsed > 7
                    or (first_run and typing_elapsed > 2)
                ):  # 新增输入状态检测
                    trigger_reason = []
                    if total_elapsed > 45:
                        trigger_reason.append(f"总时长超时(45s){total_elapsed:.2f}")
                    if activity_elapsed > 15:
                        trigger_reason.append(f"活动中断(15s){activity_elapsed:.2f}")
                    if typing_elapsed > 2.3:
                        trigger_reason.append(f"输入停止(2.3s){typing_elapsed:.2f}")

                    logging.info(
                        f"⏳ 频道 {channel_id} 触发超时: {', '.join(trigger_reason)}"
                    )
                    break
                first_run = False
                await asyncio.sleep(0.1)  # 每0.1秒检查一次

            # 从 Redis 获取当前缓冲区中的所有消息
            messages = self.redis_client.lrange(f"channel_buffer:{channel_id}", 0, -1)
            logging.info(
                f"🤔 开始智能处理，频道 {channel_info['name']}，消息数：{len(messages)}"
            )

            await self.send_typing(channel_id)

            # 开始生成回复
            await self._generate_and_send_reply(
                channel_id, messages, None, channel_info, user_info
            )  # 传递从 Redis 获取的消息

        except asyncio.CancelledError:
            logging.debug(f"[mm] 处理任务被取消 channel={channel_id}")
        except Exception as e:
            logging.error(f"❌ 智能处理出错，频道 {channel_id}: {e}")
        finally:
            # 清理处理任务记录
            if (
                channel_id in self.processing_tasks
                and self.processing_tasks[channel_id].done()
            ):
                del self.processing_tasks[channel_id]

    async def create_direct_channel(self, target_user_id: str) -> Optional[str]:
        """
        创建或获取与指定用户之间的私聊频道。
        """
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ 无法获取 BOT user ID，无法创建或获取私聊频道。 সন")
                return None

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                # 尝试创建私聊频道
                create_resp = await client.post(
                    f"{self.http_base_url}/api/v4/channels/direct",
                    headers=headers,
                    json=[self.user_id, target_user_id],
                )

                if create_resp.status_code == 201:
                    channel_data = create_resp.json()
                    logging.debug(f"[mm] 创建私聊频道成功: {channel_data['id']}")
                    return channel_data["id"]
                elif (
                    create_resp.status_code == 400
                    and "api.channel.create_direct_channel.direct_channel_exists.app_error"
                    in create_resp.text
                ):
                    # 如果频道已存在，Mattermost 会返回 400 错误，并包含特定错误信息
                    # 此时需要通过获取频道列表来找到已存在的 DM 频道
                    logging.debug(
                        f"[mm] 与用户 {target_user_id} 的私聊频道已存在，尝试获取"
                    )
                    # 获取所有 DM 频道
                    all_channels = []
                    teams = await self.get_teams()  # 需要先获取 teams
                    for team in teams:
                        channels = await self.get_channels_for_team(team["id"])
                        all_channels.extend(channels)

                    for channel in all_channels:
                        if channel.get("type") == "D":
                            members = await self.get_channel_members(channel["id"])
                            member_ids = {m["user_id"] for m in members}
                            if (
                                self.user_id in member_ids
                                and target_user_id in member_ids
                            ):
                                logging.debug(
                                    f"[mm] 成功获取已存在的私聊频道: {channel['id']}"
                                )
                                return channel["id"]
                    logging.warning(
                        f"⚠️ 无法找到与用户 {target_user_id} 已存在的私聊频道。 সন"
                    )
                    return None
                else:
                    logging.warning(
                        f"⚠️ 创建私聊频道失败: {create_resp.status_code} - {create_resp.text}"
                    )
                    return None
            except Exception as e:
                logging.error(f"❌ 创建或获取私聊频道时发生异常: {e}")
                return None

    async def send_ai_generated_message(
        self,
        channel_id: str,
        processed_messages: List[str],
        context_info: Tuple[str, List[str]] = None,
        channel_info: Dict = None,
        user_info: Dict = None,
        is_active_interaction: bool = False,  # 新增参数，标记是否是主动交互
        image_path: str = None,  # 新增参数，可选的图片路径
    ):
        """
        生成并发送 AI 回复。
        这个方法封装了 AI 思考、流式生成和发送消息的逻辑。
        """
        try:
            log_prefix = "主动交互" if is_active_interaction else "被动回复"
            logging.info(
                f"[mm] 开始生成 {log_prefix} channel={channel_id} 数量={len(processed_messages)}"
            )

            sent_any = False  # 标记是否实际发出了任何内容
            first_message_sent = False  # 标记是否已发送第一条消息

            # 流式生成回复
            async for segment in self.chat_engine.stream_reply(
                channel_id,
                processed_messages,
                channel_info,
                user_info,
                context_info,
                is_active_interaction,
            ):
                if segment.strip():
                    cleaned_segment = segment.strip()
                    sent_any = True
                    # if cleaned_segment.endswith((".", "。")):
                    #     cleaned_segment = cleaned_segment[:-1]
                    
                    # 如果有图片且是第一条消息，发送带图片的消息
                    if image_path and not first_message_sent and os.path.exists(image_path):
                        await self._send_message_with_typing(channel_id, cleaned_segment, image_path)
                        first_message_sent = True
                        logging.info(f"[mm] ✅ 第一条消息已带图片发送: {os.path.basename(image_path)}")
                    else:
                        # 普通消息发送
                        await self._send_message_with_typing(channel_id, cleaned_segment)
                        if not first_message_sent:
                            first_message_sent = True
                    
                    # 若遇到 'SEND'，立即停止后续发送
                    if "SEND" in cleaned_segment:
                        break

            # 如果是被动回复且确实发出了内容，才清空 Redis 缓冲区
            if not is_active_interaction and sent_any:
                self.redis_client.delete(f"channel_buffer:{channel_id}")
                logging.debug(f"[mm] 清空频道 {channel_id} 的消息缓冲区")
            elif not is_active_interaction and not sent_any:
                logging.debug(
                    f"[mm] 未生成有效内容，保留频道 {channel_id} 的消息缓冲区"
                )
                # 追加自动回复，但不清空缓冲区
                try:
                    await self._send_message_with_typing(
                        channel_id,
                        "[自动回复]在忙，有事请留言",
                    )
                except Exception as e:
                    logging.warning(f"⚠️ 自动回复发送失败，频道 {channel_id}: {e}")

        except Exception as e:
            logging.error(f"❌ 生成 {log_prefix} 出错，频道 {channel_id}: {e}")

    async def _generate_and_send_reply(  # 旧方法，现在调用 send_ai_generated_message
        self,
        channel_id: str,
        processed_messages: List[str],
        context_info=None,
        channel_info=None,
        user_info=None,
    ):
        """生成并发送回复 (旧方法，现在调用 send_ai_generated_message)"""
        await self.send_ai_generated_message(
            channel_id=channel_id,
            processed_messages=processed_messages,
            context_info=context_info,
            channel_info=channel_info,
            user_info=user_info,
            is_active_interaction=False,  # 标记为被动回复
        )

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

        # 动态最大等待时间：平均5秒，标准差1秒，限制在4~6之间
        max_dynamic = random.normalvariate(5.0, 1.0)
        max_dynamic = max(4.0, min(6.0, max_dynamic))  # 限制最大上限浮动范围

        # 截断：确保在 0.3 到动态上限之间
        return min(max(0.3, delay), max_dynamic)

    async def _send_message_with_typing(self, channel_id: str, text: str, image_path: str = None):
        """在发送消息时持续发送打字指示器，支持可选的图片附件"""
        # 🆕 在发送前清理AI可能生成的图片标签，避免无图片对应的描述
        text = clean_ai_image_tags(text)
        
        # 快速路径：如果包含 'SEND'，仅发送其之前的内容，丢弃 'SEND' 及其后续
        if "SEND" in text:
            prefix = text.split("SEND", 1)[0].strip()
            if prefix:
                # 支持图片发送
                if image_path and os.path.exists(image_path):
                    await self.post_message_with_image(channel_id, prefix, image_path)
                else:
                    await self.send_message(channel_id, prefix)
            else:
                logging.debug("[mm] 'SEND' 出现但前缀为空，跳过发送。 সন")
            # 不发送 typing，不等待，直接结束，进入完成状态
            return

        typing_task = None
        try:
            # 启动一个后台任务，每隔一段时间发送一次打字指示器
            async def continuous_typing():
                while True:
                    await self.send_typing(channel_id)
                    await asyncio.sleep(2)

            typing_task = asyncio.create_task(continuous_typing())

            # 等待消息发送完成，使用正态分布的随机等待时间
            delay = self._generate_typing_delay(len(text))
            
            # 根据是否有图片选择发送方法
            if image_path and os.path.exists(image_path):
                await self.post_message_with_image(channel_id, text, image_path)
            else:
                await self.send_message(channel_id, text)
                
            await asyncio.sleep(delay)

        finally:
            if typing_task:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

    async def send_message(self, channel_id, text):
        clean_text = text.replace("。", "").strip()
        if "距离上一条消息过去了" in clean_text:
            clean_text = clean_text.split("\n")[-1].strip()
        if "\n" in clean_text:
            clean_text = clean_text.replace("\n", "")
        if "\\n" in clean_text:
            clean_text = clean_text.replace("\\n", "")
        payload = {"channel_id": channel_id, "message": clean_text}
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.http_base_url}/api/v4/posts", json=payload, headers=headers
            )

        if response.status_code == 201:
            logging.info(f"[mm] 已回复: {text}")
            get_channel_memory(channel_id).add_message("assistant", text)
        else:
            logging.error(
                f"❌ Failed to send message: {response.status_code} - {response.text}"
            )

    async def post_message_with_image(
        self, channel_id: str, message: str, image_path: str
    ):
        """
        发送带有图片的消息。
        1. 上传图片文件到 Mattermost。
        2. 发送带有 file_id 的消息。
        """
        # --- 1. 上传文件 ---
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            with open(image_path, "rb") as f:
                files = {
                    "files": (os.path.basename(image_path), f.read()),
                }
                data = {"channel_id": channel_id}

                file_id = None
                async with httpx.AsyncClient() as client:
                    upload_resp = await client.post(
                        f"{self.http_base_url}/api/v4/files",
                        headers=headers,
                        files=files,
                        data=data,
                        timeout=60,
                    )
                    upload_resp.raise_for_status()
                    upload_data = upload_resp.json()
                    file_id = upload_data["file_infos"][0]["id"]
                    logging.info(f"[mm] 图片上传成功，File ID: {file_id}")
        except FileNotFoundError:
            logging.error(f"❌ 图片文件未找到: {image_path}")
            await self.send_message(channel_id, message)  # 降级发送纯文本
            return
        except Exception as e:
            logging.error(f"❌ 图片上传失败: {e}")
            # 上传失败后，尝试只发送文本消息作为降级方案
            await self.send_message(channel_id, message)
            return

        # --- 2. 发送带图片的消息 ---
        if file_id:
            payload = {
                "channel_id": channel_id,
                "message": message,
                "file_ids": [file_id],
            }
            async with httpx.AsyncClient() as client:
                post_resp = await client.post(
                    f"{self.http_base_url}/api/v4/posts",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if post_resp.status_code == 201:
                    logging.info(f"[mm] 已发送带图片的消息: {message}")
                    
                    # 🆕 优先使用AI预分析描述，回退到后分析系统
                    placeholder = format_image_description("图片已发送")  # 默认占位符
                    
                    try:
                        
                        # 首先尝试从Redis获取AI预分析的描述
                        image_filename = os.path.basename(image_path)
                        image_metadata_key = f"image_metadata:{image_filename}"
                        cached_metadata = self.redis_client.get(image_metadata_key)
                        
                        if cached_metadata:
                            # 使用AI预分析的描述
                            scene_analysis = json.loads(cached_metadata)
                            description = scene_analysis.get("description", "")
                            if description:
                                placeholder = format_image_description(description)
                                logging.debug(f"[mm] ✅ 使用AI预分析描述: {description[:30]}...")
                            else:
                                logging.debug("[mm] AI预分析描述为空，使用默认占位符")
                        else:
                            # 回退到后分析系统
                            logging.debug("[mm] 未找到AI预分析数据，回退到后分析系统")
                            from services.image_service import get_image_description_by_path
                            description = await get_image_description_by_path(image_path)
                            
                            if description:
                                placeholder = format_image_description(description)
                                logging.debug(f"[mm] 使用后分析描述: {description[:30]}...")
                            else:
                                logging.debug("[mm] 未找到任何图片描述，使用默认占位符")
                            
                    except Exception as e:
                        logging.warning(f"⚠️ [mm] 获取图片描述失败（不影响消息发送）: {e}")
                    
                    get_channel_memory(channel_id).add_message(
                        "assistant", f"{message} {placeholder}"
                    )
                else:
                    logging.error(
                        f"❌ 发送带图片的消息失败: {post_resp.status_code} - {post_resp.text}"
                    )

    async def send_dm_to_kawaro(
        self,
        message: str = "德克萨斯已经上线，随时等待你的召唤。 সন",
    ):
        """
        向用户名为 'kawaro' 的用户发送私聊消息
        步骤:
        1. 获取 BOT 自身 ID
        2. 从 Redis 获取 'kawaro' 用户的 ID
        3. 创建或获取私聊频道
        4. 发送消息
        """
        # 1. 确保 BOT ID 已获取
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ 无法获取 BOT user ID，无法发送消息 সন")
                return

        # 2. 从 Redis 获取 'kawaro' 用户 ID
        kawaro_user_id = None
        users = self.redis_client.hgetall("mattermost:users")
        for user_id, user_data in users.items():
            user_info = json.loads(user_data)
            if user_info.get("username") == "kawaro":
                kawaro_user_id = user_id
                break

        if not kawaro_user_id:
            logging.warning("⚠️ 未找到 'kawaro' 用户 সন")
            return

        logging.info(f"✅ 找到 'kawaro' 用户 ID: {kawaro_user_id}")

        # 3. 创建或获取私聊频道
        channel_id = await self.create_direct_channel(kawaro_user_id)
        if not channel_id:
            logging.error("❌ 无法获取 'kawaro' 的私聊频道，无法发送消息。 সন")
            return

        # 4. 发送消息
        await self.send_message(channel_id, message)
        logging.info(f"✅ 已向 'kawaro' 发送消息: '{message}'")

    async def get_kawaro_user_and_dm_info(self) -> Optional[dict]:
        """
        获取 'kawaro' 用户信息和与其的私聊频道及频道信息
        返回格式：
        {
            "user_id": str,
            "user_info": dict,
            "channel_id": str,
            "channel_info": dict,
        }
        """
        # 确保 BOT user ID 已获取
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ 无法获取 BOT user ID সন")
                return None

        # 从 Redis 获取 'kawaro' 用户 ID 和信息
        kawaro_user_id = None
        kawaro_user_info = None
        users = self.redis_client.hgetall("mattermost:users")
        for user_id, user_data in users.items():
            user_info = json.loads(user_data)
            if user_info.get("username") == "kawaro":
                kawaro_user_id = user_id
                kawaro_user_info = user_info
                break

        if not kawaro_user_id:
            logging.warning("⚠️ 未找到 'kawaro' 用户 সন")
            return None

        # 获取与其的私聊频道
        channel_id = await self.create_direct_channel(kawaro_user_id)
        if not channel_id:
            logging.warning("⚠️ 无法获取与 'kawaro' 的私聊频道 সন")
            return None

        channel_info = await self.get_channel_info(channel_id)

        return {
            "user_id": kawaro_user_id,
            "user_info": kawaro_user_info,
            "channel_id": channel_id,
            "channel_info": channel_info,
        }

    async def _get_file_info(self, file_id: str) -> Optional[Dict]:
        """获取 Mattermost 文件的元数据。"""
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.http_base_url}/api/v4/files/{file_id}/info",
                    headers=headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    logging.warning(
                        f"⚠️ 无法获取文件 {file_id} 的信息: {resp.status_code} - {resp.text}"
                    )
                    return None
            except Exception as e:
                logging.error(f"❌ 获取文件 {file_id} 信息时发生异常: {e}")
                return None

    async def _download_file(self, file_id: str) -> Optional[bytes]:
        """从 Mattermost 下载文件内容。"""
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.http_base_url}/api/v4/files/{file_id}",
                    headers=headers,
                )
                if resp.status_code == 200:
                    return resp.content  # 返回二进制内容
                else:
                    logging.warning(
                        f"⚠️ 无法下载文件 {file_id}: {resp.status_code} - {resp.text}"
                    )
                    return None
            except Exception as e:
                logging.error(f"❌ 下载文件 {file_id} 时发生异常: {e}")
                return None


if __name__ == "__main__":
    asyncio.run(MattermostWebSocketClient().connect())
