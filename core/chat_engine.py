from utils.logging_config import get_logger

logger = get_logger(__name__)
from typing import List, Dict, Optional, Tuple
import asyncio

from core.context_merger import merge_context
from services.ai_service import stream_ai_chat, analyze_intimacy_event
from core.persona import get_texas_system_prompt
from core.state_manager import state_manager
from utils.postgres_service import (
    init_intimacy_table,
    insert_intimacy_record,
    get_latest_intimacy_record,
    update_intimacy_record
)
import re


class ChatEngine:
    def __init__(self):
        self.system_prompt = get_texas_system_prompt()

    async def _process_release_event(self, context_messages: list):
        """
        处理释放事件：分析并存储记录 (CG Gallery)
        v3.7: 支持防抖期内的CG替换逻辑
        """
        try:
            logger.info("[chat_engine] 开始处理 Release 事件记录...")

            # 1. 确保表存在
            init_intimacy_table()

            # 2. 调用 AI 分析
            analysis = await analyze_intimacy_event(context_messages)
            if not analysis:
                logger.warning("[chat_engine] 亲密事件分析失败")
                return

            # 3. v3.7 防抖逻辑：检查是否有最近的记录（10分钟内）
            COOLDOWN_SECONDS = 600
            latest_record = get_latest_intimacy_record(within_seconds=COOLDOWN_SECONDS)

            if latest_record:
                # 在防抖期内，替换最近的CG记录
                record_id = latest_record['id']
                success = update_intimacy_record(record_id, analysis)
                if success:
                    logger.info(f"[chat_engine] ✅ CG记录已替换 (防抖): ID={record_id}, Summary={analysis.get('summary')}")
                else:
                    logger.warning(f"[chat_engine] ⚠️ CG记录替换失败: ID={record_id}")
            else:
                # 不在防抖期内，插入新记录
                record_id = insert_intimacy_record(analysis)
                logger.info(f"[chat_engine] ✅ CG记录已新建: ID={record_id}, Summary={analysis.get('summary')}")

        except Exception as e:
            logger.error(f"[chat_engine] 处理 Release 事件失败: {e}", exc_info=True)

    async def stream_reply(
        self,
        channel_id: str,
        messages: List[str],
        channel_info: Optional[Dict] = None,
        user_info: Optional[Dict] = None,
        context_info: Optional[Tuple[str, List[str]]] = None,
        is_active_interaction: bool = False,
    ):
        """流式生成回复，使用新的消息结构（system + 单条 user 消息）"""
        logger.info(
            f"[chat_engine] 开始流式生成回复 channel={channel_id}, 消息数={len(messages)}"
        )

        # 1. 系统提示词 (根据频道和用户信息动态生成)
        dynamic_system_prompt = self.system_prompt

        dynamic_system_prompt += "\n\n# 背景信息\n\n <BgInfo>"

        if channel_info["type"] == "D":
            channel_info["display_name"] = "私聊"
        if channel_info:
            dynamic_system_prompt += (
                f"\n\n当前频道信息：\n"
                f"- 频道显示名称: {channel_info.get('display_name', '未知')}\n"
                f"- 频道类型: {channel_info.get('type', '未知')}"
                "\n\n可以根据频道信息进行定制化处理。"
            )
        if user_info:
            dynamic_system_prompt += (
                f"\n\n当前用户信息，你可以选择合适的名字称呼对方：\n"
                f"- 用户名: {user_info.get('username', '未知')}\n"
                f"- 全名: {user_info.get('full_name', '未知')}\n"
                f"- 昵称: {user_info.get('nickname', '未知')}"
            )
        if user_info.get("username") == "kawaro":
            dynamic_system_prompt += "\n\n现在和你交流的user是Kawaro，这是你最熟悉的人，你应该表现得更温柔，你很喜欢他。虽然是一种克制的喜欢，但是你的心里知道你对他的喜欢超过对世上任何一个人。如果你们之间有争论，最终你会顺从他。"
        else:
            dynamic_system_prompt += (
                "\n\n这是一个普通用户，并不是Kawaro，你应该表现得更冷漠。"
                "尽一切可能少回复，用最少的字和最少的句子。但是也要有礼貌，礼貌地保持很大的社交距离。"
            )

        # 2. 获取整合的系统提示词和完整消息列表
        if context_info:
            # 如果提供了 context_info，说明已经预先调用了 merge_context
            logger.debug("使用预提供的 context_info")

            if isinstance(context_info, tuple) and len(context_info) == 2:
                # 如果 context_info 是 merge_context 返回的元组格式
                bg_info, context_messages = context_info
            elif isinstance(context_info, dict):
                # 如果 context_info 是字典格式
                bg_info = context_info.get("system_prompt", "")
                context_messages = context_info.get("messages", [])
            else:
                # 兼容旧格式：context_info 是单一字符串
                logger.warning(
                    "[chat_engine] context_info 使用旧格式，建议更新调用方式"
                )
                bg_info = ""  # 无法从旧格式中提取背景信息
                # 将旧格式转换为消息格式
                context_messages = [{"role": "user", "content": context_info}]

            logger.debug(
                f"[chat_engine] context_info 背景长度={len(bg_info)}, 消息数={len(context_messages)}"
            )

        else:
            # 否则，使用新的 merge_context 获取整合的系统提示词和消息
            latest_query = " ".join(messages)
            bg_info, context_messages = await merge_context(
                channel_id, latest_query, is_active=is_active_interaction
            )

            logger.debug(
                f"[chat_engine] merge_context 背景长度={len(bg_info)}, 消息数={len(context_messages)}"
            )

        # 3. 替换 dynamic_system_prompt 中的 <BgInfo> 占位符
        if "<BgInfo>" in dynamic_system_prompt:
            final_system_prompt = dynamic_system_prompt.replace("<BgInfo>", bg_info)
            logger.debug("已替换 <BgInfo> 占位符")
        else:
            # 如果没有占位符，直接追加背景信息
            final_system_prompt = f"{dynamic_system_prompt}\n\n{bg_info}"
            logger.debug("无 <BgInfo> 占位符，直接追加背景信息")

        # 4. 获取实时状态注入（将从 system prompt 中移除，改为插入到 messages）
        emotion_status = state_manager.get_system_prompt_injection()

        # 5. 构建新的消息结构：system（不含状态注入）+ 对话历史 + 状态注入（作为最后一条消息）
        prompt_messages = [
            {"role": "system", "content": final_system_prompt}
        ] + context_messages + [
            {
                "role": "user",
                "content": f"[实时状态更新 - 请根据以下状态调整你的行为]\n{emotion_status}"
            }
        ]

        logger.debug(
            f"[chat_engine] 构建完成 system_len={len(final_system_prompt)}, 消息数={len(context_messages)}"
        )

        # 🔍 NTR 调试输出：检查 system prompt 中是否包含关键内容
        ntr_keywords = ["完全物化模式", "道德崩坏模式", "灵魂伴侣", "狂热信徒", "System Note: 覆盖"]
        ntr_found = [kw for kw in ntr_keywords if kw in final_system_prompt]
        if ntr_found:
            logger.warning(f"🔍 [NTR_DEBUG] System Prompt 包含关键词: {ntr_found}")
            # 输出包含关键词的前后文本
            for kw in ntr_found:
                idx = final_system_prompt.find(kw)
                if idx != -1:
                    context_start = max(0, idx - 50)
                    context_end = min(len(final_system_prompt), idx + len(kw) + 200)
                    logger.warning(f"🔍 [NTR_DEBUG] '{kw}' 上下文:\n{final_system_prompt[context_start:context_end]}")
        else:
            logger.warning(f"⚠️ [NTR_DEBUG] System Prompt 中未找到 NTR 相关关键词！")

        # 输出完整的 system prompt（仅在调试模式下）
        logger.info(f"🔍 [NTR_DEBUG] 完整 System Prompt:\n{final_system_prompt}")

        # 4. 流式调用 AI 模型，并收集完整回复用于事件检测和图片请求检测
        full_response = ""
        segments_list = []  # 收集所有segments
        event_marker = "[EVENT_DETECTED]"
        image_marker = "[IMAGE_REQUESTED]"

        # 先收集所有segments
        async for segment in stream_ai_chat(prompt_messages, "grok-4.1-thinking"):
            full_response += segment
            segments_list.append(segment)
            # 调试：每个segment是否包含标记
            if event_marker in segment:
                logger.warning(f"🔍 [DEBUG] segment 包含事件标记! segment='{segment}'")
            if image_marker in segment:
                logger.warning(f"🔍 [DEBUG] segment 包含图片标记! segment='{segment}'")

        # 调试：完整回复
        logger.info(f"🔍 [DEBUG] full_response 长度={len(full_response)}")
        logger.info(f"🔍 [DEBUG] full_response 最后200字符: {full_response[-200:]}")
        logger.info(f"🔍 [DEBUG] 是否包含事件标记? {event_marker in full_response}")
        logger.info(f"🔍 [DEBUG] 是否包含图片标记? {image_marker in full_response}")

        # 检查是否包含标记，并从segments中移除
        has_event_marker = event_marker in full_response
        has_image_marker = image_marker in full_response

        if has_event_marker:
            # 找到包含标记的segment并移除标记
            for i, seg in enumerate(segments_list):
                if event_marker in seg:
                    segments_list[i] = seg.replace(event_marker, "")
                    logger.info(f"[chat_engine] 从segment {i} 中移除事件标记")

        # 提取图片描述和附言（如果有的话）
        image_description = None
        image_caption = None
        if has_image_marker:
            # 查找 [IMAGE_DESCRIPTION:xxx] 格式
            description_pattern = r"\[IMAGE_DESCRIPTION:([^\]]+)\]"
            description_match = re.search(description_pattern, full_response)
            if description_match:
                image_description = description_match.group(1).strip()
                logger.info(
                    f"[chat_engine] 提取到AI生成的图片描述: {image_description[:100]}..."
                )
            else:
                logger.warning(f"[chat_engine] 未找到图片描述标记，将使用默认场景分析")

            # 查找 [IMAGE_CAPTION:xxx] 格式
            caption_pattern = r"\[IMAGE_CAPTION:([^\]]+)\]"
            caption_match = re.search(caption_pattern, full_response)
            if caption_match:
                image_caption = caption_match.group(1).strip()
                logger.info(f"[chat_engine] 提取到AI生成的图片附言: {image_caption}")

            # 移除图片标记、描述标记和附言标记
            for i, seg in enumerate(segments_list):
                if image_marker in seg:
                    segments_list[i] = seg.replace(image_marker, "")
                    logger.info(f"[chat_engine] 从segment {i} 中移除图片标记")
                if description_match and description_match.group(0) in seg:
                    segments_list[i] = seg.replace(description_match.group(0), "")
                    logger.info(f"[chat_engine] 从segment {i} 中移除图片描述标记")
                if caption_match and caption_match.group(0) in seg:
                    segments_list[i] = seg.replace(caption_match.group(0), "")
                    logger.info(f"[chat_engine] 从segment {i} 中移除图片附言标记")

        # [NEW] Mood & Lust Tag Parsing
        p_delta = 0
        a_delta = 0
        d_delta = 0
        lust_delta = 0
        release_triggered = False

        # 1. Mood Impact (支持可选的 D 参数)
        mood_match = re.search(r"\[MOOD_IMPACT:\s*P([+-]?\d+)\s*A([+-]?\d+)(?:\s*D([+-]?\d+))?\]", full_response)
        if mood_match:
            try:
                p_delta = float(mood_match.group(1))
                a_delta = float(mood_match.group(2))
                d_delta = float(mood_match.group(3)) if mood_match.group(3) else 0

                # 日常对话限制 D 变化幅度为 ±0.2
                if abs(d_delta) > 0.2:
                    original_d = d_delta
                    d_delta = 0.2 if d_delta > 0 else -0.2
                    logger.info(f"[chat_engine] D变化被限制: {original_d:+.1f} -> {d_delta:+.1f}")

                if d_delta != 0:
                    logger.info(f"[chat_engine] 检测到情绪变化: P{p_delta:+.1f} A{a_delta:+.1f} D{d_delta:+.1f}")
                else:
                    logger.info(f"[chat_engine] 检测到情绪变化: P{p_delta:+.1f} A{a_delta:+.1f}")
            except ValueError:
                logger.warning(f"[chat_engine] 情绪标签解析失败: {mood_match.group(0)}")
        
        # 2. Lust Increase
        lust_match = re.search(r"\[LUST_INCREASE:\s*([+-]?\d+)\]", full_response)
        if lust_match:
            try:
                lust_delta = float(lust_match.group(1))
                logger.info(f"[chat_engine] 检测到欲望变化: {lust_delta:+.1f}")
            except ValueError: pass
            
        # 3. Release
        if "[RELEASE_TRIGGERED]" in full_response:
            release_triggered = True
            logger.info("[chat_engine] 检测到释放触发")
            # 触发 CG Gallery 记录任务
            asyncio.create_task(self._process_release_event(context_messages))

        # 应用变更
        if p_delta != 0 or a_delta != 0 or d_delta != 0 or lust_delta != 0 or release_triggered:
            state_manager.apply_raw_impact(p_delta, a_delta, d_delta, lust_delta, release_triggered)

        # 清理 Tags
        tags_to_remove = []
        if mood_match: tags_to_remove.append(mood_match.group(0))
        if lust_match: tags_to_remove.append(lust_match.group(0))
        if release_triggered: tags_to_remove.append("[RELEASE_TRIGGERED]")
        
        if tags_to_remove:
            for i, seg in enumerate(segments_list):
                for tag in tags_to_remove:
                    if tag in seg:
                        segments_list[i] = segments_list[i].replace(tag, "")

        # 在输出前先触发事件检测和图片生成（因为generator可能被提前终止）
        if has_event_marker:
            logger.info(
                f"[chat_engine] ✅ 检测到事件标记，开始异步提取 channel={channel_id}"
            )
            asyncio.create_task(
                self._extract_and_store_event(
                    full_response, channel_id, messages, context_messages, user_info
                )
            )

        if has_image_marker:
            logger.info(
                f"[chat_engine] ✅ 检测到图片请求标记，开始异步生成 channel={channel_id}"
            )
            asyncio.create_task(
                self._generate_and_send_image(
                    channel_id,
                    user_info.get("username", "unknown") if user_info else "unknown",
                    image_description=image_description,
                    custom_caption=image_caption,
                )
            )

        # 输出所有segments（保持原有分段逻辑）
        for seg in segments_list:
            yield seg

        logger.info(
            f"[chat_engine] 流式生成回复完成 channel={channel_id}, 回复长度={len(full_response)}, segments数量={len(segments_list)}"
        )

    async def _process_event_detection(
        self,
        ai_response: str,
        channel_id: str,
        user_messages: List[str],
        context_messages: List[Dict],
        user_info: Optional[Dict] = None,
    ):
        """
        检测AI回复中的事件标记，并异步提取和存储事件

        Args:
            ai_response: AI的完整回复
            channel_id: 频道ID
            user_messages: 用户消息列表
            context_messages: 对话上下文
            user_info: 用户信息
        """
        logger.debug(
            f"[chat_engine] 检查事件标记，回复长度={len(ai_response)}, 包含标记={'[EVENT_DETECTED]' in ai_response}"
        )

        # 检查事件标记
        if "[EVENT_DETECTED]" not in ai_response:
            logger.debug(f"[chat_engine] 未检测到事件标记")
            return

        logger.info(
            f"[chat_engine] ✅ 检测到事件标记，开始异步提取 channel={channel_id}"
        )

        # 启动异步任务处理事件提取（不阻塞主流程）
        asyncio.create_task(
            self._extract_and_store_event(
                ai_response, channel_id, user_messages, context_messages, user_info
            )
        )

    async def _extract_and_store_event(
        self,
        ai_response: str,
        channel_id: str,
        user_messages: List[str],
        context_messages: List[Dict],
        user_info: Optional[Dict] = None,
    ):
        """
        异步提取事件详情并存储

        Args:
            ai_response: AI的完整回复（包含标记）
            channel_id: 频道ID
            user_messages: 用户消息列表
            context_messages: 对话上下文
            user_info: 用户信息
        """
        try:
            from services.event_extractor import extract_event_details
            from services.future_event_manager import future_event_manager

            # 移除标记，获取干净的AI回复
            clean_response = ai_response.replace("[EVENT_DETECTED]", "").strip()

            # 获取用户消息
            user_message = " ".join(user_messages)

            # 提取事件详情
            event_data = await extract_event_details(
                user_message=user_message,
                ai_response=clean_response,
                recent_context=context_messages[-10:],  # 最近10条消息作为上下文
            )

            if not event_data:
                logger.info("[chat_engine] 事件提取失败或置信度过低，跳过存储")
                return

            # 获取用户ID
            user_id = user_info.get("username", "unknown") if user_info else "unknown"

            # 创建事件
            event_id = await future_event_manager.create_event(
                event_data=event_data,
                channel_id=channel_id,
                user_id=user_id,
                context_messages=context_messages[-5:],  # 保存最近5条消息作为上下文
            )

            if event_id:
                logger.info(
                    f"[chat_engine] 事件创建成功: {event_id} - {event_data.get('event_summary')}"
                )
            else:
                logger.warning("[chat_engine] 事件创建失败")

        except Exception as e:
            logger.error(f"[chat_engine] 事件提取和存储异常: {e}", exc_info=True)

    async def _generate_and_send_image(
        self,
        channel_id: str,
        user_id: str,
        custom_caption: Optional[str] = None,
        image_description: Optional[str] = None,
    ):
        """
        异步生成并发送图片

        Args:
            channel_id: 频道ID
            user_id: 用户ID
            custom_caption: AI生成的自定义图片附言
            image_description: AI直接生成的图片描述
        """
        try:
            from services.instant_image_generator import instant_image_generator

            # 生成图片（异步，不阻塞）
            result = await instant_image_generator.generate_instant_image(
                channel_id=channel_id,
                user_id=user_id,
                image_type=None,  # 自动判断
                context_window_minutes=3,
                max_messages=25,
                image_description=image_description,
            )

            if not result["success"]:
                logger.warning(f"[chat_engine] 图片生成失败: {result.get('error')}")
                # 生成失败不影响对话流程，静默失败
                return

            image_path = result["image_path"]
            is_selfie = result.get("is_selfie", False)
            logger.info(
                f"[chat_engine] 图片生成成功: {image_path}, 类型: {'自拍' if is_selfie else '场景'}"
            )

            # 发送图片到频道
            from app.mattermost_client import MattermostWebSocketClient

            ws_client = MattermostWebSocketClient()

            # 确保bot user ID已获取
            if ws_client.user_id is None:
                await ws_client.fetch_bot_user_id()

            # 使用自定义附言或生成随机的发送文本
            if custom_caption:
                caption = custom_caption
                logger.info(f"[chat_engine] 使用AI生成的图片附言: {caption}")
            else:
                import random

                if is_selfie:
                    messages = [
                        "拍好了。",
                        "来，看这里。",
                        "这张怎么样？",
                        "刚拍的。",
                        "（举起手机）",
                    ]
                else:
                    messages = [
                        "拍到了。",
                        "这就是现在的场景。",
                        "看，就是这样。",
                        "给你看看。",
                        "（转身对准窗外）",
                    ]
                caption = random.choice(messages)
                logger.info(f"[chat_engine] 使用预设随机附言: {caption}")

            # 发送图片
            await ws_client.post_message_with_image(
                channel_id=channel_id, message=caption, image_path=image_path
            )

            logger.info(f"[chat_engine] 图片已发送到频道: {channel_id}")

        except Exception as e:
            logger.error(f"[chat_engine] 图片生成和发送异常: {e}", exc_info=True)

    # 为了向后兼容，保留原有的单消息接口
    async def stream_reply_single(
        self,
        channel_id: str,
        latest_query: str,
        channel_info: Optional[Dict] = None,
        user_info: Optional[Dict] = None,
    ):
        """向后兼容的单消息接口"""
        async for segment in self.stream_reply(
            channel_id, [latest_query], channel_info, user_info
        ):
            yield segment
