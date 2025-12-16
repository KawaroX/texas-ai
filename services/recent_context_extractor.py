"""
最近对话上下文提取器
用于即时图片生成时获取相关对话历史
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from utils.logging_config import get_logger
import json

logger = get_logger(__name__)


class RecentContextExtractor:
    """最近对话上下文提取器"""

    def __init__(self):
        from core.memory_buffer import get_channel_memory
        from utils.redis_manager import get_redis_client

        self.get_channel_memory = get_channel_memory
        self.redis_client = get_redis_client()

    def extract_recent_context(
        self,
        channel_id: str,
        window_minutes: int = 3,
        max_messages: int = 25,
        include_assistant: bool = True
    ) -> List[Dict]:
        """
        提取最近的对话上下文

        Args:
            channel_id: 频道ID
            window_minutes: 时间窗口（分钟）
            max_messages: 最大消息数量
            include_assistant: 是否包含AI的回复

        Returns:
            消息列表，格式: [{"role": "user", "content": "...", "timestamp": "..."}]
        """
        logger.info(f"[context_extractor] 提取最近对话: channel={channel_id}, window={window_minutes}min, max={max_messages}")

        # 从Redis buffer获取
        messages = self._extract_from_redis(channel_id, window_minutes, max_messages)

        # 过滤AI回复（可选）
        if not include_assistant:
            messages = [msg for msg in messages if msg['role'] == 'user']

        logger.info(f"[context_extractor] 提取到 {len(messages)} 条消息")
        return messages

    def _extract_from_redis(
        self,
        channel_id: str,
        window_minutes: int,
        max_messages: int
    ) -> List[Dict]:
        """从Redis buffer提取"""
        try:
            # 获取频道的所有缓存消息
            channel_memory = self.get_channel_memory(channel_id)
            buffer_messages = channel_memory.get_recent_messages()

            if not buffer_messages:
                return []

            # 计算时间窗口
            cutoff_time = datetime.now() - timedelta(minutes=window_minutes)

            # 过滤时间窗口内的消息
            recent_messages = []
            for msg in buffer_messages:
                # 解析时间戳
                msg_time = self._parse_timestamp(msg.get('timestamp'))
                if msg_time and msg_time > cutoff_time:
                    recent_messages.append(msg)

            # 限制数量（取最近的N条）
            recent_messages = recent_messages[-max_messages:]

            logger.debug(f"[context_extractor] Redis提取: {len(recent_messages)}条")
            return recent_messages

        except Exception as e:
            logger.error(f"[context_extractor] Redis提取失败: {e}")
            return []

    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """解析时间戳字符串"""
        if not timestamp_str:
            return None

        try:
            # 尝试ISO格式
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            try:
                # 尝试其他格式
                return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except:
                return None

    def format_context_for_scene(self, messages: List[Dict]) -> str:
        """
        将对话格式化为场景描述

        Args:
            messages: 消息列表

        Returns:
            格式化的场景描述文本
        """
        if not messages:
            return "当前对话内容为空。"

        context_lines = []

        for msg in messages:
            # 角色名称
            role_name = "kawaro" if msg['role'] == 'user' else "德克萨斯"

            # 消息内容
            content = msg.get('content', '').strip()

            if content:
                context_lines.append(f"{role_name}: {content}")

        # 添加时间信息
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        header = f"当前时间: {current_time}\n最近的对话内容:\n\n"

        return header + "\n".join(context_lines)


# 全局实例
recent_context_extractor = RecentContextExtractor()
