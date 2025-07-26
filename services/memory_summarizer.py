import os
import requests
import json
from datetime import datetime
import pytz
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class MemorySummarizer:
    def __init__(self):
        self.api_url = os.getenv("SUMMARY_API_URL")
        self.api_key = os.getenv("SUMMARY_API_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        logger.info("[MemorySummarizer] Initialized with API URL: %s", self.api_url)

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
        请分析以下聊天记录，识别其中的关键话题（至少一个，最多五个）。
        为每个独立话题生成一个JSON对象，包含：
        - topic: 话题标题
        - summary: 简洁摘要 (50-100字)
        - details: 详细内容 (200-500字)
        - importance: 重要度评分 (0.1-0.9)
        - tags: 相关标签（数组）
        - participants: 参与者列表（数组）
        
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
            schedule_details.append({
                "id": schedule.get("id"),
                "schedule_data": schedule.get("schedule_data"),
                "experiences": schedule.get("experiences")
            })
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
        请分析以下日程执行情况和关联的大事件背景（如果存在）。
        - 总结计划完成度
        - 识别遇到的问题和解决方案
        - 区分例行事务和特殊事件
        - 提取对未来有价值的经验
        
        生成包含以下内容的JSON：
        - 简洁摘要 (50-100字)
        - 详细内容 (200-500字)
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
        请分析以下大事件的整体影响和关键节点：
        - 总结事件全局影响
        - 识别关键转折点
        - 分析最终结果
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
        data_type: str, # 新增 memory_type 参数
        prompt: str,
        source_count: int,
        importance: float = None,
        is_array: bool = False,
    ) -> Dict:
        """调用AI总结API"""
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
                        "importance": {
                            "type": "number",
                            "minimum": 0.1,
                            "maximum": 1.0,
                        },
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

        payload = {
            "model": "mistralai/mistral-small-3.2-24b-instruct:free",  # 明确指定支持结构化输出的模型
            "prompt": prompt,
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

        try:
            response = requests.post(
                self.api_url, headers=self.headers, json=payload, timeout=30
            )
            response.raise_for_status()
            result = response.json()["choices"][0]["text"]
            logger.info(
                "[MemorySummarizer] API call successful. Received keys: %s",
                list(result.keys()),
            )

            # 构建标准记忆格式
            # 使用pytz获取带时区信息的UTC时间
            utc_now = datetime.now(pytz.utc)
            memory = {
                "id": f"memory_{utc_now.strftime('%Y_%m_%d_%H%M%S')}",
                "date": utc_now.date().isoformat(),
                "type": data_type, # 明确添加type字段
                "source_count": source_count,
                **result,
            }

            if importance is not None:
                memory["importance"] = importance

            return memory
        except Exception as e:
            logger.error("[MemorySummarizer] API call failed: %s", str(e))
            # 提供详细错误信息便于调试
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
            logger.error("API调用详细错误信息: %s", json.dumps(error_detail, indent=2))

            # 构建开发友好的错误消息
            error_msg = (
                f"AI总结API调用失败: {type(e).__name__} - {str(e)}\n\n"
                "调试信息:\n"
                f"- 错误类型: {type(e).__name__}\n"
                f"- 错误消息: {str(e)}\n"
            )

            # 包含原始响应内容（如果存在）
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f"- API响应: {json.dumps(error_detail, indent=2)}\n"
                except:
                    error_msg += f"- 原始响应: {e.response.text[:500]}\n"

            # 包含请求信息
            error_msg += (
                f"- 请求URL: {self.api_url}\n"
                f"- 请求方法: POST\n"
                f"- 请求头: {json.dumps(self.headers, indent=2)}\n"
                f"- 请求体: {json.dumps(payload, indent=2)[:1000]}"
            )

            raise RuntimeError(error_msg)
