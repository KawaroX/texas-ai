#!/usr/bin/env python3
"""
主动交互系统测试脚本
用于测试整个主动交互流程，包括数据生成、Redis存储、Celery任务执行等
"""

import os
import sys
import json
import redis
import asyncio
import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Any
import uuid

# 添加项目根目录到Python路径
sys.path.append("/app")

from app.config import settings
from utils.postgres_service import (
    insert_daily_schedule,
    insert_micro_experience,
    get_daily_schedule_by_date,
    get_micro_experiences_by_daily_schedule_id,
)
from app.life_system import collect_interaction_experiences
from tasks.interaction_tasks import process_scheduled_interactions

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ActiveInteractionTester:
    def __init__(self):
        self.redis_client = redis.StrictRedis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        self.test_date = datetime.now().date()
        self.test_date_str = self.test_date.strftime("%Y-%m-%d")
        self.test_schedule_id = None
        self.test_experiences = []

    def print_section(self, title: str):
        """打印测试章节标题"""
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")

    def print_step(self, step: str):
        """打印测试步骤"""
        print(f"\n🔸 {step}")

    def print_success(self, message: str):
        """打印成功信息"""
        print(f"✅ {message}")

    def print_error(self, message: str):
        """打印错误信息"""
        print(f"❌ {message}")

    def print_info(self, message: str):
        """打印信息"""
        print(f"ℹ️  {message}")

    def check_docker_environment(self):
        """检查Docker环境"""
        self.print_section("检查Docker环境")

        # 检查Redis连接
        self.print_step("检查Redis连接")
        try:
            self.redis_client.ping()
            self.print_success("Redis连接正常")
        except Exception as e:
            self.print_error(f"Redis连接失败: {e}")
            return False

        # 检查环境变量
        self.print_step("检查环境变量")
        required_vars = ["REDIS_URL", "POSTGRES_PORT", "POSTGRES_DB"]
        for var in required_vars:
            if hasattr(settings, var):
                self.print_success(f"{var}: {getattr(settings, var)}")
            else:
                self.print_error(f"缺少环境变量: {var}")
                return False

        return True

    async def create_test_data(self):
        """创建测试数据"""
        self.print_section("创建测试数据")

        # 1. 创建测试日程
        self.print_step("创建测试日程")
        try:
            # 检查是否已存在测试日程
            existing_schedule = get_daily_schedule_by_date(self.test_date_str)
            if existing_schedule:
                self.test_schedule_id = existing_schedule["id"]
                self.print_info(f"使用已存在的日程 ID: {self.test_schedule_id}")
            else:
                # 创建新的测试日程
                test_schedule_data = {
                    "date": self.test_date_str,
                    "schedule_items": [
                        {
                            "id": str(uuid.uuid4()),
                            "title": "测试活动1",
                            "start_time": "10:00",
                            "end_time": "11:00",
                            "description": "用于测试主动交互的活动",
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "title": "测试活动2",
                            "start_time": "14:00",
                            "end_time": "15:00",
                            "description": "另一个测试活动",
                        },
                    ],
                }

                self.test_schedule_id = insert_daily_schedule(
                    date=self.test_date_str,
                    schedule_data=test_schedule_data,
                    weather="晴天",
                    is_in_major_event=False,
                    major_event_id=None,
                )
                self.print_success(f"创建测试日程，ID: {self.test_schedule_id}")

        except Exception as e:
            self.print_error(f"创建测试日程失败: {e}")
            return False

        # 2. 创建测试微观经历
        self.print_step("创建测试微观经历")
        try:
            # 创建当前时间前后的测试经历
            current_time = datetime.now()

            # 过去的经历（应该被触发）
            past_exp = {
                "id": str(uuid.uuid4()),
                "start_time": (current_time - timedelta(minutes=30)).strftime("%H:%M"),
                "end_time": (current_time + timedelta(minutes=30)).strftime("%H:%M"),
                "content": "这是一个测试的微观经历，需要主动交互",
                "emotions": "好奇",
                "thoughts": "想知道这个测试是否会成功",
                "need_interaction": True,
                "interaction_content": "嘿，我刚刚完成了一个有趣的测试活动，你觉得怎么样？",
                "schedule_item_id": str(uuid.uuid4()),
            }

            # 未来的经历（不应该被触发）
            future_exp = {
                "id": str(uuid.uuid4()),
                "start_time": (current_time + timedelta(hours=1)).strftime("%H:%M"),
                "end_time": (current_time + timedelta(hours=2)).strftime("%H:%M"),
                "content": "这是一个未来的微观经历",
                "emotions": "期待",
                "thoughts": "这个应该不会被立即触发",
                "need_interaction": True,
                "interaction_content": "我正在期待即将到来的活动！",
                "schedule_item_id": str(uuid.uuid4()),
            }

            self.test_experiences = [past_exp, future_exp]

            # 插入微观经历到数据库
            for exp in self.test_experiences:
                insert_micro_experience(
                    date=self.test_date_str,
                    daily_schedule_id=self.test_schedule_id,
                    related_item_id=exp["schedule_item_id"],
                    experiences=[exp],
                )

            self.print_success(f"创建了 {len(self.test_experiences)} 个测试微观经历")

            # 打印测试经历详情
            for i, exp in enumerate(self.test_experiences, 1):
                self.print_info(
                    f"经历 {i}: {exp['start_time']}-{exp['end_time']} | {exp['interaction_content'][:50]}..."
                )

        except Exception as e:
            self.print_error(f"创建测试微观经历失败: {e}")
            return False

        return True

    async def test_redis_storage(self):
        """测试Redis存储功能"""
        self.print_section("测试Redis存储功能")

        self.print_step("调用collect_interaction_experiences函数")
        try:
            # 调用生活系统的收集函数
            result = await collect_interaction_experiences(self.test_date)
            if result:
                self.print_success("成功调用collect_interaction_experiences")
            else:
                self.print_error("collect_interaction_experiences返回False")
                return False
        except Exception as e:
            self.print_error(f"调用collect_interaction_experiences失败: {e}")
            return False

        # 检查Redis Sorted Set
        self.print_step("检查Redis Sorted Set")
        interaction_key = f"interaction_needed:{self.test_date_str}"
        try:
            # 获取所有事件
            all_events = self.redis_client.zrange(interaction_key, 0, -1)
            self.print_info(f"Redis key: {interaction_key}")
            self.print_info(f"找到 {len(all_events)} 个需要交互的事件")

            for i, event_json in enumerate(all_events, 1):
                try:
                    event_data = json.loads(event_json)
                    self.print_info(
                        f"事件 {i}: ID={event_data.get('id', 'N/A')}, "
                        f"时间={event_data.get('start_time', 'N/A')}-{event_data.get('end_time', 'N/A')}"
                    )
                except json.JSONDecodeError:
                    self.print_error(f"事件 {i}: JSON解析失败")

            if len(all_events) > 0:
                self.print_success("Redis Sorted Set存储正常")
            else:
                self.print_error("Redis Sorted Set中没有数据")
                return False

        except Exception as e:
            self.print_error(f"检查Redis Sorted Set失败: {e}")
            return False

        return True

    async def test_celery_task_manual(self):
        """手动测试Celery任务"""
        self.print_section("手动测试Celery任务")

        self.print_step("手动调用主动交互处理逻辑")
        try:
            # 模拟Celery任务的逻辑，但直接调用异步函数
            from app.mattermost_client import MattermostWebSocketClient
            from tasks.interaction_tasks import _process_events_async
            
            current_timestamp = datetime.now().timestamp()
            today_key = f"interaction_needed:{self.test_date_str}"
            
            # 获取到期事件
            expired_events = self.redis_client.zrangebyscore(today_key, 0, current_timestamp)
            
            if not expired_events:
                self.print_info("没有找到到期的事件")
                return True
                
            self.print_info(f"找到 {len(expired_events)} 个到期事件")
            
            # 实例化 MattermostWebSocketClient
            ws_client = MattermostWebSocketClient()
            
            # 直接调用异步处理函数
            await _process_events_async(ws_client, today_key, expired_events)
            
            self.print_success("成功调用主动交互处理逻辑")

            # 检查交互记录
            self.print_step("检查交互记录")
            interacted_key = f"interacted_schedule_items:{self.test_date_str}"
            interacted_items = self.redis_client.smembers(interacted_key)

            self.print_info(f"已交互的事件数量: {len(interacted_items)}")
            for item in interacted_items:
                self.print_info(f"已交互事件ID: {item}")

            if len(interacted_items) > 0:
                self.print_success("发现已交互的事件记录")
            else:
                self.print_info("没有找到已交互的事件记录（可能是时间范围不匹配）")

        except Exception as e:
            self.print_error(f"手动测试Celery任务失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        return True

    def check_redis_state(self):
        """检查Redis状态"""
        self.print_section("检查Redis状态")

        # 检查interaction_needed
        self.print_step("检查interaction_needed状态")
        interaction_key = f"interaction_needed:{self.test_date_str}"
        try:
            current_timestamp = datetime.now().timestamp()

            # 获取所有事件
            all_events = self.redis_client.zrange(
                interaction_key, 0, -1, withscores=True
            )
            self.print_info(f"总事件数: {len(all_events)}")

            # 获取到期事件
            expired_events = self.redis_client.zrangebyscore(
                interaction_key, 0, current_timestamp
            )
            self.print_info(f"到期事件数: {len(expired_events)}")

            # 显示事件详情
            for event_json, score in all_events:
                try:
                    event_data = json.loads(event_json)
                    event_time = datetime.fromtimestamp(score)
                    is_expired = score <= current_timestamp
                    status = "已到期" if is_expired else "未到期"

                    self.print_info(
                        f"事件: {event_data.get('id', 'N/A')} | "
                        f"结束时间: {event_time.strftime('%H:%M:%S')} | "
                        f"状态: {status}"
                    )
                except:
                    self.print_error("解析事件数据失败")

        except Exception as e:
            self.print_error(f"检查interaction_needed失败: {e}")

        # 检查interacted_schedule_items
        self.print_step("检查interacted_schedule_items状态")
        interacted_key = f"interacted_schedule_items:{self.test_date_str}"
        try:
            interacted_items = self.redis_client.smembers(interacted_key)
            self.print_info(f"已交互事件数: {len(interacted_items)}")

            for item in interacted_items:
                self.print_info(f"已交互: {item}")

        except Exception as e:
            self.print_error(f"检查interacted_schedule_items失败: {e}")

    def cleanup_test_data(self):
        """清理测试数据"""
        self.print_section("清理测试数据")

        self.print_step("清理Redis测试数据")
        try:
            # 清理interaction_needed
            interaction_key = f"interaction_needed:{self.test_date_str}"
            deleted_count = self.redis_client.delete(interaction_key)
            self.print_info(f"删除interaction_needed key: {deleted_count}")

            # 清理interacted_schedule_items
            interacted_key = f"interacted_schedule_items:{self.test_date_str}"
            deleted_count = self.redis_client.delete(interacted_key)
            self.print_info(f"删除interacted_schedule_items key: {deleted_count}")

            self.print_success("Redis测试数据清理完成")

        except Exception as e:
            self.print_error(f"清理Redis数据失败: {e}")

        self.print_info("注意: 数据库中的测试数据需要手动清理")

    async def run_full_test(self):
        """运行完整测试"""
        self.print_section("开始主动交互系统完整测试")

        try:
            # 1. 检查环境
            if not self.check_docker_environment():
                self.print_error("环境检查失败，终止测试")
                return False

            # # 2. 创建测试数据
            if not await self.create_test_data():
                self.print_error("测试数据创建失败，终止测试")
                return False

            # 3. 测试Redis存储
            if not await self.test_redis_storage():
                self.print_error("Redis存储测试失败，终止测试")
                return False

            # 4. 手动测试Celery任务
            if not await self.test_celery_task_manual():
                self.print_error("Celery任务手动测试失败，终止测试")
                return False

            # 5. 检查Redis状态
            self.check_redis_state()

            self.print_success("主动交互系统完整测试成功")
            return True

        except Exception as e:
            self.print_error(f"测试过程中发生错误: {e}")
            return False

    def run(self):
        """运行测试"""
        asyncio.run(self.run_full_test())
        self.cleanup_test_data()


if __name__ == "__main__":
    tester = ActiveInteractionTester()
    tester.run()
