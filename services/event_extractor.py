"""
未来事件提取服务
使用AI从对话中提取未来事件的详细信息
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def extract_event_details(
    user_message: str,
    ai_response: str,
    recent_context: List[Dict] = None
) -> Optional[Dict]:
    """
    从对话中提取事件详细信息（结构化输出）

    Args:
        user_message: 用户消息
        ai_response: AI的回复
        recent_context: 最近的对话上下文

    Returns:
        {
            "event_text": str,
            "event_summary": str,
            "event_date": str,  # YYYY-MM-DD
            "event_time": str,  # HH:MM
            "need_reminder": bool,
            "reminder_advance_minutes": int,
            "confidence": float,
            "metadata": dict
        }
        或 None（如果提取失败）
    """
    from services.ai_service import call_structured_generation

    # 获取当前时间信息
    now = datetime.now()
    current_date_str = now.strftime("%Y-%m-%d %H:%M")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]

    # 格式化最近对话
    context_text = ""
    if recent_context:
        context_lines = []
        for msg in recent_context[-5:]:  # 最近5条
            role_name = "kawaro" if msg.get('role') == 'user' else "德克萨斯"
            context_lines.append(f"{role_name}: {msg.get('content', '')}")
        context_text = "\n".join(context_lines)

    # 构建提示词
    prompt = f"""你是德克萨斯的事件管理助手。请从对话中提取未来事件的详细信息。

## 当前时间
{current_date_str} 星期{weekday}

## 最近对话
{context_text}

## 最新交互
kawaro: {user_message}
德克萨斯: {ai_response}

## 任务
从对话中提取kawaro提到的未来要做的事情，解析出详细信息。

## 时间解析规则
1. **绝对时间**: "明天下午三点" → 计算具体日期和时间
2. **相对时间**: "两周后" → 计算具体日期
3. **模糊时间**: "下周" → 取下周一
4. **无具体时间**: 如果只说"要做某事"没有时间 → event_date 和 event_time 都为 null

## 时间计算示例（当前{current_date_str}）
- "明天" → {(now + timedelta(days=1)).strftime("%Y-%m-%d")}
- "后天" → {(now + timedelta(days=2)).strftime("%Y-%m-%d")}
- "下周" → {(now + timedelta(days=(7 - now.weekday()))).strftime("%Y-%m-%d")}
- "下周五" → 找到下个周五的日期
- "一周后" → {(now + timedelta(days=7)).strftime("%Y-%m-%d")}
- "两个月后" → {(now + timedelta(days=60)).strftime("%Y-%m-%d")}

## 提醒判断
以下情况需要设置 need_reminder=true:
- 明确提到"提醒我"、"别忘了"
- 重要事项：考试、约会、面试、会议
- 有明确时间的任务

## 置信度评估
- 0.9-1.0: 时间和事件都非常明确
- 0.7-0.9: 时间或事件有一个较明确
- 0.5-0.7: 时间和事件都比较模糊
- <0.5: 不确定是否是事件

请严格按照以下JSON格式输出：
{{
  "event_text": "用户的原话",
  "event_summary": "简短摘要(5-10字)",
  "event_date": "YYYY-MM-DD或null",
  "event_time": "HH:MM或null",
  "need_reminder": true/false,
  "reminder_advance_minutes": 30,
  "confidence": 0.85,
  "metadata": {{
    "location": "地点或null",
    "participants": ["参与人"],
    "importance": "high|medium|low",
    "category": "work|personal|social|health|other"
  }}
}}

注意：
- 如果无法确定具体时间，event_date和event_time设为null
- event_summary尽量简洁，5-10个字
- 置信度要诚实评估，不确定就给低分
- 只提取一个最主要的事件
"""

    try:
        # 调用AI进行结构化提取
        logger.debug("[event_extractor] 开始提取事件详情")
        result = await call_structured_generation([{"role": "user", "content": prompt}])

        if not result or "error" in result:
            logger.warning(f"[event_extractor] 提取失败: {result.get('error') if result else 'None'}")
            return None

        # 验证必要字段
        if not result.get('event_text') or not result.get('event_summary'):
            logger.warning("[event_extractor] 缺少必要字段")
            return None

        # 验证置信度
        confidence = result.get('confidence', 0.0)
        if confidence < 0.7:
            logger.info(f"[event_extractor] 置信度过低: {confidence}")
            return None

        logger.info(f"[event_extractor] 提取成功: {result['event_summary']} (confidence={confidence})")
        return result

    except Exception as e:
        logger.error(f"[event_extractor] 提取异常: {e}")
        return None


def calculate_reminder_datetime(event_date_str: str, event_time_str: str, advance_minutes: int) -> Optional[str]:
    """
    计算提醒时间

    Args:
        event_date_str: 事件日期 (YYYY-MM-DD)
        event_time_str: 事件时间 (HH:MM)
        advance_minutes: 提前多少分钟

    Returns:
        ISO格式的提醒时间字符串，或None
    """
    if not event_date_str:
        return None

    try:
        # 解析日期和时间
        if event_time_str:
            event_datetime = datetime.strptime(
                f"{event_date_str} {event_time_str}",
                "%Y-%m-%d %H:%M"
            )
        else:
            # 如果没有具体时间，默认为当天上午9点
            event_datetime = datetime.strptime(
                f"{event_date_str} 09:00",
                "%Y-%m-%d %H:%M"
            )

        # 计算提醒时间
        reminder_datetime = event_datetime - timedelta(minutes=advance_minutes)

        # 如果提醒时间已经过去，则不设置提醒
        if reminder_datetime < datetime.now():
            return None

        return reminder_datetime.isoformat()

    except Exception as e:
        logger.error(f"[event_extractor] 计算提醒时间失败: {e}")
        return None
