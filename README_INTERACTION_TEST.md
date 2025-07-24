# 主动交互系统测试指南

## 概述

这个测试系统用于验证德克萨斯AI的主动交互功能，包括：
- 微观经历数据的生成和存储
- Redis Sorted Set的数据管理
- Celery任务的执行
- 时间范围和交互状态的判断

## 快速开始

### 1. 在宿主机运行测试（推荐）

```bash
# 确保在项目根目录
cd /path/to/texas-ai

# 给脚本执行权限
chmod +x scripts/run_interaction_test.sh

# 运行测试
./scripts/run_interaction_test.sh
```

### 2. 手动在Docker容器中运行

```bash
# 进入容器
docker-compose exec app bash

# 运行测试脚本
python /app/scripts/test_active_interaction.py
```

## 测试内容

### 1. 环境检查
- ✅ Redis连接测试
- ✅ 环境变量验证
- ✅ Docker服务状态检查

### 2. 测试数据创建
- 📅 创建当日测试日程
- 🔬 生成测试微观经历（包含需要交互的事件）
- ⏰ 设置不同时间范围的事件（过去、当前、未来）

### 3. Redis存储测试
- 📦 调用`collect_interaction_experiences`函数
- 🔍 验证Sorted Set数据结构
- 📊 检查事件的score（时间戳）设置

### 4. Celery任务测试
- 🚀 手动执行`process_scheduled_interactions`任务
- ⏱️ 验证时间范围判断逻辑
- 🔒 测试防重复交互机制
- 📝 检查交互记录的Redis Set

### 5. 状态检查
- 📈 显示Redis中的所有相关数据
- 🕐 显示事件的到期状态
- 📋 列出已交互的事件ID

## 测试输出示例

```
============================================================
  检查Docker环境
============================================================

🔸 检查Redis连接
✅ Redis连接正常

🔸 检查环境变量
✅ REDIS_URL: redis://redis:6379
✅ POSTGRES_HOST: postgres
✅ POSTGRES_DB: texas_ai

============================================================
  创建测试数据
============================================================

🔸 创建测试日程
✅ 创建测试日程，ID: 123

🔸 创建测试微观经历
✅ 创建了 2 个测试微观经历
ℹ️  经历 1: 15:30-16:30 | 嘿，我刚刚完成了一个有趣的测试活动，你觉得怎么样？...
ℹ️  经历 2: 17:00-18:00 | 我正在期待即将到来的活动！...

============================================================
  测试Redis存储功能
============================================================

🔸 调用collect_interaction_experiences函数
✅ 成功调用collect_interaction_experiences

🔸 检查Redis Sorted Set
ℹ️  Redis key: interaction_needed:2025-07-24
ℹ️  找到 2 个需要交互的事件
ℹ️  事件 1: ID=abc123, 时间=15:30-16:30
ℹ️  事件 2: ID=def456, 时间=17:00-18:00
✅ Redis Sorted Set存储正常
```

## 故障排除

### 1. Redis连接失败
```bash
# 检查Redis服务状态
docker-compose ps redis

# 重启Redis服务
docker-compose restart redis
```

### 2. 数据库连接失败
```bash
# 检查PostgreSQL服务状态
docker-compose ps postgres

# 查看数据库日志
docker-compose logs postgres
```

### 3. Celery任务失败
```bash
# 检查Celery worker日志
docker-compose logs celery-worker

# 手动启动Celery worker
docker-compose exec app celery -A tasks.celery_app worker --loglevel=debug
```

### 4. 测试数据清理
```bash
# 清理Redis测试数据
docker-compose exec app python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379')
keys = r.keys('interaction_needed:*') + r.keys('interacted_schedule_items:*')
if keys: r.delete(*keys)
print(f'清理了 {len(keys)} 个Redis key')
"

# 清理数据库测试数据（谨慎使用）
docker-compose exec app python -c "
from utils.postgres_service import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute('DELETE FROM micro_experiences WHERE date = CURRENT_DATE')
cur.execute('DELETE FROM daily_schedules WHERE date = CURRENT_DATE')
conn.commit()
print('清理了当日的测试数据')
"
```

## 调试技巧

### 1. 查看Redis数据
```bash
# 进入Redis CLI
docker-compose exec redis redis-cli

# 查看所有interaction相关的key
KEYS interaction*
KEYS interacted*

# 查看Sorted Set内容
ZRANGE interaction_needed:2025-07-24 0 -1 WITHSCORES

# 查看Set内容
SMEMBERS interacted_schedule_items:2025-07-24
```

### 2. 查看数据库数据
```bash
# 进入PostgreSQL
docker-compose exec postgres psql -U postgres -d texas_ai

# 查看今日的微观经历
SELECT * FROM micro_experiences WHERE date = CURRENT_DATE;

# 查看今日的日程
SELECT * FROM daily_schedules WHERE date = CURRENT_DATE;
```

### 3. 手动触发Celery任务
```bash
# 进入容器
docker-compose exec app bash

# 手动执行任务
python -c "
from tasks.interaction_tasks import process_scheduled_interactions
result = process_scheduled_interactions()
print('任务执行完成')
"
```

## 注意事项

1. **时间敏感性**: 测试会创建基于当前时间的事件，确保系统时间正确
2. **数据清理**: 测试会自动清理Redis数据，但数据库数据需要手动清理
3. **服务依赖**: 确保Redis、PostgreSQL和Mattermost服务都在运行
4. **权限问题**: 确保脚本有执行权限 (`chmod +x scripts/run_interaction_test.sh`)

## 扩展测试

如需添加更多测试场景，可以修改 `scripts/test_active_interaction.py` 中的测试数据：

```python
# 添加更多测试经历
additional_exp = {
    "id": str(uuid.uuid4()),
    "start_time": "09:00",
    "end_time": "09:30", 
    "content": "自定义测试内容",
    "need_interaction": True,
    "interaction_content": "自定义交互内容"
}
```

## 联系支持

如果遇到问题，请检查：
1. Docker服务是否正常运行
2. 环境变量是否正确配置
3. 网络连接是否正常
4. 日志文件中的错误信息
