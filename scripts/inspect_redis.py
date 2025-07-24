import redis
from app.config import settings
import json
from datetime import date, datetime


def inspect_life_data():
    # 连接到Redis
    r = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)

    # 获取今天的键名
    today = date.today().strftime("%Y-%m-%d")
    time = datetime.now().strftime("%H:%M:%S")
    key = f"life_system:{today}_{time}"

    # 检查键是否存在
    if not r.exists(key):
        print(f"没有找到今天({today})的生活系统数据")
        return

    # 获取所有字段
    data = {
        "major_event": r.hget(key, "major_event"),
        "daily_schedule": r.hget(key, "daily_schedule"),
        "current_micro_experience": r.hget(key, "current_micro_experience"),
        "past_micro_experiences": r.hget(key, "past_micro_experiences"),
    }

    # 打印格式化数据
    print(f"=== {today} 生活系统数据 ===")
    for field, value in data.items():
        print(f"\n{field}:")
        if value and value != "null":
            try:
                parsed = json.loads(value)
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
            except:
                print(value)
        else:
            print("无数据")


if __name__ == "__main__":
    inspect_life_data()
