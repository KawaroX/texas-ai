"""
AI Providers 工具函数模块

包含各AI服务提供商共用的工具函数，如通知、重试、日志等。
"""

import os
import httpx
from utils.logging_config import get_logger

logger = get_logger(__name__)
import asyncio
import urllib.parse
from typing import AsyncGenerator, Optional


# Bark通知配置
BARK_BASE_URL = "https://api.day.app/h9F6jTtz4QYaZjkvFo7SxQ/"


async def send_bark_notification(
    title: str, content: str, group: str = "AI_Service_Alerts"
):
    """发送Bark通知"""
    try:
        # 限制长度以防止URL过长
        # title 20字符，content 100字符，group 20字符
        title = title[:20] if title else "通知"
        content = content[:100] if content else ""
        group = group[:20] if group else "AI_Service_Alerts"

        encoded_title = urllib.parse.quote(title)
        encoded_content = urllib.parse.quote(content)
        encoded_group = urllib.parse.quote(group)
        full_url = (
            f"{BARK_BASE_URL}{encoded_title}/{encoded_content}?group={encoded_group}"
        )
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(full_url)
            response.raise_for_status()
            logger.info(f"Bark notification sent: {title}")
    except Exception as bark_e:
        logger.error(f"Failed to send Bark notification: {bark_e}")


def _truncate_for_log(s: str, limit: int = 20) -> str:
    """截断字符串用于日志显示"""
    try:
        return s[:limit] + ("…" if len(s) > limit else "")
    except Exception:
        return str(s)[:limit]


def _estimate_tokens_simple(s: str) -> int:
    """
    Very rough token estimate: ~4 characters per token.
    Avoids heavy deps like tiktoken while giving an order-of-magnitude view.
    """
    try:
        return max(1, (len(s) + 3) // 4)
    except Exception:
        return 1


def summarize_payload_for_log(payload: dict, preview_len: int = 20) -> dict:
    """
    递归地总结payload内容用于日志:
    - 对每个字符串字段，包含长度、近似token数和前N个字符
    - 对列表/字典，保持结构但用摘要替换字符串叶节点
    - 计算所有字符串字段的近似总token数
    """
    total_tokens = 0

    def walk(node):
        nonlocal total_tokens
        if isinstance(node, str):
            t = _estimate_tokens_simple(node)
            total_tokens += t
            return {
                "len": len(node),
                "tokens": t,
                "preview": _truncate_for_log(node, preview_len),
            }
        elif isinstance(node, list):
            return [walk(x) for x in node]
        elif isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        else:
            return node

    try:
        summarized = walk(payload)
    except Exception as e:
        summarized = {"error": f"summarize_failed: {type(e).__name__}: {e}"}

    summarized["_approx_total_tokens"] = total_tokens
    return summarized


async def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0):
    """
    重试机制，支持指数退避
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 遇到429错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error("达到最大重试次数，放弃重试")
                    raise
            else:
                # 其他HTTP错误直接抛出，不重试
                raise
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(f"{e}")
                logger.warning(
                    f"⚠️ 遇到未知错误{type(e)}，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error("达到最大重试次数，放弃重试")
                raise