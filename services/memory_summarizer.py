import os
import requests
import json
import time  # 导入time模块用于延迟
from datetime import datetime
import pytz
from typing import Dict, List
import logging
import redis  # 添加Redis支持

logger = logging.getLogger(__name__)


class MemorySummarizer:
    def __init__(self):
        self.api_url = os.getenv("SUMMARY_API_URL")
        self.api_key = os.getenv("SUMMARY_API_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.max_retries = 3  # 最大重试次数
        self.initial_delay = 5  # 初始延迟秒数

        # 初始化Redis客户端
        self.redis_url = os.getenv("REDIS_URL")
        if not self.redis_url:
            raise RuntimeError("环境变量REDIS_URL未设置")
        self.redis_client = redis.Redis.from_url(self.redis_url)

        logger.info(
            "[MemorySummarizer] Initialized with API URL: %s and Redis", self.api_url
        )

    def summarize(self, data_type: str, data: List[Dict]) -> Dict:
        """根据数据类型调用不同的总结方法"""
        logger.info("[MemorySummarizer] Summarizing data of type: %s", data_type)
        if data_type == "chat":
            return self.summarize_chat(data)
        elif data_type == "schedule":
            return self.summarize_schedule(data)
        elif data_type == "event":
            return self.summarize_event(data)
        else:
            raise ValueError(f"未知的数据类型: {data_type}")

    def summarize_chat(self, chats: List[Dict]) -> List[Dict]:
        """总结聊天记录（按话题分割为多个记忆项）"""
        prompt = f"""
请分析以下聊天记录，识别其中的关键话题（至少一个，没有上限，根据情况而定）。
为每个独立话题生成一个JSON对象，包含：
- topic: 话题标题
- summary: 简洁摘要 (50-100字)
- details: 详细内容 (500-3000字)（详细介绍发生了什么）
- importance: 重要度评分 (0.1-0.9)
- tags: 相关标签（数组）
- participants: 参与者列表（数组）

对话是德克萨斯与另一个人之间的聊天记录，小德是德克萨斯的昵称。另一个人是Kawaro。如果无法知道另一个人是谁，那么就认为他叫Kawaro。

将多个话题组织在JSON数组中返回。

聊天记录：
{json.dumps(chats, ensure_ascii=False)}
"""
        return self._call_api("daily_conversation", prompt, len(chats), is_array=True)

    def summarize_schedule(self, schedules: List[Dict]) -> Dict:
        """总结日程和经历，如果关联大事件则包含大事件信息"""
        schedule_details = []
        major_event_context = ""

        for schedule in schedules:
            schedule_details.append(
                {
                    "id": schedule.get("id"),
                    "schedule_data": schedule.get("schedule_data"),
                    "experiences": schedule.get("experiences"),
                }
            )
            if schedule.get("major_event_details"):
                event = schedule["major_event_details"]
                major_event_context += (
                    f"\n关联大事件信息:\n"
                    f"  事件ID: {event.get('id')}\n"
                    f"  开始日期: {event.get('start_date')}\n"
                    f"  结束日期: {event.get('end_date')}\n"
                    f"  主要内容: {event.get('main_content')}\n"
                    f"  事件类型: {event.get('event_type')}\n"
                )

        prompt = f"""
请分析以下德克萨斯（角色名字）的日程安排和关联的大事件背景（如果存在）。
- 总结德克萨斯（角色名字）做了什么
- 她有什么想法、有什么感受
- 有什么值得记忆的事情
- 有什么重要的事情、事件或计划

生成包含以下内容的JSON：
- 简洁摘要 (50-100字)
- 详细内容 (500-3000字)（详细介绍发生了什么）
- 重要度评分 (0.1-0.9)
- 相关标签

日程数据：
{json.dumps(schedule_details, ensure_ascii=False)}
{major_event_context}
        """
        return self._call_api("daily_schedule", prompt, len(schedules))

    def summarize_event(self, events: List[Dict]) -> Dict:
        """总结大事件"""
        prompt = f"""
大事件是德克萨斯工作或者生活上的比较非常的事件，请分析以下大事件的整体影响和关键节点：
- 总结事件全局影响
- 识别关键转折点
- 分析最终结果
- 找到值得记忆的内容，例如：
  - 重要的决策或结果
  - 有价值的经验或教训
  - 有趣的发现或创新
  - 旅途中的有意思的遭遇
- 重要度强制设为1.0

生成包含以下内容的JSON：
- 简洁摘要 (50-100字)
- 详细内容 (200-500字)
- 重要度评分 (固定1.0)
- 相关标签

事件数据：
{json.dumps(events, ensure_ascii=False)}
"""
        return self._call_api("major_event", prompt, len(events), importance=1.0)

    def _call_api(
        self,
        data_type: str,  # 新增 memory_type 参数
        prompt: str,
        source_count: int,
        importance: float = None,
        is_array: bool = False,
    ) -> Dict:
        """调用AI总结API"""
        # 检查Redis缓存
        memory_date = datetime.utcnow().strftime("%Y-%m-%d")
        cache_key = f"mem0:{data_type}_{memory_date}"
        cached_data = self.redis_client.get(cache_key)
        if cached_data:
            logger.info("[MemorySummarizer] 命中缓存: %s", cache_key)
            return json.loads(cached_data)

        logger.info(
            "[MemorySummarizer] Calling API with prompt length %d and source_count %d",
            len(prompt),
            source_count,
        )
        # 定义JSON Schema模板
        base_schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "简洁摘要内容"},
                "details": {"type": "string", "description": "详细内容描述"},
                "importance": {"type": "number", "minimum": 0.1, "maximum": 1.0},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "details", "importance", "tags"],
            "additionalProperties": False,
        }

        # 根据数据类型调整schema
        if is_array:
            # 聊天记录需要返回数组
            base_schema = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "summary": {"type": "string"},
                        "details": {"type": "string"},
                        "importance": {"type": "number", "minimum": 0.1, "maximum": 1},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "participants": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "topic",
                        "summary",
                        "details",
                        "importance",
                        "tags",
                        "participants",
                    ],
                    "additionalProperties": False,
                },
            }
        else:
            # 其他类型保持对象结构
            if "chat" in prompt:
                base_schema["properties"]["participants"] = {
                    "type": "array",
                    "items": {"type": "string"},
                }
            elif "event" in prompt:
                base_schema["properties"]["importance"]["const"] = 1.0

        # 修改为标准的 messages 格式
        payload = {
            "model": "qwen/qwen3-235b-a22b:free",  # 明确指定支持结构化输出的模型
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "memory_summary",
                    "strict": True,
                    "schema": base_schema,
                },
            },
        }
        time.sleep(60)

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.api_url, headers=self.headers, json=payload, timeout=30
                )
                response.raise_for_status()  # 检查HTTP错误

                # 第一次解析：获取AI模型的原始响应
                api_response_data = response.json()

                # 检查并提取实际的总结内容，通常在 'message' -> 'content' 或 'text' 中
                if (
                    "choices" in api_response_data
                    and len(api_response_data["choices"]) > 0
                ):
                    choice = api_response_data["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                        result_str = choice["message"]["content"]
                    elif "text" in choice:  # 兼容旧版或某些模型直接返回text
                        result_str = choice["text"]
                    else:
                        raise ValueError("AI响应中未找到'message.content'或'text'字段")
                else:
                    raise ValueError("AI响应中未找到'choices'字段或其为空")

                # 第二次解析：将总结内容字符串解析为JSON对象
                result = json.loads(result_str)

                logger.info(
                    "[MemorySummarizer] API call successful. Parsed content keys: %s",
                    list(result.keys()) if isinstance(result, dict) else "N/A",
                )

                # 构建标准记忆格式，只包含核心总结内容
                utc_now = datetime.now(pytz.utc)
                memory = {
                    "id": f"memory_{utc_now.strftime('%Y_%m_%d_%H%M%S')}",
                    "date": utc_now.date().isoformat(),
                    "type": data_type,
                    "source_count": source_count,
                    "content": result,  # 直接存储解析后的JSON对象
                }

                if importance is not None:
                    memory["importance"] = importance

                # 缓存API结果（24小时有效期）
                self.redis_client.setex(cache_key, 86400, json.dumps(memory))
                logger.info("[MemorySummarizer] 已缓存结果: %s", cache_key)
                return memory

            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(
                    "[MemorySummarizer] API call failed (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    str(e),
                )
                if attempt < self.max_retries - 1:
                    delay = self.initial_delay * (2**attempt)  # 指数退避
                    logger.info("[MemorySummarizer] Retrying in %f seconds...", delay)
                    time.sleep(delay)
                else:
                    # 所有重试都失败了，抛出最终错误
                    logger.error("[MemorySummarizer] All API call attempts failed.")
                    response_text_content = None
                    if hasattr(e, "response") and e.response is not None:
                        try:
                            response_text_content = e.response.text
                        except Exception:
                            response_text_content = "无法获取响应文本"

                    error_detail = {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "response_text": response_text_content,
                        "request_payload": payload,
                    }
                    logger.error(
                        "API调用详细错误信息: %s", json.dumps(error_detail, indent=2)
                    )

                    error_msg = (
                        f"AI总结API调用失败: {type(e).__name__} - {str(e)}\n\n"
                        "调试信息:\n"
                        f"- 错误类型: {type(e).__name__}\n"
                        f"- 错误消息: {str(e)}\n"
                    )

                    if hasattr(e, "response") and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg += (
                                f"- API响应: {json.dumps(error_detail, indent=2)}\n"
                            )
                        except:
                            error_msg += f"- 原始响应: {e.response.text[:500]}\n"

                    error_msg += (
                        f"- 请求URL: {self.api_url}\n"
                        f"- 请求方法: POST\n"
                        f"- 请求头: {json.dumps(self.headers, indent=2)}\n"
                        f"- 请求体: {json.dumps(payload, indent=2)[:1000]}"
                    )
                    raise RuntimeError(error_msg)
            except Exception as e:
                # 捕获其他未预料的异常
                logger.error(
                    "[MemorySummarizer] An unexpected error occurred: %s", str(e)
                )
                raise RuntimeError(f"AI总结API调用发生意外错误: {str(e)}")
