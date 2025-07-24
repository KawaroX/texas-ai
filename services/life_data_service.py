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

    async def fetch_and_store_today_data(self):
        """获取并存储当天生活系统数据到Redis"""
        try:
            # 获取当前日期和时间
            today = date.today()
            date_str = today.strftime("%Y-%m-%d")
            current_time = datetime.now().strftime("%H:%M")

            logger.info(f"🚀 开始获取{date_str}的生活系统数据")
            logger.info(f"📅 目标日期: {date_str}, 当前时间: {current_time}")

            # 初始化查询对象
            query = LifeSystemQuery(today)

            # 获取当天的大事件
            major_event = await query.get_major_event_info()

            # 获取当天的日程
            daily_schedule = await query.get_daily_schedule_info()

            # 获取当前时刻的微观经历
            current_micro_experience = None
            schedule_item = None  # 初始化schedule_item变量
            logger.info("🔍 获取当前时刻的日程项")

            # 先获取当前时刻的日程项
            if (
                daily_schedule
                and "schedule_data" in daily_schedule
                and "schedule_items" in daily_schedule["schedule_data"]
            ):
                logger.info("🔍 遍历日程项")
                for item in daily_schedule["schedule_data"]["schedule_items"]:
                    logger.info(f"日程项开始时间: {item.get('start_time')}")
                    logger.info(f"日程项结束时间: {item.get('end_time')}")
                    item_start_time = item["start_time"]
                    item_end_time = item["end_time"]
                    item_start_time_obj = datetime.strptime(
                        item_start_time, "%H:%M"
                    ).time()
                    item_end_time_obj = datetime.strptime(item_end_time, "%H:%M").time()
                    current_time_obj = datetime.strptime(current_time, "%H:%M").time()
                    if item_start_time_obj <= current_time_obj <= item_end_time_obj:
                        schedule_item = item
                        logger.info(f"匹配的日程项: {schedule_item}")
                        break  # 找到第一个匹配项即可退出循环

            if schedule_item:
                logger.info(f"找到匹配的日程项: {schedule_item}")
                # 获取该日程项的微观经历
                logger.info("🔍 获取该日程项的微观经历")
                schedule_item_id = schedule_item.get("id")
                if schedule_item_id:
                    # 获取该日程项在当前时刻的微观经历
                    logger.info("🔍 获取该日程项在当前时刻的微观经历")
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
                logger.info("🔍 获取当前时刻之前所有微观经历")
                for item in daily_schedule["schedule_data"]["schedule_items"]:
                    item_time = item["start_time"]
                    item_start_time_obj = datetime.strptime(item_time, "%H:%M").time()
                    current_time_obj = datetime.strptime(current_time, "%H:%M").time()
                    if (
                        item_start_time_obj <= current_time_obj
                    ):  # 只包括当前时刻及之前的日程项
                        logger.info("🔍 日程项开始时间小于等于当前时间!!!!!")
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
                                # result = json.dumps(all_past_micro_experiences, ensure_ascii=False)
                                # logger.info(f"获取当前时刻之前所有微观经历: {result}")

            # 检查与之前存储的差异
            prev_past_micro_experiences_key = (
                f"life_system:prev_past_micro_experiences:{date_str}"
            )
            prev_past_micro_experiences = self.redis.get(
                prev_past_micro_experiences_key
            )

            # 序列化当前经历用于比较
            current_exp_json = (
                json.dumps(
                    all_past_micro_experiences, sort_keys=True, ensure_ascii=False
                )
                if all_past_micro_experiences
                else ""
            )

            # logger.info(f"prev: ...{prev_past_micro_experiences[-100:]}")
            # logger.info(f"curr: ...{current_exp_json[-100:]}")

            IS_DIFF = False
            if prev_past_micro_experiences != current_exp_json:
                IS_DIFF = True
                logger.info("发现差异")
            else:
                logger.info("无差异")

            # 仅当有差异时才重新汇总
            if all_past_micro_experiences and IS_DIFF:
                # 汇总过去的微观经历
                summarized_past_micro_experiences_story = (
                    await summarize_past_micro_experiences(all_past_micro_experiences)
                )
                # 存储当前版本用于后续比较
                self.redis.set(
                    prev_past_micro_experiences_key, current_exp_json, ex=86400
                )
            elif all_past_micro_experiences:
                # 从主哈希获取之前汇总的故事
                main_data = self.redis.hgetall(f"life_system:{date_str}")
                prev_story = main_data.get(
                    "summarized_past_micro_experiences_story", ""
                )

                # 如果找到且是有效JSON，则解析
                if prev_story and prev_story.startswith('"'):
                    try:
                        summarized_past_micro_experiences_story = json.loads(prev_story)
                    except json.JSONDecodeError:
                        summarized_past_micro_experiences_story = prev_story
                else:
                    summarized_past_micro_experiences_story = prev_story
            else:
                summarized_past_micro_experiences_story = ""

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

            logger.info(f"生活系统数据已存储到Redis: {redis_key}")

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
        logger.info("✅ 生活系统数据获取和存储成功")
    else:
        logger.error("❌ 生活系统数据获取和存储失败")

    # 打印存储在Redis中的数据
    today = datetime.date.today().strftime("%Y-%m-%d")
    redis_key = f"life_system:{today}"
    stored_data = redis_client.hgetall(redis_key)

    if stored_data:
        logger.info(f"🔍 Redis存储的数据 ({redis_key}):")
        for key, value in stored_data.items():
            # 尝试解析JSON值
            try:
                parsed_value = json.loads(value)
                logger.info(
                    f"{key}: {json.dumps(parsed_value, indent=2, ensure_ascii=False)}"
                )
            except:
                logger.info(f"{key}: {value}")
    else:
        logger.warning(f"ℹ️ 未找到Redis键: {redis_key}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
