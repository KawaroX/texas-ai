import asyncio
import websockets
import json
import os
import logging
import httpx
import datetime, time
import redis  # 导入 redis
import random
from typing import Dict, List, Optional
from app.config import settings
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
        self.team_info_cache = {}  # 新增：缓存 Team 信息

        # 频道活动状态跟踪
        self.channel_activity = {}  # {channel_id: {"last_activity": timestamp}}
        self.last_typing_time = {}  # 新增：记录各频道最后输入状态时间

    async def get_teams(self):
        """获取 BOT 加入的 Team 列表"""
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ BOT user ID 未知，无法获取 Team 列表。")
                return []

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/users/{self.user_id}/teams",
                headers=headers,
            )
            if resp.status_code == 200:
                teams = resp.json()
                logging.info(f"✅ 成功获取 {len(teams)} 个 Team。")
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
                logging.error("❌ BOT user ID 未知，无法获取频道列表。")
                return []

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.http_base_url}/api/v4/users/{self.user_id}/teams/{team_id}/channels",
                headers=headers,
            )
            if resp.status_code == 200:
                channels = resp.json()
                logging.info(f"✅ 成功获取 Team {team_id} 的 {len(channels)} 个频道。")
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
                logging.info(f"✅ 成功获取频道 {channel_id} 的 {len(members)} 个成员。")
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

    async def _fetch_and_store_mattermost_data(self):
        """
        获取 Mattermost Team、频道和用户信息，并存储到 Redis。
        对用户名为 'kawaro' 的用户进行特殊标记。
        """
        logging.info("🚀 开始获取 Mattermost 基础数据并存储到 Redis...")

        # 1. 获取 BOT 自身信息 (已在 fetch_bot_user_id 中处理)
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ 无法获取 BOT user ID，跳过数据同步。")
                return

        # 2. 获取 BOT 加入的 Team 列表并存储
        teams = await self.get_teams()
        if teams:
            team_data_to_store = {
                team["id"]: json.dumps(team, ensure_ascii=False) for team in teams
            }
            self.redis_client.hmset("mattermost:teams", team_data_to_store)
            logging.info(f"✅ 已将 {len(teams)} 个 Team 信息存储到 Redis。")
        else:
            logging.warning("⚠️ 未获取到任何 Team 信息。")

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
            self.redis_client.hmset("mattermost:channels", channel_data_to_store)
            logging.info(f"✅ 已将 {len(all_channels)} 个频道信息存储到 Redis。")
        else:
            logging.warning("⚠️ 未获取到任何频道信息。")

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
                    logging.info(f"✨ 已标记用户 'kawaro' ({user_details['id']})。")

                user_data_to_store[user["id"]] = json.dumps(
                    user_details, ensure_ascii=False
                )

            self.redis_client.hmset("mattermost:users", user_data_to_store)
            logging.info(f"✅ 已将 {len(all_users)} 个用户信息存储到 Redis。")
        else:
            logging.warning("⚠️ 未获取到任何用户信息。")

        # 5. 遍历 DM 频道，更新频道信息以包含对方用户 ID 和 is_special_user 标记
        # 这一步是为了完善频道信息，特别是 DM 频道，使其包含对方用户ID和特殊标记
        # 假设 all_channels 已经包含了所有频道，包括 DM 频道
        dm_channels_from_api = [c for c in all_channels if c.get("type") == "D"]
        logging.info(f"找到 {len(dm_channels_from_api)} 个 DM 频道。")

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
                    logging.info(
                        f"✅ 已更新 DM 频道 {dm_channel_id} 的对方用户ID和特殊标记。"
                    )
                else:
                    logging.warning(
                        f"⚠️ 无法从 Redis 获取用户 {other_user_id} 的详细信息，DM 频道 {dm_channel_id} 未完全更新。"
                    )
            else:
                logging.warning(f"⚠️ 无法找到 DM 频道 {dm_channel_id} 的对方用户。")

        logging.info("✅ Mattermost 基础数据同步完成。")

    async def connect(self):
        retries = 5
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

                # 在连接成功后，获取并存储 Mattermost 基础数据
                await self._fetch_and_store_mattermost_data()

                # 向 kawaro 发送上线通知
                # await self.send_dm_to_kawaro()

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
                    # 独立记录输入状态时间
                    self.last_typing_time[channel_id] = time.time()
                    # 保持原活动状态更新
                    self.channel_activity[channel_id] = {"last_activity": time.time()}
                    logging.debug(f"⌨️ 更新频道 {channel_id} 输入状态时间")

    async def send_typing(self, channel_id: str):
        """发送打字指示器到指定频道"""
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.http_base_url}/api/v4/users/me/typing",
                    json={"channel_id": channel_id},
                    headers=headers,
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
        from core.context_merger import _needs_summary

        is_simple_message = not _needs_summary(message)
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
                    # 移除去除句号的操作，因为用户反馈这可能导致重复发送
                    # if cleaned_segment.endswith((".", "。")):
                    #     cleaned_segment = cleaned_segment[:-1]
                    # 在等待期间持续发送打字指示器
                    await self._send_message_with_typing(channel_id, cleaned_segment)
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
        self, channel_id: str, channel_info=None, user_info=None, first_run=True
    ):
        """智能延迟处理：根据用户活动和超时进行处理"""
        start_time = time.time()

        try:
            while True:
                # 获取最新活动时间
                time.sleep(4)
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
                    if total_elapsed > 30:
                        trigger_reason.append(f"总时长超时(30s){total_elapsed:.2f}")
                    if activity_elapsed > 7:
                        trigger_reason.append(f"活动中断(7s){activity_elapsed:.2f}")
                    if typing_elapsed > 4:
                        trigger_reason.append(f"输入停止(4s){typing_elapsed:.2f}")

                    logging.info(
                        f"⏳ 频道 {channel_id} 触发超时: {', '.join(trigger_reason)}"
                        f"\n上次收到typing时间{current_typing_time:.2f}"
                        f"\n上次收到activity时间{current_activity_time:.2f}"
                    )
                    break
                first_run = False
                await asyncio.sleep(1)  # 每1秒检查一次

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

    async def create_direct_channel(self, target_user_id: str) -> Optional[str]:
        """
        创建或获取与指定用户之间的私聊频道。
        """
        if self.user_id is None:
            await self.fetch_bot_user_id()
            if self.user_id is None:
                logging.error("❌ 无法获取 BOT user ID，无法创建或获取私聊频道。")
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
                    logging.info(f"✅ 创建私聊频道成功: {channel_data['id']}")
                    return channel_data["id"]
                elif (
                    create_resp.status_code == 400
                    and "api.channel.create_direct_channel.direct_channel_exists.app_error"
                    in create_resp.text
                ):
                    # 如果频道已存在，Mattermost 会返回 400 错误，并包含特定错误信息
                    # 此时需要通过获取频道列表来找到已存在的 DM 频道
                    logging.info(
                        f"ℹ️ 与用户 {target_user_id} 的私聊频道已存在，尝试获取。"
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
                                logging.info(
                                    f"✅ 成功获取已存在的私聊频道: {channel['id']}"
                                )
                                return channel["id"]
                    logging.warning(
                        f"⚠️ 无法找到与用户 {target_user_id} 已存在的私聊频道。"
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
        context_info=None,
        channel_info=None,
        user_info=None,
        is_active_interaction: bool = False,  # 新增参数，标记是否是主动交互
    ):
        """
        生成并发送 AI 回复。
        这个方法封装了 AI 思考、流式生成和发送消息的逻辑。
        """
        try:
            log_prefix = "主动交互" if is_active_interaction else "被动回复"
            logging.info(
                f"🧠 开始生成 {log_prefix}，频道 {channel_id}，处理消息数：{len(processed_messages)}"
            )

            # 流式生成回复
            async for segment in self.chat_engine.stream_reply(
                channel_id, processed_messages, channel_info, user_info, context_info
            ):
                if segment.strip():
                    cleaned_segment = segment.strip()
                    # if cleaned_segment.endswith((".", "。")):
                    #     cleaned_segment = cleaned_segment[:-1]
                    await self._send_message_with_typing(channel_id, cleaned_segment)

            # 如果是被动回复，清空 Redis 缓冲区
            if not is_active_interaction:
                self.redis_client.delete(f"channel_buffer:{channel_id}")
                logging.info(f"🧹 清空频道 {channel_id} 的消息缓冲区")

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
                    await asyncio.sleep(3)

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
        clean_text = text.replace("。", " ")
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
            logging.info(f"✅ Replied with: {text}")
            get_channel_memory(channel_id).add_message("assistant", text)
        else:
            logging.error(
                f"❌ Failed to send message: {response.status_code} - {response.text}"
            )

    async def send_dm_to_kawaro(
        self, message: str = "德克萨斯已经上线，随时等待你的召唤。"
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
                logging.error("❌ 无法获取 BOT user ID，无法发送消息")
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
            logging.warning("⚠️ 未找到 'kawaro' 用户")
            return

        logging.info(f"✅ 找到 'kawaro' 用户 ID: {kawaro_user_id}")

        # 3. 创建或获取私聊频道
        channel_id = await self.create_direct_channel(kawaro_user_id)
        if not channel_id:
            logging.error("❌ 无法获取 'kawaro' 的私聊频道，无法发送消息。")
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
                logging.error("❌ 无法获取 BOT user ID")
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
            logging.warning("⚠️ 未找到 'kawaro' 用户")
            return None

        # 获取与其的私聊频道
        channel_id = await self.create_direct_channel(kawaro_user_id)
        if not channel_id:
            logging.warning("⚠️ 无法获取与 'kawaro' 的私聊频道")
            return None

        channel_info = await self.get_channel_info(channel_id)

        return {
            "user_id": kawaro_user_id,
            "user_info": kawaro_user_info,
            "channel_id": channel_id,
            "channel_info": channel_info,
        }


if __name__ == "__main__":
    asyncio.run(MattermostWebSocketClient().connect())
