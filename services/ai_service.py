"""
AI服务统一调度模块

重构后的AI服务入口，通过统一接口调度各个AI服务提供商。
保持与原有代码的API兼容性。
"""

from utils.logging_config import get_logger

logger = get_logger(__name__)
from typing import AsyncGenerator, Optional, Dict, Any

from .ai_providers import OpenRouterProvider, GeminiProvider, OpenAIProvider


class AIService:
    """AI服务统一调度器"""

    def __init__(self):
        self.openrouter = OpenRouterProvider()
        self.gemini = GeminiProvider()
        self.openai = OpenAIProvider()

        # 默认路由配置
        self._default_routes = {
            "stream": "gemini",  # 默认流式对话使用Gemini
            "summary": "openrouter",  # 摘要使用OpenRouter
            "structured": "openai",  # 结构化生成使用OpenAI
        }

    def _get_provider(self, provider_name: str):
        """根据名称获取提供商实例"""
        providers = {
            "openrouter": self.openrouter,
            "gemini": self.gemini,
            "openai": self.openai,
        }
        return providers.get(provider_name)

    async def stream_ai_chat(self, messages: list, model: Optional[str] = None) -> AsyncGenerator[str, None]:
        """
        流式生成AI回复，按分隔符分段输出 - 完整恢复原有功能
        包含：模型路由、文本清理、分段处理、回退机制、Bark通知
        """
        import re
        # === DEBUG_CONTEXT_SAVE_START === 临时调试代码，用于保存AI上下文
        import os
        import json
        from datetime import datetime
        # === DEBUG_CONTEXT_SAVE_END ===
        from .ai_providers.utils import send_bark_notification
        
        # === DEBUG_CONTEXT_SAVE_START === 保存发送给AI的完整上下文到本地文件用于调试
        # 修改这里的 True/False 来启用/禁用调试功能，无需重启服务
        DEBUG_SAVE_CONTEXT = False
        if DEBUG_SAVE_CONTEXT:
            try:
                debug_dir = "/app/debug_output"
                os.makedirs(debug_dir, exist_ok=True)
                
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 包含毫秒
                
                # 1. 保存原始messages JSON
                messages_json_file = f"{debug_dir}/ai_context_messages_{timestamp_str}.json"
                with open(messages_json_file, 'w', encoding='utf-8') as f:
                    json.dump(messages, f, ensure_ascii=False, indent=2)
                
                # 2. 保存人类可读格式
                messages_readable_file = f"{debug_dir}/ai_context_readable_{timestamp_str}.txt"
                with open(messages_readable_file, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\n")
                    f.write("AI CONTEXT - 发送给AI的完整上下文\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"模型: {model}\n")
                    f.write(f"消息总数: {len(messages)}\n")
                    f.write("=" * 80 + "\n\n")
                    
                    for i, msg in enumerate(messages):
                        f.write(f"[消息 {i+1}] 角色: {msg['role']}\n")
                        f.write("-" * 40 + "\n")
                        f.write(msg['content'])
                        f.write("\n" + "=" * 40 + "\n\n")
                
                logger.debug(f"上下文已保存: {messages_json_file}")
                
            except Exception as e:
                logger.warning(f"保存上下文失败: {e}")
        # === DEBUG_CONTEXT_SAVE_END ===

        # 根据模型选择提供商
        if model and "gemini" in model.lower():
            provider = self.gemini  # 最常用，优先检查
        elif model and "/" in model:
            provider = self.openrouter  # OpenRouter模型格式：vendor/model
        else:
            provider = self.openai  # 其他情况使用OpenAI

        logger.info(f"使用 {provider.get_provider_name()} 进行流式对话")

        def clean_segment(text):
            """清理文本中的时间戳和发言人标识"""
            return re.sub(
                r"^\(距离上一条消息过去了：(\d+[hms]( \d+[hms])?)*\) \[\d{2}:\d{2}:\d{2}\] [^:]+:\s*",
                "",
                text,
            ).strip()

        buffer = ""
        total_processed = 0  # 跟踪已处理的字符数

        # 特殊处理：Gemini模型需要回退机制
        if model and "gemini" in model.lower():
            # 第一次尝试：Gemini
            gemini_failed = False
            yielded_any = False
            try:
                async for chunk in provider.stream_chat(messages, model):
                    # 检查是否是自动回复（说明Gemini失败了）
                    if chunk.startswith("[自动回复]") or not chunk.strip():
                        gemini_failed = True
                        break
                    if chunk.strip():
                        yielded_any = True
                    buffer += chunk

                    # 应用文本分段处理逻辑
                    while True:
                        # 优先按句号、问号、感叹号切分
                        indices = []
                        for sep in ["。", "？", "！"]:
                            idx = buffer.find(sep)
                            if idx != -1:
                                indices.append(idx)

                        if indices:
                            earliest_index = min(indices)
                            # 如果句末标点在末尾，暂不切分，等待收尾符号
                            if earliest_index == len(buffer) - 1:
                                break

                            # 将紧随其后的收尾字符一并包含
                            closers = set([
                                "”", "’", "】", "」", "』", "）", "》", "〉",
                                ")", "]", "'", '"',
                            ])
                            end_index = earliest_index + 1
                            while end_index < len(buffer) and buffer[end_index] in closers:
                                end_index += 1

                            segment = buffer[:end_index].strip()
                            cleaned_segment = clean_segment(segment)
                            if cleaned_segment:
                                logger.debug(f"stream_ai_chat: yield sentence='{cleaned_segment[:50]}'")
                                yield cleaned_segment
                            buffer = buffer[end_index:]
                            total_processed += end_index
                            continue

                        # 再尝试按换行符切分
                        newline_index = buffer.find("\n")
                        if newline_index != -1:
                            if newline_index == len(buffer) - 1:
                                buffer = buffer[:newline_index]
                                break
                            segment = buffer[:newline_index].strip()
                            cleaned_segment = clean_segment(segment)
                            if cleaned_segment:
                                logger.debug(f"stream_ai_chat: yield line='{cleaned_segment[:50]}'")
                                yield cleaned_segment
                            buffer = buffer[newline_index + 1:]
                            total_processed += newline_index + 1
                            continue

                        break

                # 处理最终剩余内容
                if buffer.strip():
                    final_segment = clean_segment(buffer)
                    if final_segment:
                        logger.debug(f"stream_ai_chat: yield final='{final_segment[:80]}'")
                        yield final_segment

                # 如果Gemini失败或无输出，立即尝试OpenAI协议
                if gemini_failed or not yielded_any:
                    fallback_message = f"Gemini失败，立即尝试OpenAI协议({model})"
                    logger.warning(fallback_message)
                    await send_bark_notification(
                        title="Gemini API 回退",
                        content=fallback_message,
                        group="AI_Service_Alerts",
                    )

                    # 重置buffer，第二次尝试：OpenAI协议
                    buffer = ""
                    openai_yielded = False
                    try:
                        async for chunk in self.openai.stream_chat(messages, model):
                            if chunk.strip():
                                openai_yielded = True
                            buffer += chunk


                        # OpenAI分段处理逻辑
                        while True:
                            indices = []
                            for sep in ["。", "？", "！"]:
                                idx = buffer.find(sep)
                                if idx != -1:
                                    indices.append(idx)
                            if indices:
                                earliest_index = min(indices)
                                if earliest_index == len(buffer) - 1:
                                    break
                                closers = set(["”", "’", "】", "」", "』", "）", "》", "〉", ")", "]", "'", '"'])
                                end_index = earliest_index + 1
                                while end_index < len(buffer) and buffer[end_index] in closers:
                                    end_index += 1
                                segment = buffer[:end_index].strip()
                                cleaned_segment = clean_segment(segment)
                                if cleaned_segment:
                                    yield cleaned_segment
                                buffer = buffer[end_index:]
                                continue
                            newline_index = buffer.find("\n")
                            if newline_index != -1:
                                if newline_index == len(buffer) - 1:
                                    buffer = buffer[:newline_index]
                                    break
                                segment = buffer[:newline_index].strip()
                                cleaned_segment = clean_segment(segment)
                                if cleaned_segment:
                                    yield cleaned_segment
                                buffer = buffer[newline_index + 1:]
                                continue
                            break

                        # 处理OpenAI剩余内容
                        if buffer.strip():
                            final_segment = clean_segment(buffer)
                            if final_segment:
                                yield final_segment

                    except Exception as openai_e:
                        logger.error(f"OpenAI也失败: {openai_e}")
                        openai_yielded = False

                    # 如果OpenAI也没有输出，返回自动回复
                    if not openai_yielded:
                        await send_bark_notification(
                            title="所有AI服务失败",
                            content=f"Gemini和OpenAI都失败，返回自动回复",
                            group="AI_Service_Alerts",
                        )
                        yield "[自动回复] 在忙，有事请留言"
                    return

            except Exception as e:
                # Gemini异常也尝试OpenAI
                logger.error(f"Gemini异常: {e}，尝试OpenAI")
                gemini_failed = True
        else:
            # 其他提供商也应用相同的文本分段处理逻辑
            async for chunk in provider.stream_chat(messages, model):
                buffer += chunk

                while True:
                    # 优先按句号、问号、感叹号切分
                    indices = []
                    for sep in ["。", "？", "！"]:
                        idx = buffer.find(sep)
                        if idx != -1:
                            indices.append(idx)

                    if indices:
                        earliest_index = min(indices)
                        if earliest_index == len(buffer) - 1:
                            break

                        closers = set(["”", "’", "】", "」", "』", "）", "》", "〉", ")", "]", "'", '"'])
                        end_index = earliest_index + 1
                        while end_index < len(buffer) and buffer[end_index] in closers:
                            end_index += 1

                        segment = buffer[:end_index].strip()
                        cleaned_segment = clean_segment(segment)
                        if cleaned_segment:
                            logger.debug(f"stream_ai_chat: yield sentence='{cleaned_segment[:50]}'")
                            yield cleaned_segment
                        buffer = buffer[end_index:]
                        total_processed += end_index
                        continue

                    newline_index = buffer.find("\n")
                    if newline_index != -1:
                        if newline_index == len(buffer) - 1:
                            buffer = buffer[:newline_index]
                            break
                        segment = buffer[:newline_index].strip()
                        cleaned_segment = clean_segment(segment)
                        if cleaned_segment:
                            logger.debug(f"stream_ai_chat: yield line='{cleaned_segment[:50]}'")
                            yield cleaned_segment
                        buffer = buffer[newline_index + 1:]
                        total_processed += newline_index + 1
                        continue

                    break

            # 处理最终剩余内容
            if buffer.strip():
                final_segment = clean_segment(buffer)
                if final_segment:
                    logger.debug(f"stream_ai_chat: yield final='{final_segment[:80]}'")
                    yield final_segment

    async def call_ai_summary(self, prompt: str) -> str:
        """
        AI摘要调用接口
        兼容原有的call_ai_summary函数
        """
        messages = [{"role": "user", "content": prompt}]
        model = "mistralai/mistral-7b-instruct:free"
        logger.info(f"开始AI摘要，模型={model}")
        return await self.openrouter.call_chat(messages, model)

    async def call_structured_generation(self, messages: list, max_retries: int = 3) -> dict:
        """
        结构化生成接口
        兼容原有的call_structured_generation函数
        """
        return await self.openai.call_structured_generation(messages, max_retries)


# 创建全局AI服务实例
ai_service = AIService()


# ===== 兼容性函数：保持原有API不变 =====

async def stream_ai_chat(messages: list, model: Optional[str] = None) -> AsyncGenerator[str, None]:
    """兼容原有接口的流式对话函数"""
    async for chunk in ai_service.stream_ai_chat(messages, model):
        yield chunk


async def stream_reply_ai_by_gemini(
    messages, model="gemini-2.5-pro"
) -> AsyncGenerator[str, None]:
    """兼容原有接口的Gemini流式对话函数"""
    async for chunk in ai_service.gemini.stream_chat(messages, model):
        yield chunk


async def stream_openrouter(
    messages, model="z-ai/glm-4.5-air:free"
) -> AsyncGenerator[str, None]:
    """兼容原有接口的OpenRouter流式对话函数"""
    async for chunk in ai_service.openrouter.stream_chat(messages, model):
        yield chunk


async def stream_reply_ai(
    messages, model="claude-3-7-sonnet-20250219"
) -> AsyncGenerator[str, None]:
    """兼容原有接口的OpenAI流式对话函数"""
    async for chunk in ai_service.openai.stream_chat(messages, model):
        yield chunk


async def call_openrouter(messages, model="mistralai/mistral-7b-instruct:free") -> str:
    """兼容原有接口的OpenRouter调用函数"""
    return await ai_service.openrouter.call_chat(messages, model)


async def call_gemini(messages, model="gemini-2.5-flash") -> str:
    """兼容原有接口的Gemini调用函数"""
    return await ai_service.gemini.call_chat(messages, model)


async def call_openai(messages, model="gpt-4o-mini") -> str:
    """兼容原有接口的OpenAI调用函数"""
    return await ai_service.openai.call_chat(messages, model, use_summary=True)


async def call_ai_summary(prompt: str) -> str:
    """兼容原有接口的AI摘要函数"""
    return await ai_service.call_ai_summary(prompt)


async def call_structured_generation(messages: list, max_retries: int = 3) -> dict:
    """兼容原有接口的结构化生成函数"""
    return await ai_service.call_structured_generation(messages, max_retries)


# ===== 其他原有函数保持不变 =====

import os
import json
import hashlib
import random
import httpx
from typing import Optional
import uuid

def get_weather_info(date: str, location: str = "") -> str:
    """
    获取指定日期和地点的天气信息（接入和风天气API，失败时退回伪随机生成）

    Args:
        date: 日期字符串 (YYYY-MM-DD)
        location: 位置（仅用于种子）

    Returns:
        str: 综合天气描述
    """
    # 默认location列表
    default_locations = [
        "101320101", "101320103", "14606", "1B6D3", "1D255", "1DC87", "275A5",
        "28FE1", "2BBD1", "2BC09", "39CD9", "407DA", "4622E", "55E7E",
        "8A9CA", "8E1C5", "9173", "D5EC3", "DD9B5", "E87DC",
    ]
    if not location:
        location = random.choice(default_locations)
        logger.debug(f"ai.weather 使用随机位置ID: {location} 查询 {date} 天气")

    try:
        logger.info(f"ai.weather 开始获取天气 date={date} location={location}")
        url = (
            "https://"
            + os.getenv("HEFENG_API_HOST", "have_no_api_host")
            + "/v7/weather/7d"
        )
        params = {
            "location": location,
            "key": os.getenv("HEFENG_API_KEY"),
            "lang": "zh",
        }
        logger.debug(f"ai.weather 请求参数: {params}")

        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        logger.debug(f"ai.weather 响应: {data}")

        if data.get("code") != "200":
            error_msg = f"API错误代码: {data.get('code')}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        for day in data.get("daily", []):
            if day.get("fxDate") == date:
                result = (
                    f"白天{day.get('textDay')}，夜晚{day.get('textNight')}。"
                    f"气温{day.get('tempMin')}°C~{day.get('tempMax')}°C，"
                    f"白天风：{day.get('windDirDay')} {day.get('windScaleDay')}级，"
                    f"夜晚风：{day.get('windDirNight')} {day.get('windScaleNight')}级，"
                    f"湿度：{day.get('humidity')}%，"
                    f"降水：{day.get('precip')}mm，"
                    f"紫外线指数：{day.get('uvIndex')}，"
                    f"月相：{day.get('moonPhase')}，"
                    f"日出：{day.get('sunrise')}，日落：{day.get('sunset')}，"
                    f"月升：{day.get('moonrise')}，月落：{day.get('moonset')}。"
                )
                logger.info(f"ai.weather 成功获取 {date} 天气")
                return result

        logger.warning(f"未找到 {date} 的天气数据，使用最后一天数据替代")
        day = data["daily"][-1]
        result = (
            f"白天{day.get('textDay')}，夜晚{day.get('textNight')}。"
            f"气温{day.get('tempMin')}°C~{day.get('tempMax')}°C，"
            f"白天风：{day.get('windDirDay')} {day.get('windScaleDay')}级，"
            f"夜晚风：{day.get('windDirNight')} {day.get('windScaleNight')}级，"
            f"湿度：{day.get('humidity')}%，"
            f"降水：{day.get('precip')}mm，"
            f"紫外线指数：{day.get('uvIndex')}，"
            f"月相：{day.get('moonPhase')}，"
            f"日出：{day.get('sunrise')}，日落：{day.get('sunset')}，"
            f"月升：{day.get('moonrise')}，月落：{day.get('moonset')}。"
        )
        logger.debug(f"ai.weather 使用最后一天数据作为 {date} 天气: {result[:50]}...")
        return result
    except httpx.HTTPError as e:
        logger.error(f"HTTP请求失败: {e}")
    except httpx.Timeout:
        logger.error("天气API请求超时")
    except ValueError as e:
        logger.error(f"API返回数据错误: {e}")
    except Exception as e:
        logger.error(f"获取天气异常: {str(e)}", exc_info=True)

    # 回退：使用伪随机天气
    seed = int(hashlib.md5(f"{date}-{location}".encode()).hexdigest()[:8], 16)
    random.seed(seed)
    logger.warning(f"回退到伪随机天气 (种子: {seed})")

    weather_options = ["晴天", "阴天", "雨天", "雪天", "雾天"]
    weather_weights = [0.4, 0.25, 0.2, 0.05, 0.1]

    result = random.choices(weather_options, weights=weather_weights)[0]
    logger.debug(f"ai.weather 生成伪随机天气: {result}")
    return result


async def generate_daily_schedule(
    date: str,
    day_type: str,
    weather: str,
    is_in_major_event: bool,
    major_event_context: Optional[dict] = None,
    special_flags: Optional[list] = None,
) -> dict:
    """功能：生成主日程"""
    # 构建详细的背景信息和Prompt
    prompt = f"""你是德克萨斯AI生活系统的核心模块，负责为明日方舟世界中的德克萨斯生成真实、连贯的日常生活安排。

## 角色背景
德克萨斯是企鹅物流的一名信使，性格冷静、专业，有着丰富的快递配送经验。她住在龙门，主要工作是为企鹅物流执行各种配送任务。她的日常生活围绕工作、休息和与同事（空、能天使、可颂等）的社交活动展开。

## 当前情况
- 日期: {date}
- 日期类型: {day_type} ({"工作日" if day_type == "weekday" else "周末"})
- 天气状况: {weather}
- 是否处于大事件中: {"是" if is_in_major_event else "否"}"""

    if is_in_major_event and major_event_context:
        prompt += f"\n- 大事件背景: {json.dumps(major_event_context, ensure_ascii=False)}"
    if special_flags:
        prompt += f"\n- 特殊情况: {', '.join(special_flags)}"

    prompt += f"""

## 生成要求
请根据德克萨斯的角色特点和当前情况，生成一份符合逻辑的日程安排。注意：
1. **必须明确起床和睡觉时间**：日程的第一项应该是起床（例如 06:30-07:00），最后一项应该是睡觉（例如 23:00-23:59）
2. 工作日通常包含快递配送任务，周末可能有加班或休闲活动
3. 天气会影响户外活动和配送难度
4. 与同事的互动要符合角色关系
5. 时间安排要合理，活动之间要有逻辑连接
6. 起床时间一般在 06:00-08:00 之间，睡觉时间一般在 22:00-23:59 之间，根据当天的活动安排适当调整

请严格按照以下JSON格式输出，不要包含任何其他文本：
{{
  "date": "{date}",
  "day_type": "{day_type}",
  "weather": "{weather}",
  "is_overtime": false,
  "daily_summary": "简要描述这一天的整体安排和主要活动",
  "schedule_items": [
    {{
      "start_time": "HH:MM",
      "end_time": "HH:MM（如果到次日，则写23:59。最多不得超过23:59）",
      "duration_minutes": 数字,
      "title": "活动标题",
      "category": "personal|work|social|rest",
      "priority": "high|medium|low",
      "location": "具体地点",
      "description": "详细的活动描述",
      "weather_affected": true或false,
      "companions": ["参与的其他角色"],
      "emotional_impact_tags": ["相关情绪标签"],
      "interaction_potential": "low|medium|high"
    }}
  ]
}}"""

    messages = [{"role": "user", "content": prompt}]

    # 使用非流式调用，指定Claude模型
    try:
        # 使用专用结构化生成函数
        response = await call_structured_generation(messages)
        if "error" in response:
            return response  # 直接返回错误

        result = response  # 已经是解析好的字典

        # 为每个schedule_item添加UUID
        for item in result.get("schedule_items", []):
            item["id"] = str(uuid.uuid4())

        return result
    except json.JSONDecodeError:
        logger.error(f"generate_daily_schedule: AI返回的不是有效的JSON: {response}")
        return {"error": "AI返回格式错误", "raw_response": response}
    except Exception as e:
        logger.error(f"generate_daily_schedule: 调用失败: {e}")
        return {"error": f"调用失败: {str(e)}"}


async def generate_major_event(
    duration_days: int,
    event_type: str,
    start_date: str,
    weather_forecast: Optional[dict] = None,
) -> dict:
    """功能：生成大事件"""
    # 构建详细的背景信息和Prompt
    prompt = f"""你是德克萨斯AI生活系统的核心模块，负责为明日方舟世界中的德克萨斯生成重要的生活事件。

## 角色背景
德克萨斯是企鹅物流的一名信使，性格冷静、专业，有着丰富的快递配送经验。她住在龙门，主要工作是为企鹅物流执行各种配送任务。她的日常生活围绕工作、休息和与同事（空、能天使、可颂等）的社交活动展开。

## 大事件定义
大事件是指持续多天、对德克萨斯生活产生重要影响的事件，如：
- 重要的配送任务（跨城市、高价值货物）
- 企鹅物流的团队活动或培训
- 个人重要事务（搬家、休假、医疗等）
- 龙门城市事件（节日、紧急状况等）

## 当前大事件参数
- 事件类型: {event_type}
- 开始日期: {start_date}
- 持续天数: {duration_days}天"""

    if weather_forecast:
        prompt += f"\n- 期间天气预报: {json.dumps(weather_forecast, ensure_ascii=False)}"

    prompt += f"""

## 生成要求
请根据德克萨斯的角色特点和事件参数，生成一个详细的大事件计划。注意：
1. 事件内容要符合德克萨斯的职业和性格特点
2. 每日计划要有逻辑连贯性和渐进性
3. 考虑天气对事件执行的影响
4. 包含合理的挑战和风险因素

请严格按照以下JSON格式输出，不要包含任何其他文本：
{{
  "event_title": "事件的简洁标题",
  "event_type": "{event_type}",
  "main_objective": "这个大事件的主要目标和意义",
  "total_days": {duration_days},
  "daily_plans": [
    {{
      "day": 1,
      "date": "YYYY-MM-DD",
      "phase": "事件的当前阶段（如：准备阶段、执行阶段、收尾阶段）",
      "summary": "当日的主要安排和目标",
      "key_activities": ["具体活动1", "具体活动2"],
      "expected_challenges": ["可能遇到的挑战"],
      "emotional_state": "德克萨斯在这一天的情绪状态",
      "location_start": "一天开始的地点",
      "location_end": "一天结束的地点"
    }}
  ],
  "success_criteria": ["判断事件成功的标准"],
  "risk_factors": ["可能影响事件的风险因素"]
}}"""

    messages = [{"role": "user", "content": prompt}]

    # 使用结构化生成函数
    try:
        response = await call_structured_generation(messages)
        if "error" in response:
            return response  # 直接返回错误

        result = response  # 已经是解析好的字典

        # 添加UUID
        result["event_id"] = str(uuid.uuid4())

        return result
    except json.JSONDecodeError:
        logger.error(f"generate_major_event: AI返回的不是有效的JSON: {response}")
        return {"error": "AI返回格式错误", "raw_response": response}
    except Exception as e:
        logger.error(f"generate_major_event: 调用失败: {e}")
        return {"error": f"调用失败: {str(e)}"}


async def generate_micro_experiences(
    schedule_item: dict,
    current_date: str,
    previous_experiences: Optional[list] = None,
    major_event_context: Optional[dict] = None,
) -> list:
    """功能：为单个日程项目生成多个微观经历项（5-30分钟颗粒度）"""
    # 构建详细的背景信息和Prompt
    prompt = f"""你是德克萨斯AI生活系统的微观经历生成模块，负责为明日方舟世界中的德克萨斯生成真实、细腻的生活片段。

## 角色背景
德克萨斯是企鹅物流的一名员工，性格冷静、专业，有着丰富的快递配送经验。她住在龙门，主要工作是为企鹅物流执行各种配送任务。她的日常生活围绕工作、休息和与同事（空、能天使、可颂等）的社交活动展开。

## 当前情况
- 当前日期: {current_date}
- 日程项目: {schedule_item.get("title", "未知活动")}
- 项目开始时间: {schedule_item.get("start_time", "未知")}
- 项目结束时间: {schedule_item.get("end_time", "未知")}
- 活动地点: {schedule_item.get("location", "未知地点")}
- 活动描述: {schedule_item.get("description", "无描述")}
- 同伴: {", ".join(schedule_item.get("companions", [])) if schedule_item.get("companions") else "独自一人"}"""

    if previous_experiences:
        prompt += f"\n- 之前的经历摘要: {json.dumps(previous_experiences, ensure_ascii=False)}"
    if major_event_context:
        prompt += f"\n- 大事件背景: {json.dumps(major_event_context, ensure_ascii=False)}"

    prompt += f"""## 生成要求
请根据德克萨斯的角色特点和当前情况，将日程项目拆解成多个5-30分钟颗粒度的微观经历项。注意：
1. 每个经历项应包含具体的时间段（开始和结束时间）并且所有微观经历连续起来整体上要从头到到尾覆盖整个日程项目
2. 内容要符合德克萨斯的性格特点（冷静、专业、内敛）
3. 情绪表达要细腻但不夸张
4. 思考要符合她的职业背景和经历
5. 如果需要交互，要符合角色关系和情境

## 主动交互须知
这是一个 AI 角色扮演的一部分。这里是模拟角色的日常生活。所谓主动交互，是指角色（德克萨斯）是否要与用户进行互动。
如果德克萨斯认为这件事值得分享给用户，则设置为true，交互内容是德克萨斯对这件事想要和用户分享的经历和感受。
用户是和她只能通过网络进行交流，但是是关系最好的朋友。

**特别注意**：
- **只有当日程标题包含"起床"或"睡觉"时**，才需要在某个合适的item中包含早安或晚安的问候
- 如果是起床相关日程，在第一个item中设置need_interaction为true，交互内容包含道早安
- 如果是睡觉相关日程，在最后一个item中设置need_interaction为true，交互内容包含道晚安
- 其他日程项不需要早安/晚安问候

主动交互为true大概要占据40%左右，不要过低，至少需要有一个，但不要超过一半。

## 图片生成决策
对于每个微观经历item，你需要判断是否值得生成图片以及生成什么类型的图片：

**⚠️ 重要前提条件**：
- **只有当 need_interaction=true 时，才考虑设置 need_image=true**
- 如果 need_interaction=false，则 need_image 必须为 false
- **每个微观经历（整个items数组）中，最多只能有 2 个 item 的 need_image=true**
- 优先为最重要、最值得记录的时刻生成图片

**是否生成图片 (need_image)**：
在 need_interaction=true 的前提下，当满足以下条件之一时，设置为true：
1. 遇到美丽的风景、特殊的天气景观（日落、晚霞、雨后彩虹等）
2. 重要的时刻或事件（完成重要任务、特殊庆祝、难忘瞬间等）
3. 有趣的场景或经历（意外发生的趣事、特别的互动等）
4. 与朋友的温馨时刻（一起用餐、聊天、合作等）
5. **如果是起床或睡觉相关的经历，通常设置为true（自拍类型）**

**数量控制**：
- 仔细挑选最值得生成图片的 1-2 个时刻
- 不要为普通、平淡的交互生成图片
- 如果整个微观经历都很平淡，可以只有 0-1 个图片

**图片类型 (image_type)**：
- "selfie"（自拍）：当德克萨斯想要分享自己的状态、表情、或与朋友的合影时
  - 示例：起床后的状态、心情好时的自拍、与朋友的合照
- "scene"（场景）：当重点是展示环境、风景、或第一人称视角的场景时
  - 示例：美丽的风景、工作场景、特殊的环境

如果need_image为false，image_type设置为null。

**图片原因 (image_reason)**：
简短说明为什么要生成这张图片（用于日志记录），例如："美丽的晚霞"、"完成重要任务的心情"、"与能天使的有趣对话"等。

请严格按照以下JSON格式输出，不要包含任何其他文本：
{{
  "date": "{current_date}",
  "schedule_item_id": "{schedule_item.get("id", "")}",
  "items": [
    {{
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "content": "详细描述这段经历",
      "emotions": "情绪状态",
      "thoughts": "内心的想法",
      "need_interaction": true或false,
      "interaction_content": "交互内容（如果需要）",
      "need_image": true或false,
      "image_type": "selfie"或"scene"或null,
      "image_reason": "生成图片的原因（如果need_image为true）"
    }},
    // 更多经历项...
  ],
  "created_at": "自动生成，无需填写"
}}"""

    messages = [{"role": "user", "content": prompt}]

    # 使用结构化生成函数
    try:
        response = await call_structured_generation(messages)
        if "error" in response:
            return [response]  # 返回错误列表

        # 确保返回的是列表格式
        if "items" not in response or not isinstance(response["items"], list):
            return [{"error": "AI返回格式错误: 缺少items列表", "raw_response": response}]

        # 为每个经历项添加唯一ID
        for item in response["items"]:
            item["id"] = str(uuid.uuid4())
            item["schedule_item_id"] = schedule_item.get("id", "")

        return response["items"]
    except json.JSONDecodeError:
        logger.error("generate_micro_experiences: AI返回的不是有效的JSON")
        return [{"error": "AI返回格式错误"}]
    except Exception as e:
        logger.error(f"generate_micro_experiences: 调用失败: {e}")
        return [{"error": f"调用失败: {str(e)}"}]


async def summarize_past_micro_experiences(experiences: list) -> str:
    """功能：将过去的微观经历整理成故事化的文本"""
    prompt = f"""你是德克萨斯（明日方舟角色）。
现在请你以第一人称回顾刚刚经历的微观事件，目标是生成一份完整、真实、有条理的自我记录。

请遵循以下要求：
	1.	按照时间顺序，逐条用自然语言流畅地陈述每一段经历的发生内容、所见所闻、内心想法、情绪变化；
	2.	不得遗漏任何经历项，每段经历都要覆盖基本要素（做了什么、想了什么、当时的情绪）；
	3.	不进行文学化加工，也不编造未在经历中出现的内容；
	4.	如果某些经历之间存在前后关联，可以指出，让衔接流畅。

你正在生成的文本目的在于完整记录当天生活细节。
注意语言要连贯自然，让其他人阅读的时候，能理解你的想法，了解你今天为止的全部经历。
注意详略得当，把你认为印象深刻的内容详细地记录下来。其他的可以简要一些。
有点类似于日记，或者是你经历这些事情后的回忆过程。

以下是你今天的微观经历数据：
{json.dumps(experiences, ensure_ascii=False, indent=2)}

请开始记录：
"""

    messages = [{"role": "user", "content": prompt}]

    try:
        # 使用非流式调用，获取故事化文本
        response = await call_openrouter(messages, model="z-ai/glm-4.5-air:free")
        # response = await call_openai(messages, model="gpt-4o-mini")
        return response
    except Exception as e:
        logger.error(f"summarize_past_micro_experiences: 调用失败: {e}")
        return f"故事生成失败: {str(e)}"
