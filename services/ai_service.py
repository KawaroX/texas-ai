"""
AI服务统一调度模块

重构后的AI服务入口，通过统一接口调度各个AI服务提供商。
保持与原有代码的API兼容性。
"""

import logging
from typing import AsyncGenerator, Optional, Dict, Any

from .ai_providers import OpenRouterProvider, GeminiProvider, OpenAIProvider

logger = logging.getLogger(__name__)


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
        统一的流式AI对话接口
        兼容原有的stream_ai_chat函数
        """
        # 根据模型选择提供商
        if model and any(gemini_model in model for gemini_model in ["gemini", "Gemini"]):
            provider = self.gemini
        elif model and any(openrouter_model in model for openrouter_model in ["mistral", "glm", "qwen"]):
            provider = self.openrouter
        else:
            provider = self.gemini  # 默认使用Gemini
        
        logger.info(f"[AIService] 使用 {provider.get_provider_name()} 进行流式对话")
        async for chunk in provider.stream_chat(messages, model):
            yield chunk
    
    async def call_ai_summary(self, prompt: str) -> str:
        """
        AI摘要调用接口
        兼容原有的call_ai_summary函数
        """
        messages = [{"role": "user", "content": prompt}]
        model = "mistralai/mistral-7b-instruct:free"
        logger.info(f"[AIService] 开始AI摘要，模型={model}")
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
        logger.debug(f"[ai.weather] 使用随机位置ID: {location} 查询 {date} 天气")

    try:
        logger.info(f"[ai.weather] 开始获取天气 date={date} location={location}")
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
        logger.debug(f"[ai.weather] 请求参数: {params}")

        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        logger.debug(f"[ai.weather] 响应: {data}")

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
                logger.info(f"[ai.weather] 成功获取 {date} 天气")
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
        logger.debug(f"[ai.weather] 使用最后一天数据作为 {date} 天气: {result[:50]}...")
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
    logger.warning(f"⚠️ 回退到伪随机天气 (种子: {seed})")

    weather_options = ["晴天", "阴天", "雨天", "雪天", "雾天"]
    weather_weights = [0.4, 0.25, 0.2, 0.05, 0.1]

    result = random.choices(weather_options, weights=weather_weights)[0]
    logger.debug(f"[ai.weather] 生成伪随机天气: {result}")
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
1. 工作日通常包含快递配送任务，周末可能有加班或休闲活动
2. 天气会影响户外活动和配送难度
3. 与同事的互动要符合角色关系
4. 时间安排要合理，活动之间要有逻辑连接

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
        logger.error(f"❌ generate_daily_schedule: AI返回的不是有效的JSON: {response}")
        return {"error": "AI返回格式错误", "raw_response": response}
    except Exception as e:
        logger.error(f"❌ generate_daily_schedule: 调用失败: {e}")
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
        logger.error(f"❌ generate_major_event: AI返回的不是有效的JSON: {response}")
        return {"error": "AI返回格式错误", "raw_response": response}
    except Exception as e:
        logger.error(f"❌ generate_major_event: 调用失败: {e}")
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
如果需要，交互的内容则是角色（德克萨斯）发送给用户的内容。
如果德克萨斯认为这件事值得分享给用户，则设置为ture，交互内容是德克萨斯对这件事想要和用户分享的经历和感受。
而不是指对德克萨斯日程中的伙伴，而是和她只能通过网络进行交流，但是是关系最好的朋友的主动交互。即判断此时德克萨斯是否会想要将当前的经历发送给该好友。
注意，如果是早上起床时的日程，则必须在某一个合适的item中设置need_interaction为true，交互内容是德克萨斯对早上起床的感受和道早安。但只需要在最开始的那一个即可。如果是起床以后则不用。
主动交互为true大概要占据40%左右，不要过低，至少需要有一个，但不要超过一半。

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
      "interaction_content": "交互内容（如果需要）"
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
        logger.error("❌ generate_micro_experiences: AI返回的不是有效的JSON")
        return [{"error": "AI返回格式错误"}]
    except Exception as e:
        logger.error(f"❌ generate_micro_experiences: 调用失败: {e}")
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
        logger.error(f"❌ summarize_past_micro_experiences: 调用失败: {e}")
        return f"故事生成失败: {str(e)}"