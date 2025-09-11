import asyncio
import json
import os
from datetime import date, timedelta
from utils.logging_config import get_logger

logger = get_logger(__name__)
import uuid
from typing import Optional
from datetime import datetime
import redis  # 添加 Redis 支持

from services.ai_service import (
    get_weather_info,
    generate_daily_schedule,
    generate_major_event,
    generate_micro_experiences,
)
from utils.postgres_service import (
    insert_daily_schedule,
    get_daily_schedule_by_date,
    update_daily_schedule,
    insert_major_event,
    get_major_event_by_date,  # 新增
    insert_micro_experience,
    get_micro_experiences_by_daily_schedule_id,
    get_micro_experiences_by_related_item_id,  # 新增
)


# 定义生成内容存储的文件夹
GENERATED_CONTENT_DIR = "generated_content"


async def generate_and_store_daily_life(target_date: date):
    """
    生成并存储指定日期的德克萨斯生活日程。
    包括获取天气、生成日程、存储到数据库和文件。
    """
    date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"[daily_life] 开始生成每日日程: {date_str}")

    # 1. 获取天气信息
    weather = get_weather_info(date_str)
    logger.debug(f"[daily_life] 天气信息: {weather}")

    # 2. 判断工作日/周末 (简化逻辑，实际可根据节假日等更复杂判断)
    day_type = "weekend" if target_date.weekday() >= 5 else "weekday"
    logger.debug(f"[daily_life] 日期类型: {day_type}")

    # 3. 检查大事件
    is_in_major_event = False
    major_event_context = None
    logger.debug(f"[daily_life] 检查是否处于大事件: {date_str}")

    # 检查数据库是否已存在包含目标日期的大事件
    major_event_context = get_major_event_by_date(date_str)

    if major_event_context:
        is_in_major_event = True
    else:
        logger.debug("[daily_life] 未检测到已存在的大事件")

    # 如果没有大事件，则根据0.028概率决定是否生成新的大事件
    if not is_in_major_event:
        import random

        gen_prob = 0.028  # 0.028
        rand_val = random.random()

        if rand_val < gen_prob:  # 0.028概率生成大事件
            # 正态分布生成持续天数 (μ=4, σ=2)，范围1-7天

            duration_days = max(1, min(7, int(random.gauss(4, 2))))
            logger.debug(f"[daily_life] 大事件持续天数: {duration_days}天 (μ=4, σ=2)")

            # 随机选择事件类型
            event_types = ["出差任务", "特殊快递", "培训学习", "个人事务", "生病"]
            weights = [0.4, 0.3, 0.15, 0.1, 0.05]  # 事件类型概率权重
            event_type = random.choices(event_types, weights=weights)[0]
            logger.debug(f"[daily_life] 选择事件类型: {event_type} (权重: {weights})")

            # 生成大事件
            end_date = target_date + timedelta(days=duration_days - 1)
            major_event_context = await generate_and_store_major_event(
                target_date, end_date, event_type
            )
            is_in_major_event = True
            logger.debug(
                f"[daily_life] 新大事件生成完成: {event_type}, 持续{duration_days}天"
            )

    # 如果处于大事件中，但未获取上下文，尝试从数据库获取
    if is_in_major_event and not major_event_context:
        logger.warning("大事件上下文缺失，尝试从数据库获取...")
        major_event_context = get_major_event_by_date(date_str)
        if not major_event_context:
            logger.warning("数据库中也未找到大事件详情，使用默认值")
            major_event_context = {
                "event_title": "默认大事件",
                "event_type": "默认类型",
                "main_objective": "默认目标",
            }
    if is_in_major_event:
        weather += "以上为随机天气情况，仅供参考，以大事件情况为准。"
    else:
        logger.debug("[daily_life] 大事件状态: 不存在")

    # 4. 调用AI生成每日日程
    logger.debug("[daily_life] 调用 AI 生成每日日程")
    daily_schedule_data = await generate_daily_schedule(
        date=date_str,
        day_type=day_type,
        weather=weather,
        is_in_major_event=is_in_major_event,
        major_event_context=major_event_context,
        special_flags=[],
    )

    if "error" in daily_schedule_data:
        logger.error(f"AI生成日程失败: {daily_schedule_data['error']}")
        return None

    logger.debug("[daily_life] AI日程生成成功")

    # 5. 存储到数据库
    logger.debug("[daily_life] 存储日程到数据库")
    try:
        # 检查该日期是否已存在日程，如果存在则更新，否则插入
        existing_schedule = get_daily_schedule_by_date(date_str)
        if existing_schedule:
            schedule_id = existing_schedule["id"]
            update_daily_schedule(
                schedule_id=schedule_id,
                schedule_data=daily_schedule_data,
                weather=weather,
                is_in_major_event=is_in_major_event,
                major_event_id=(
                    major_event_context["id"] if major_event_context else None
                ),
            )
            logger.debug(f"[daily_life] 日程已更新 (ID: {schedule_id})")
        else:
            schedule_id = insert_daily_schedule(
                date=date_str,
                schedule_data=daily_schedule_data,
                weather=weather,
                is_in_major_event=is_in_major_event,
                major_event_id=(
                    major_event_context["id"] if major_event_context else None
                ),
            )
            logger.debug(f"[daily_life] 日程已插入 (ID: {schedule_id})")

        daily_schedule_data["id"] = str(schedule_id)  # 将数据库生成的ID添加到数据中
    except Exception as e:
        logger.error(f"存储日程到数据库失败: {e}")
        return None

    # 6. 存储到文件
    logger.debug("[daily_life] 存储日程到文件")
    os.makedirs(GENERATED_CONTENT_DIR, exist_ok=True)
    file_path = os.path.join(GENERATED_CONTENT_DIR, f"daily_schedule_{date_str}.json")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(daily_schedule_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"[daily_life] 日程已保存到文件: {file_path}")
    except Exception as e:
        logger.error(f"保存日程到文件失败: {e}")

    # 7. 生成并存储微观经历
    if "schedule_items" in daily_schedule_data:
        successful_experiences = 0

        # 获取之前的经历摘要（简化实现）
        previous_experiences_summary = None

        for index, item in enumerate(daily_schedule_data["schedule_items"]):
            # 设置当前时间为项目开始时间（如需使用可在后续逻辑中引用）

            micro_experiences = await generate_and_store_micro_experiences(
                schedule_item=item,
                current_date=target_date,
                previous_experiences=previous_experiences_summary,
                major_event_context=major_event_context,
                schedule_id=schedule_id,  # 传入每日计划的ID
            )

            if micro_experiences:
                successful_experiences += 1
                # 更新经历摘要（使用生成的经历内容）
                exp_summaries = [
                    f"{exp.get('start_time', '')}-{exp.get('end_time', '')}: {exp.get('content', '')[:50]}..."
                    for exp in micro_experiences
                ]
                previous_experiences_summary = exp_summaries

    else:
        logger.warning("日程中没有可生成微观经历的项目")

    logger.info(f"[daily_life] 生成完成: {date_str} 每日日程与存储")

    # 8. 使用专用函数收集需要交互的微观经历
    logger.debug("[daily_life] 开始收集需要主动交互的微观经历")
    await collect_interaction_experiences(target_date)

    return daily_schedule_data


async def _store_enhanced_interaction_data(target_date: date, micro_experiences: list, daily_schedule: dict, redis_client):
    """
    存储增强的交互数据，包含完整的微观经历信息、schedule_item数据和背景信息
    """
    date_str = target_date.strftime("%Y-%m-%d")
    enhanced_redis_key = f"interaction_needed_enhanced:{date_str}"
    logger.debug(f"[interactions] 开始存储增强交互数据: {enhanced_redis_key}")
    
    # 获取大事件背景信息（可能为None）
    major_event_context = get_major_event_by_date(date_str)
    
    # 获取schedule_items映射，用于快速查找
    schedule_items_map = {}
    if daily_schedule.get("schedule_data") and daily_schedule["schedule_data"].get("schedule_items"):
        for item in daily_schedule["schedule_data"]["schedule_items"]:
            item_id = item.get("id")
            if item_id:
                schedule_items_map[item_id] = item
    
    # 辅助函数：时间转时间戳
    def time_to_timestamp(date_obj: date, time_str: str) -> float:
        dt_str = f"{date_obj.strftime('%Y-%m-%d')} {time_str}"
        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt_obj.timestamp()
    
    enhanced_interactions = []
    
    # 处理每个微观经历记录
    for record in micro_experiences:
        experiences = record.get("experiences", [])
        related_item_id = record.get("related_item_id")
        
        # 获取关联的schedule_item
        related_schedule_item = schedule_items_map.get(related_item_id) if related_item_id else None
        
        for exp in experiences:
            if exp.get("need_interaction") is True:
                # 构建增强数据对象
                enhanced_exp = {
                    # 原有微观经历数据
                    "id": exp.get("id"),
                    "start_time": exp.get("start_time"),
                    "end_time": exp.get("end_time"),
                    "content": exp.get("content"),
                    "emotions": exp.get("emotions"),
                    "thoughts": exp.get("thoughts"),
                    "need_interaction": exp.get("need_interaction"),
                    "interaction_content": exp.get("interaction_content"),
                    
                    # 关联的schedule_item数据（增强信息）
                    "schedule_context": {
                        "item_id": related_item_id,
                        "title": related_schedule_item.get("title") if related_schedule_item else None,
                        "location": related_schedule_item.get("location") if related_schedule_item else None,
                        "description": related_schedule_item.get("description") if related_schedule_item else None,
                        "companions": related_schedule_item.get("companions", []) if related_schedule_item else [],
                        "category": related_schedule_item.get("category") if related_schedule_item else None,
                    },
                    
                    # 大事件背景信息
                    "major_event_context": major_event_context,
                    
                    # 派生信息
                    "date": date_str,
                    "time_period": _get_time_period(exp.get("start_time")),
                    "enhanced_data_version": "1.0",
                }
                
                enhanced_interactions.append(enhanced_exp)
    
    # 存储到Redis Sorted Set
    for enhanced_exp in enhanced_interactions:
        try:
            score = time_to_timestamp(target_date, enhanced_exp["start_time"])
            redis_client.zadd(enhanced_redis_key, {json.dumps(enhanced_exp, ensure_ascii=False): score})
        except Exception as e:
            logger.warning(f"存储单个增强交互数据失败: {e}")
    
    # 设置过期时间
    redis_client.expire(enhanced_redis_key, 86400)  # 24小时过期
    logger.info(f"[interactions] 增强交互数据已存储: {enhanced_redis_key} (共 {len(enhanced_interactions)} 条)")


def _get_time_period(time_str: str) -> str:
    """根据时间字符串返回时间段描述"""
    if not time_str:
        return "unknown"
    
    try:
        hour = int(time_str.split(":")[0])
        if 5 <= hour < 9:
            return "early_morning"
        elif 9 <= hour < 12:
            return "morning"
        elif 12 <= hour < 14:
            return "noon"
        elif 14 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 21:
            return "evening"
        else:
            return "night"
    except:
        return "unknown"


async def collect_interaction_experiences(target_date: date):
    """
    单独收集需要交互的微观经历并存入Redis
    """
    date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"[interactions] 开始收集需要主动交互的微观经历: {date_str}")

    try:
        # 从数据库获取当日日程 ID
        daily_schedule = get_daily_schedule_by_date(date_str)
        if not daily_schedule:
            logger.warning(f"未找到 {date_str} 的日程数据")
            return False

        schedule_id = daily_schedule["id"]

        # 查询关联的微观经历
        micro_experiences = get_micro_experiences_by_daily_schedule_id(schedule_id)
        if not micro_experiences:
            logger.debug("[interactions] 当日没有微观经历数据")
            return False

        # 筛选需要交互的条目
        interaction_needed = []
        for record in micro_experiences:
            experiences = record.get("experiences", [])
            for exp in experiences:
                if exp.get("need_interaction") is True:
                    interaction_needed.append(exp)


        # 存储到 Redis
        from utils.redis_manager import get_redis_client
        r = get_redis_client()
        redis_key = f"interaction_needed:{date_str}"

        # 辅助函数：将 HH:MM 格式的时间字符串转换为当天的 Unix 时间戳
        def time_to_timestamp(date_obj: date, time_str: str) -> float:
            dt_str = f"{date_obj.strftime('%Y-%m-%d')} {time_str}"
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            return dt_obj.timestamp()

        # 存储新数据到 Sorted Set
        # 使用 end_time 的 Unix 时间戳作为 score
        # 如果 Sorted Set 中已存在相同的 member，zadd 会更新其 score
        # 如果每天生成新的 key，则不需要删除旧数据
        for exp in interaction_needed:
            try:
                score = time_to_timestamp(target_date, exp["start_time"])
                r.zadd(redis_key, {json.dumps(exp, ensure_ascii=False): score})
            except KeyError as ke:
                logger.error(f"缺少时间字段，无法添加到 Sorted Set: {exp} - {ke}")
            except Exception as add_e:
                logger.error(f"添加到 Redis Sorted Set 失败: {exp} - {add_e}")

        # 设置 24 小时过期
        r.expire(redis_key, 86400)
        logger.info(f"[interactions] 已存储到 Redis: {redis_key} (24h 过期)")
        
        # 🆕 额外存储增强数据（失败不影响主流程）
        try:
            await _store_enhanced_interaction_data(target_date, micro_experiences, daily_schedule, r)
        except Exception as enhanced_error:
            logger.warning(f"存储增强交互数据失败（不影响主流程）: {enhanced_error}")
        
        return True

    except Exception as e:
        logger.error(f"收集交互微观经历失败: {str(e)}", exc_info=True)
        return False


async def generate_and_store_major_event(
    start_date: date, end_date: date, event_type: str
):
    """
    生成并存储大事件。
    """
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    duration_days = (end_date - start_date).days + 1
    logger.info(f"[major_event] 开始生成大事件: {start_date_str} -> {end_date_str}")

    # 1. 获取真实天气
    import random

    WORLD_CITIES = [
        (40.71, -74.01),
        (51.51, -0.13),
        (48.86, 2.35),
        (52.52, 13.41),
        (35.68, 139.76),
        (37.57, 126.98),
        (13.75, 100.50),
        (1.35, 103.82),
        (-33.87, 151.21),
        (55.75, 37.62),
        (30.05, 31.25),
        (-1.29, 36.82),
        (-23.55, -46.63),
        (-34.61, -58.38),
        (43.65, -79.38),
        (19.43, -99.13),
        (41.01, 28.97),
        (25.27, 55.30),
        (19.07, 72.88),
        (-36.85, 174.76),
    ]

    # 统一选择一个地点（纬度, 经度），并转为字符串
    lat, lon = random.choice(WORLD_CITIES)
    selected_location = f"{lat:.2f},{lon:.2f}"
    logger.debug(f"[major_event] 天气模拟地点: {selected_location}")

    weather_forecast = {}
    for i in range(duration_days):
        current_date = start_date + timedelta(days=i)
        weather_forecast[current_date.strftime("%Y-%m-%d")] = get_weather_info(
            current_date.strftime("%Y-%m-%d"), location=selected_location
        )

    logger.debug(f"[major_event] 模拟天气预报: {weather_forecast}")

    # 2. 调用AI生成大事件
    logger.debug("[major_event] 调用 AI 生成大事件")
    major_event_data = await generate_major_event(
        duration_days=duration_days,
        event_type=event_type,
        start_date=start_date_str,
        weather_forecast=weather_forecast,
    )

    if "error" in major_event_data:
        logger.error(f"AI生成大事件失败: {major_event_data['error']}")
        return None

    logger.debug("[major_event] AI 大事件生成成功")

    # 3. 存储到数据库
    logger.debug("[major_event] 存储大事件到数据库")
    try:
        event_id = insert_major_event(
            start_date=start_date_str,
            end_date=end_date_str,
            duration_days=duration_days,
            main_content=major_event_data.get("main_objective", "无主要内容"),
            daily_summaries=major_event_data.get("daily_plans", []),
            event_type=event_type,
            status="active",  # 假设生成后即为活跃状态
        )
        logger.debug(f"[major_event] 大事件已插入 (ID: {event_id})")
        major_event_data["id"] = str(event_id)  # 将数据库生成的ID添加到数据中
    except Exception as e:
        logger.error(f"存储大事件到数据库失败: {e}")
        return None

    # 4. 存储到文件
    logger.debug("[major_event] 存储大事件到文件")
    os.makedirs(GENERATED_CONTENT_DIR, exist_ok=True)
    file_path = os.path.join(
        GENERATED_CONTENT_DIR,
        f"major_event_{major_event_data.get('event_id', uuid.uuid4())}.json",
    )
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(major_event_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"[major_event] 大事件已保存到文件: {file_path}")
    except Exception as e:
        logger.error(f"保存大事件到文件失败: {e}")

    logger.info("[major_event] 大事件生成与存储完成")
    return major_event_data


async def generate_and_store_micro_experiences(
    schedule_item: dict,
    current_date: date,
    schedule_id: str,
    previous_experiences: Optional[list] = None,
    major_event_context: Optional[dict] = None,
):
    """
    为单个日程项目生成并存储多个微观经历项（5-30分钟颗粒度）
    """
    logger.info(
        f"[micro_exp] 开始为日程项生成微观经历: {schedule_item.get('title', '未知项目')}"
    )

    # 1. 调用AI生成多个微观经历项
    logger.debug("[micro_exp] 调用 AI 生成微观经历（5-30 分钟）")
    micro_experiences = await generate_micro_experiences(
        schedule_item=schedule_item,
        current_date=current_date.strftime("%Y-%m-%d"),
        previous_experiences=previous_experiences,
        major_event_context=major_event_context,
    )

    if not micro_experiences or any("error" in exp for exp in micro_experiences):
        errors = [exp["error"] for exp in micro_experiences if "error" in exp]
        logger.error(f"AI生成微观经历失败: {', '.join(errors)}")
        return None

    logger.debug(f"[micro_exp] AI 生成成功，数量: {len(micro_experiences)}")

    # 2. 存储到数据库
    logger.debug("[micro_exp] 存储微观经历项到数据库")
    try:
        experience_id = insert_micro_experience(
            date=current_date.strftime("%Y-%m-%d"),
            daily_schedule_id=schedule_id,
            related_item_id=schedule_item.get("id"),
            experiences=micro_experiences,
        )
        logger.debug(f"[micro_exp] 微观经历已存储 (ID: {experience_id})")
        successful_items = len(micro_experiences)
    except Exception as e:
        logger.error(f"存储微观经历失败: {e}")
        successful_items = 0


    # 3. 存储到文件
    logger.debug("[micro_exp] 存储微观经历到文件")
    os.makedirs(GENERATED_CONTENT_DIR, exist_ok=True)
    title = schedule_item.get("title", "unknown").replace(" ", "_")
    date_str = current_date.strftime("%Y-%m-%d")
    file_path = os.path.join(
        GENERATED_CONTENT_DIR, f"micro_experiences_{date_str}_{title}.json"
    )
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": current_date.strftime("%Y-%m-%d"),
                    "schedule_item_id": schedule_item.get("id", ""),
                    "items": micro_experiences,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.debug(f"[micro_exp] 微观经历项已保存到文件: {file_path}")
    except Exception as e:
        logger.error(f"保存微观经历项到文件失败: {e}")

    logger.info("[micro_exp] 微观经历项生成与存储完成")
    return micro_experiences


# async def get_and_summarize_experiences(
#     daily_schedule_id: str, summary_type: str = "整体"
# ):
#     """
#     从数据库获取微观经历并进行总结。
#     """
#     logger.info(f"--- 正在获取并总结每日计划 {daily_schedule_id} 的微观经历 ---")
#     experiences = get_micro_experiences_by_daily_schedule_id(daily_schedule_id)
#     if not experiences:
#         logger.info("没有找到微观经历。")
#         return "没有找到相关微观经历。"

#     logger.info(f"找到 {len(experiences)} 条微观经历，正在总结...")
#     summary = await summarize_experiences(experiences, summary_type)
#     logger.info("总结完成。")
#     return summary


# 示例用法 (在实际应用中，这些会通过API或调度器触发)
class LifeSystemQuery:
    def __init__(self, target_date: Optional[date] = None):
        self.target_date = target_date if target_date else date.today()
        self.date_str = self.target_date.strftime("%Y-%m-%d")

    async def is_in_major_event(self) -> bool:
        major_event = get_major_event_by_date(self.date_str)
        return major_event is not None

    async def get_major_event_info(self) -> Optional[dict]:
        return get_major_event_by_date(self.date_str)

    async def get_major_event_daily_info(self) -> Optional[dict]:
        major_event = await self.get_major_event_info()
        if major_event and "daily_summaries" in major_event:
            # daily_summaries 字段是一个JSONB类型，存储的是一个列表，每个元素是一个字典，包含日期和内容
            # 遍历 daily_summaries 列表，查找与当前日期匹配的每日摘要
            for daily_summary in major_event["daily_summaries"]:
                if daily_summary.get("date") == self.date_str:
                    return daily_summary
        return None

    async def get_daily_schedule_info(self) -> Optional[dict]:
        return get_daily_schedule_by_date(self.date_str)

    async def get_schedule_item_at_time(self, target_time: str) -> Optional[dict]:
        daily_schedule = await self.get_daily_schedule_info()
        if not daily_schedule:
            logger.debug("No daily schedule found.")
            return None

        if not (
            "schedule_data" in daily_schedule
            and "schedule_items" in daily_schedule["schedule_data"]
        ):
            logger.debug("Daily schedule has no'schedule_data' or 'schedule_items'.")
            return None

        try:
            target_time_obj = datetime.strptime(target_time, "%H:%M").time()
        except ValueError:
            logger.error(f"Invalid target_time format: {target_time}")
            return None

        for item in daily_schedule["schedule_data"]["schedule_items"]:
            item_start_time_str = item.get("start_time")
            item_end_time_str = item.get("end_time")

            if not (item_start_time_str and item_end_time_str):
                logger.warning(f"Schedule item missing start_time or end_time: {item}")
                continue

            try:
                item_start_time_obj = datetime.strptime(
                    item_start_time_str, "%H:%M"
                ).time()
                item_end_time_obj = datetime.strptime(item_end_time_str, "%H:%M").time()
            except ValueError:
                logger.error(f"Invalid time format in schedule item: {item}")
                continue

            if item_start_time_obj <= target_time_obj < item_end_time_obj:
                logger.debug(f"Matched schedule item: {item.get('title')}")
                return item

        logger.debug("No matching schedule item found for current time.")
        return None

    async def get_micro_experiences_for_schedule_item(
        self, schedule_item_id: str
    ) -> Optional[list]:
        return get_micro_experiences_by_related_item_id(schedule_item_id)

    async def get_micro_experience_at_time(
        self, schedule_item_id: str, target_time: str
    ) -> Optional[dict]:
        micro_experiences_list = await self.get_micro_experiences_for_schedule_item(
            schedule_item_id
        )
        if not micro_experiences_list:
            return None

        try:
            target_time_obj = datetime.strptime(target_time, "%H:%M").time()
        except ValueError:
            logger.error(f"Invalid target_time format: {target_time}")
            return None

        for record in micro_experiences_list:
            experiences_in_record = record.get("experiences", [])
            if not experiences_in_record:
                continue

            for exp in experiences_in_record:
                exp_start_time_str = exp.get("start_time")
                exp_end_time_str = exp.get("end_time")

                if not (exp_start_time_str and exp_end_time_str):
                    logger.warning(
                        f"Micro experience item missing start_time or end_time: {exp}"
                    )
                    continue

                try:
                    exp_start_time_obj = datetime.strptime(
                        exp_start_time_str, "%H:%M"
                    ).time()
                    exp_end_time_obj = datetime.strptime(
                        exp_end_time_str, "%H:%M"
                    ).time()
                except ValueError:
                    logger.error(f"Invalid time format in micro experience item: {exp}")
                    continue

                if exp_start_time_obj <= target_time_obj < exp_end_time_obj:
                    logger.debug(f"Matched micro experience: {exp.get('content')}")
                    return exp

        logger.debug("No matching micro experience found for current time.")
        return None


# 示例用法 (在实际应用中，这些会通过API或调度器触发)
async def main(target_date: date = None):
    """主执行函数，包含异常处理和日期参数"""
    target_date = target_date or date.today()

    try:
        logger.info(f"[main] 开始生成日程系统: {target_date}")

        # 生成主日程
        await generate_and_store_daily_life(target_date)

        # 示例查询功能验证
        logger.debug("[main] 验证系统查询功能")
        query = LifeSystemQuery(target_date)
        print(f"\n{target_date} 是否处于大事件中: {await query.is_in_major_event()}")
        print(f"当日日程摘要: {await query.get_daily_schedule_info() or '无日程'}")

    except Exception as e:
        logger.critical(f"‼️ 主流程执行失败: {str(e)}", exc_info=True)
        raise

    print("\n--- LifeSystemQuery 示例 ---")
    query_today = LifeSystemQuery()
    print(
        f"今天 ({query_today.date_str}) 是否处于大事件中: {await query_today.is_in_major_event()}"
    )
    print(
        f"今天 ({query_today.date_str}) 的大事件信息: {await query_today.get_major_event_info()}"
    )
    print(
        f"今天 ({query_today.date_str}) 的日程信息: {await query_today.get_daily_schedule_info()}"
    )

    # 假设有一个日程项ID
    # example_schedule_item_id = "some_uuid_from_db"
    # print(f"日程项 {example_schedule_item_id} 的微观经历: {await query_today.get_micro_experiences_for_schedule_item(example_schedule_item_id)}")
    # print(f"日程项 {example_schedule_item_id} 在 10:00 的微观经历: {await query_today.get_micro_experience_at_time(example_schedule_item_id, '10:00')}")


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(description="德州生活系统生成器")
    parser.add_argument(
        "--date", type=str, help="指定生成日期 (格式: YYYY-MM-DD)", default=None
    )
    args = parser.parse_args()

    target_date = date.today()
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"无效日期格式: {args.date}, 使用今日日期")
            target_date = date.today()

    logger.debug(f"[main] 执行日期: {target_date}")
    asyncio.run(main(target_date))
