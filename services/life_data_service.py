import json
import logging
import redis
from app.config import settings
from app.life_system import LifeSystemQuery
import logging
from services.ai_service import summarize_past_micro_experiences  # 导入新的AI服务

logger = logging.getLogger(__name__)

from datetime import date, datetime  # 确保 datetime 类被正确导入

logger = logging.getLogger(__name__)

# 复用项目现有的Redis连接池
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


class LifeDataService:
    def __init__(self):
        self.redis = redis_client

    async def _generate_summary_with_status_tracking(
        self, 
        all_past_micro_experiences, 
        current_exp_json,
        prev_past_micro_experiences_key,
        summary_generation_status_key,
        date_str
    ):
        """生成汇总并跟踪状态"""
        logger.info("[LIFE_DATA] 🤖 开始生成微观经历汇总")
        
        # 记录开始尝试的状态
        attempt_status = {
            "last_attempt_time": datetime.now().isoformat(),
            "last_attempt_data": current_exp_json,
            "last_success": "false",
            "attempt_count": str(int(self.redis.hget(summary_generation_status_key, "attempt_count") or "0") + 1)
        }
        self.redis.hset(summary_generation_status_key, mapping=attempt_status)
        self.redis.expire(summary_generation_status_key, 86400)
        
        try:
            # 汇总过去的微观经历
            summarized_story = await summarize_past_micro_experiences(all_past_micro_experiences)
            
            # 验证生成结果
            if not summarized_story or summarized_story.strip() == "":
                logger.warning("⚠️ AI汇总生成结果为空，保持重试状态")
                # 更新失败状态，但不更新数据基准
                failure_status = {
                    "last_success": "false",
                    "last_error": "生成结果为空",
                    "last_failure_time": datetime.now().isoformat()
                }
                self.redis.hset(summary_generation_status_key, mapping=failure_status)
                return "汇总生成中，请稍候..."
            else:
                logger.info("[LIFE_DATA] ✅ AI汇总生成成功")
                # 记录成功状态
                success_status = {
                    "last_success": "true",
                    "last_success_time": datetime.now().isoformat(),
                    "last_error": ""  # 清除错误信息
                }
                self.redis.hset(summary_generation_status_key, mapping=success_status)
                
                # 只有在成功生成后才更新比较基准
                self.redis.set(prev_past_micro_experiences_key, current_exp_json, ex=86400)
                return summarized_story
                
        except Exception as e:
            logger.error(f"❌ AI汇总生成失败: {str(e)}")
            # 记录失败状态，但不更新数据基准
            failure_status = {
                "last_success": "false", 
                "last_error": str(e),
                "last_failure_time": datetime.now().isoformat()
            }
            self.redis.hset(summary_generation_status_key, mapping=failure_status)
            return f"汇总生成失败，将在下次重试 (错误: {str(e)[:50]}...)"

    async def fetch_and_store_today_data(self):
        """获取并存储当天生活系统数据到Redis"""
        try:
            # 获取当前日期和时间
            today = date.today()
            date_str = today.strftime("%Y-%m-%d")
            current_time = datetime.now().strftime("%H:%M")

            logger.info(f"[LIFE_DATA] 🚀 开始获取{date_str}的生活系统数据")
            logger.info(f"[LIFE_DATA] 📅 目标日期: {date_str}, 当前时间: {current_time}")

            # 初始化查询对象
            query = LifeSystemQuery(today)

            # 获取当天的大事件
            major_event = await query.get_major_event_info()

            # 获取当天的日程
            daily_schedule = await query.get_daily_schedule_info()

            # 获取当前时刻的微观经历
            current_micro_experience = None
            schedule_item = None  # 初始化schedule_item变量
            logger.info("[LIFE_DATA] 🔍 获取当前时刻的日程项")

            # 先获取当前时刻的日程项
            if (
                daily_schedule
                and "schedule_data" in daily_schedule
                and "schedule_items" in daily_schedule["schedule_data"]
            ):
                logger.info("[LIFE_DATA] 🔍 遍历日程项")
                for item in daily_schedule["schedule_data"]["schedule_items"]:
                    logger.info(f"[LIFE_DATA] 日程项开始时间: {item.get('start_time')}")
                    logger.info(f"[LIFE_DATA] 日程项结束时间: {item.get('end_time')}")
                    item_start_time = item["start_time"]
                    item_end_time = item["end_time"]
                    item_start_time_obj = datetime.strptime(
                        item_start_time, "%H:%M"
                    ).time()
                    item_end_time_obj = datetime.strptime(item_end_time, "%H:%M").time()
                    current_time_obj = datetime.strptime(current_time, "%H:%M").time()
                    if item_start_time_obj <= current_time_obj <= item_end_time_obj:
                        schedule_item = item
                        logger.info(f"[LIFE_DATA] 匹配的日程项: {schedule_item}")
                        break  # 找到第一个匹配项即可退出循环

            if schedule_item:
                logger.info(f"[LIFE_DATA] 找到匹配的日程项: {schedule_item}")
                # 获取该日程项的微观经历
                logger.info("[LIFE_DATA] 🔍 获取该日程项的微观经历")
                schedule_item_id = schedule_item.get("id")
                if schedule_item_id:
                    # 获取该日程项在当前时刻的微观经历
                    logger.info("[LIFE_DATA] 🔍 获取该日程项在当前时刻的微观经历")
                    current_micro_experience = await query.get_micro_experience_at_time(
                        schedule_item_id, current_time
                    )

            # 获取当前时刻之前的所有微观经历（不包括当前时刻）
            all_past_micro_experiences = []
            if (
                daily_schedule
                and "schedule_data" in daily_schedule
                and "schedule_items" in daily_schedule["schedule_data"]
            ):
                logger.info("[LIFE_DATA] 🔍 获取当前时刻之前所有微观经历")
                for item in daily_schedule["schedule_data"]["schedule_items"]:
                    item_time = item["start_time"]
                    item_start_time_obj = datetime.strptime(item_time, "%H:%M").time()
                    current_time_obj = datetime.strptime(current_time, "%H:%M").time()
                    if (
                        item_start_time_obj <= current_time_obj
                    ):  # 只包括当前时刻及之前的日程项
                        # logger.info("[LIFE_DATA] 🔍 日程项开始时间小于等于当前时间!!!!!")
                        schedule_item_id = item.get("id")
                        if schedule_item_id:
                            # 获取该日程项的所有微观经历
                            micro_experiences = (
                                await query.get_micro_experiences_for_schedule_item(
                                    schedule_item_id
                                )
                            )
                            # logger.info(
                            #     f"获取该日程项的所有微观经历: {micro_experiences}"
                            # )
                            if micro_experiences:
                                # 过滤出在当前时刻之前结束的微观经历
                                for exp in micro_experiences:
                                    for exp_item in exp.get("experiences", []):
                                        # 确保经历有结束时间
                                        if "end_time" in exp_item:
                                            # 只包括在当前时刻之前结束的经历
                                            if exp_item["end_time"] <= current_time:
                                                all_past_micro_experiences.append(
                                                    exp_item
                                                )

            # Redis 键定义
            prev_past_micro_experiences_key = f"life_system:prev_past_micro_experiences:{date_str}"
            summary_generation_status_key = f"life_system:summary_status:{date_str}"
            
            # 获取之前存储的数据和状态
            prev_past_micro_experiences = self.redis.get(prev_past_micro_experiences_key)
            summary_status = self.redis.hgetall(summary_generation_status_key)

            # 序列化当前经历用于比较
            current_exp_json = (
                json.dumps(
                    all_past_micro_experiences, sort_keys=True, ensure_ascii=False
                )
                if all_past_micro_experiences
                else ""
            )

            logger.info(f"[LIFE_DATA] prev: ...{prev_past_micro_experiences[-100:] if prev_past_micro_experiences else 'None'}")
            logger.info(f"[LIFE_DATA] curr: ...{current_exp_json[-100:]}")
            logger.info(f"[LIFE_DATA] summary_status: {summary_status}")

            # 检查是否需要重新生成汇总
            data_changed = prev_past_micro_experiences != current_exp_json
            last_generation_success = summary_status.get("last_success", "false") == "true"
            last_attempt_data = summary_status.get("last_attempt_data", "")
            
            if not current_exp_json:
                # 没有当前经历数据
                summarized_past_micro_experiences_story = ""
                # 清理状态
                self.redis.delete(summary_generation_status_key)
                self.redis.set(prev_past_micro_experiences_key, current_exp_json, ex=86400)
                
            elif data_changed:
                # 数据有变化，无论之前是否成功都需要重新生成
                logger.info("[LIFE_DATA] 发现数据差异，需要重新生成汇总")
                summarized_past_micro_experiences_story = await self._generate_summary_with_status_tracking(
                    all_past_micro_experiences, 
                    current_exp_json,
                    prev_past_micro_experiences_key,
                    summary_generation_status_key,
                    date_str
                )
                
            elif not last_generation_success and last_attempt_data == current_exp_json:
                # 数据没变但上次生成失败，需要重试
                logger.info("[LIFE_DATA] 数据未变化但上次生成失败，进行重试")
                summarized_past_micro_experiences_story = await self._generate_summary_with_status_tracking(
                    all_past_micro_experiences,
                    current_exp_json, 
                    prev_past_micro_experiences_key,
                    summary_generation_status_key,
                    date_str
                )
                
            else:
                # 数据没变化且之前生成成功，使用现有汇总
                logger.info("[LIFE_DATA] 数据无变化且之前生成成功，使用现有汇总")
                main_data = self.redis.hgetall(f"life_system:{date_str}")
                existing_story = main_data.get("summarized_past_micro_experiences_story", "")
                
                if not existing_story or existing_story in ["", "没有之前的经历，今天可能才刚刚开始。"]:
                    # 没有有效汇总但状态显示成功，可能是数据丢失，重新生成
                    logger.info("[LIFE_DATA] 状态显示成功但未找到有效汇总，重新生成")
                    summarized_past_micro_experiences_story = await self._generate_summary_with_status_tracking(
                        all_past_micro_experiences,
                        current_exp_json,
                        prev_past_micro_experiences_key, 
                        summary_generation_status_key,
                        date_str
                    )
                else:
                    # 解析现有汇总
                    if existing_story.startswith('"'):
                        try:
                            summarized_past_micro_experiences_story = json.loads(existing_story)
                        except json.JSONDecodeError:
                            summarized_past_micro_experiences_story = existing_story
                    else:
                        summarized_past_micro_experiences_story = existing_story

            # 存储到Redis
            redis_key = f"life_system:{date_str}"
            data = {
                "major_event": (
                    json.dumps(major_event, ensure_ascii=False)
                    if major_event
                    else "现在没有什么大事件，在平静的龙门。"
                ),
                "daily_schedule": (
                    json.dumps(daily_schedule, ensure_ascii=False)
                    if daily_schedule
                    else "当日没有日程。"
                ),
                "current_micro_experience": (
                    json.dumps(current_micro_experience, ensure_ascii=False)
                    if current_micro_experience
                    else "现在没有事件。"
                ),
                "past_micro_experiences": (
                    json.dumps(all_past_micro_experiences, ensure_ascii=False)
                    if all_past_micro_experiences
                    else "没有之前的经历，今天可能才刚刚开始。"
                ),
                "summarized_past_micro_experiences_story": (
                    json.dumps(
                        summarized_past_micro_experiences_story, ensure_ascii=False
                    )
                    if summarized_past_micro_experiences_story
                    else "没有之前的经历，今天可能才刚刚开始。"
                ),
            }

            # 使用HSET存储哈希数据
            self.redis.hset(redis_key, mapping=data)
            # 设置24小时过期时间
            self.redis.expire(redis_key, 86400)

            logger.info(f"[LIFE_DATA] 生活系统数据已存储到Redis: {redis_key}")

            return True

        except Exception as e:
            import traceback

            logger.error(f"获取和存储生活数据失败: {str(e)}")
            logger.error(traceback.format_exc())
            return False


# 单例实例
life_data_service = LifeDataService()


async def main():
    """直接运行入口"""
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 执行数据获取和存储
    result = await life_data_service.fetch_and_store_today_data()
    if result:
        logger.info("[LIFE_DATA] ✅ 生活系统数据获取和存储成功")
    else:
        logger.error("❌ 生活系统数据获取和存储失败")

    # 打印存储在Redis中的数据和状态
    today = datetime.date.today().strftime("%Y-%m-%d")
    redis_key = f"life_system:{today}"
    status_key = f"life_system:summary_status:{today}"
    
    stored_data = redis_client.hgetall(redis_key)
    status_data = redis_client.hgetall(status_key)

    if stored_data:
        logger.info(f"[LIFE_DATA] 🔍 Redis存储的数据 ({redis_key}):")
        for key, value in stored_data.items():
            # 尝试解析JSON值
            try:
                parsed_value = json.loads(value)
                logger.info(
                    f"{key}: {json.dumps(parsed_value, indent=2, ensure_ascii=False)}"
                )
            except:
                logger.info(f"[LIFE_DATA] {key}: {value}")
    else:
        logger.warning(f"ℹ️ 未找到Redis键: {redis_key}")
        
    if status_data:
        logger.info(f"[LIFE_DATA] 📊 生成状态信息 ({status_key}):")
        for key, value in status_data.items():
            logger.info(f"[LIFE_DATA] {key}: {value}")
    else:
        logger.info("[LIFE_DATA] 📊 未找到生成状态信息")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
    