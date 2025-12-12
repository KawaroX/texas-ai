# Texas AI 项目改进建议

生成日期: 2025-12-12

## 🔴 高优先级 - 立即处理

### 1. 修复网络请求超时问题 ✅ 已修复
- **问题**: `generate_daily_life_task` 使用默认的 5 秒超时，导致生成任务总是失败
- **影响**: 每日日程无法自动生成
- **解决方案**: 已将超时时间设置为 300 秒
- **位置**: `tasks/daily_tasks.py:225`

### 2. 清理调试代码
**问题**: 项目中存在大量 `print()` 语句和调试代码
```bash
# 受影响的文件（部分）:
- tasks/interaction_tasks.py (多处 print 和 DEBUG 日志)
- app/life_system.py
- core/rag_decision_system.py
```

**建议**:
- 将所有 `print()` 替换为 `logger.debug()`
- 移除生产环境中不需要的 DEBUG 日志
- 或者使用环境变量控制日志级别

### 3. 删除备份文件
**问题**: 仓库中包含备份文件
```bash
app/mattermost_client_副本.py
app/mattermost_client_副本2.py
```

**建议**:
```bash
git rm app/mattermost_client_副本.py app/mattermost_client_副本2.py
git commit -m "chore: remove backup files"
```

### 4. 改进错误处理
**当前问题示例** (`tasks/daily_tasks.py:228-229`):
```python
except Exception as e:
    return {"status": "error", "message": str(e)}
```

**建议改进**:
```python
except httpx.TimeoutException as e:
    logger.error(f"生成日程超时: {e}")
    return {"status": "error", "message": "timeout", "details": str(e)}
except httpx.HTTPStatusError as e:
    logger.error(f"API 返回错误状态: {e.response.status_code}")
    return {"status": "error", "message": "http_error", "status_code": e.response.status_code}
except Exception as e:
    logger.exception(f"生成日程失败: {e}")  # 使用 logger.exception 会自动记录堆栈
    return {"status": "error", "message": str(e)}
```

---

## 🟡 中优先级 - 近期优化

### 5. 统一日志格式
**问题**: 日志消息格式不统一
- 有些使用 `[module_name]` 前缀
- 有些使用中文，有些使用英文
- 有些使用表情符号

**建议**: 制定统一的日志规范
```python
# 推荐格式
logger.info("[生成日程] 开始生成 date=%s", date)
logger.debug("[生成日程] AI 响应: %s", response[:100])
logger.error("[生成日程] 生成失败: %s", error, exc_info=True)
```

### 6. 添加健康检查端点
**建议**: 在 `app/main.py` 中添加健康检查端点

```python
@app.get("/health")
async def health_check():
    """健康检查端点，用于监控系统状态"""
    try:
        # 检查 Redis 连接
        redis_ok = redis_client.ping()

        # 检查数据库连接
        from utils.postgres_service import test_db_connection
        db_ok = test_db_connection()

        # 检查今天是否有日程数据
        from app.life_system import LifeSystemQuery
        today = date.today()
        schedule = await LifeSystemQuery(today).get_daily_schedule_info()

        return {
            "status": "healthy",
            "redis": redis_ok,
            "database": db_ok,
            "has_today_schedule": schedule is not None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/health/celery")
async def celery_health():
    """Celery 任务队列健康检查"""
    from tasks.celery_app import celery_app

    try:
        # 检查 Celery workers 是否在线
        stats = celery_app.control.inspect().stats()
        active = celery_app.control.inspect().active()

        return {
            "status": "healthy" if stats else "unhealthy",
            "workers": list(stats.keys()) if stats else [],
            "active_tasks": sum(len(tasks) for tasks in active.values()) if active else 0
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### 7. 改进 Celery 任务监控
**建议**: 添加任务失败重试机制

```python
# tasks/daily_tasks.py
@shared_task(
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def generate_daily_life_task(self, date: str | None = None):
    try:
        # ... 现有代码 ...
    except httpx.TimeoutException as exc:
        # 超时时重试
        logger.warning(f"生成日程超时，将重试: {exc}")
        raise self.retry(exc=exc, countdown=60)  # 60秒后重试
    except Exception as e:
        logger.error(f"生成日程失败: {e}")
        return {"status": "error", "message": str(e)}
```

### 8. 优化数据库查询
**建议**: 添加数据库连接池配置和查询优化

在 `utils/postgres_service.py` 中:
```python
# 添加连接池配置
import psycopg2.pool

connection_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=20,  # 根据实际负载调整
    host=settings.POSTGRES_HOST,
    database=settings.POSTGRES_DB,
    user=settings.POSTGRES_USER,
    password=settings.POSTGRES_PASSWORD
)

# 添加查询缓存（对于不常变化的数据）
from functools import lru_cache

@lru_cache(maxsize=100)
def get_major_event_by_date_cached(date_str: str):
    # 大事件数据可以缓存，因为不会频繁变化
    return get_major_event_by_date(date_str)
```

### 9. 环境变量验证
**建议**: 在启动时验证所有必需的环境变量

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 添加必需字段验证
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    REDIS_HOST: str = "redis"
    GEMINI_API_KEY: str
    MATTERMOST_HOST: str
    MATTERMOST_TOKEN: str

    # 添加启动时验证
    @classmethod
    def validate_settings(cls):
        required = [
            'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB',
            'REDIS_HOST', 'GEMINI_API_KEY', 'MATTERMOST_HOST', 'MATTERMOST_TOKEN'
        ]
        missing = [key for key in required if not getattr(settings, key, None)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
```

---

## 🟢 低优先级 - 长期改进

### 10. 添加单元测试
**建议**: 为核心功能添加单元测试

```python
# tests/test_life_system.py
import pytest
from app.life_system import generate_and_store_daily_life

@pytest.mark.asyncio
async def test_generate_daily_life():
    from datetime import date
    target_date = date.today()
    result = await generate_and_store_daily_life(target_date)
    assert result is not None
    assert "schedule_items" in result

# tests/test_tasks.py
def test_fetch_and_store_life_data_task():
    from tasks.life_data_tasks import fetch_and_store_life_data_task
    result = fetch_and_store_life_data_task()
    assert result["status"] in ["success", "triggered_generation"]
```

### 11. 性能监控
**建议**: 添加性能监控和 APM (Application Performance Monitoring)

```python
# 可以使用 Prometheus + Grafana
# 或者简单的自定义监控

from functools import wraps
import time

def monitor_performance(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        duration = time.time() - start

        # 记录到 Redis 或日志
        logger.info(f"[性能监控] {func.__name__} 耗时: {duration:.2f}s")

        # 如果超过阈值，发送告警
        if duration > 30:
            logger.warning(f"[性能警告] {func.__name__} 耗时过长: {duration:.2f}s")

        return result
    return wrapper

# 使用示例
@monitor_performance
async def generate_and_store_daily_life(target_date: date):
    # ... 现有代码 ...
```

### 12. 数据备份策略
**建议**: 实现自动数据备份

```python
# tasks/backup_tasks.py
@shared_task
def backup_database():
    """每天备份数据库"""
    import subprocess
    from datetime import datetime

    backup_file = f"backups/db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"

    try:
        subprocess.run([
            "pg_dump",
            "-h", settings.POSTGRES_HOST,
            "-U", settings.POSTGRES_USER,
            "-d", settings.POSTGRES_DB,
            "-f", backup_file
        ], check=True)

        logger.info(f"数据库备份成功: {backup_file}")

        # 删除 7 天前的备份
        cleanup_old_backups(days=7)

    except Exception as e:
        logger.error(f"数据库备份失败: {e}")

# 在 celery_app.py 中添加调度
"backup-database": {
    "task": "tasks.backup_tasks.backup_database",
    "schedule": crontab(hour=2, minute=0),  # 每天凌晨 2 点备份
}
```

### 13. API 速率限制
**建议**: 添加 API 速率限制，防止滥用

```python
# app/main.py
from fastapi import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

@app.get("/generate-daily-life")
@limiter.limit("5/minute")  # 每分钟最多 5 次请求
async def generate_daily_life_endpoint(request: Request, target_date: str = None):
    # ... 现有代码 ...
```

### 14. 配置管理优化
**建议**: 使用配置中心或配置文件分层

```
config/
  ├── base.yml          # 基础配置
  ├── development.yml   # 开发环境
  ├── production.yml    # 生产环境
  └── local.yml         # 本地配置（不提交到 Git）
```

### 15. 代码质量工具
**建议**: 添加代码质量检查工具

```bash
# 安装工具
pip install black flake8 mypy pylint isort

# pyproject.toml
[tool.black]
line-length = 100
target-version = ['py311']

[tool.isort]
profile = "black"
line_length = 100

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true

# 添加 pre-commit 钩子
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
```

---

## 📊 性能优化建议

### 16. Redis 使用优化
**当前问题**:
- 可能存在 Redis 连接泄漏
- 没有使用连接池

**建议**:
```python
# utils/redis_manager.py
import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool

# 使用异步连接池
pool = ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    max_connections=50,
    decode_responses=True
)

async_redis_client = aioredis.Redis(connection_pool=pool)
```

### 17. 缓存策略
**建议**: 为频繁查询的数据添加缓存

```python
from functools import lru_cache
import asyncio

# 内存缓存 + Redis 缓存双层策略
async def get_daily_schedule_with_cache(date_str: str):
    # 1. 先查内存缓存
    cache_key = f"schedule:{date_str}"

    # 2. 查 Redis 缓存
    cached = await async_redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # 3. 查数据库
    schedule = get_daily_schedule_by_date(date_str)

    # 4. 写入缓存（24小时过期）
    if schedule:
        await async_redis_client.setex(
            cache_key,
            86400,
            json.dumps(schedule, ensure_ascii=False)
        )

    return schedule
```

---

## 🔒 安全性改进

### 18. 敏感信息保护
**建议**:
- 不要在日志中输出敏感信息（API keys, tokens）
- 添加日志脱敏函数

```python
# utils/logging_config.py
def sanitize_log_message(message: str) -> str:
    """脱敏处理日志消息"""
    import re
    # 隐藏 API keys
    message = re.sub(r'(api[_-]?key["\s:=]+)[\w-]+', r'\1***', message, flags=re.IGNORECASE)
    # 隐藏 tokens
    message = re.sub(r'(token["\s:=]+)[\w-]+', r'\1***', message, flags=re.IGNORECASE)
    # 隐藏密码
    message = re.sub(r'(password["\s:=]+)[\w-]+', r'\1***', message, flags=re.IGNORECASE)
    return message
```

### 19. 输入验证
**建议**: 为 API 端点添加输入验证

```python
from pydantic import BaseModel, validator
from datetime import date

class DateInput(BaseModel):
    target_date: str

    @validator('target_date')
    def validate_date(cls, v):
        try:
            date.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('日期格式必须是 YYYY-MM-DD')

@app.get("/generate-daily-life")
async def generate_daily_life_endpoint(date_input: DateInput = Depends()):
    # ... 使用验证后的数据 ...
```

---

## 📈 监控和告警

### 20. 添加告警系统
**建议**: 当关键任务失败时发送告警

```python
# utils/alerting.py
import httpx

async def send_alert(title: str, message: str, level: str = "warning"):
    """发送告警通知（可以使用企业微信、钉钉、邮件等）"""
    # 示例：发送到 Webhook
    webhook_url = settings.ALERT_WEBHOOK_URL

    if not webhook_url:
        logger.warning("未配置告警 Webhook，跳过告警发送")
        return

    try:
        await httpx.post(
            webhook_url,
            json={
                "title": title,
                "message": message,
                "level": level,
                "timestamp": datetime.now().isoformat()
            },
            timeout=5.0
        )
    except Exception as e:
        logger.error(f"发送告警失败: {e}")

# 在关键任务中使用
@shared_task
def generate_daily_life_task(date: str | None = None):
    try:
        # ... 任务逻辑 ...
    except Exception as e:
        asyncio.run(send_alert(
            title="日程生成失败",
            message=f"生成 {date} 的日程时发生错误: {str(e)}",
            level="error"
        ))
        raise
```

---

## 📝 文档改进

### 21. API 文档完善
**建议**: 为所有 API 端点添加详细的文档字符串

```python
@app.get(
    "/generate-daily-life",
    summary="生成每日日程",
    description="为指定日期生成德克萨斯的每日生活日程，包括天气、活动安排和微观经历",
    response_description="生成结果，包含成功消息或错误信息",
    tags=["日程管理"]
)
async def generate_daily_life_endpoint(
    target_date: str = Query(
        None,
        description="目标日期，格式为 YYYY-MM-DD。如果不指定，默认为今天",
        example="2025-12-12"
    )
):
    """
    ## 功能说明
    触发生成指定日期的德克萨斯生活日程。

    ## 处理流程
    1. 验证日期格式
    2. 获取天气信息
    3. 生成日程安排
    4. 生成微观经历
    5. 存储到数据库和 Redis

    ## 注意事项
    - 生成过程可能需要较长时间（1-5分钟）
    - 如果日期已存在日程，将会更新
    - 生成后会自动触发交互事件收集
    """
    # ... 现有代码 ...
```

---

## 🎯 实施优先级建议

### 立即处理（本周）
1. ✅ 修复超时问题（已完成）
2. 清理调试代码和备份文件
3. 改进错误处理
4. 添加健康检查端点

### 近期优化（2周内）
5. 统一日志格式
6. 添加 Celery 任务重试
7. 环境变量验证
8. 基础监控和告警

### 长期改进（1个月内）
9. 添加单元测试
10. 性能优化（缓存、连接池）
11. 数据备份策略
12. 代码质量工具集成

---

## 📞 需要讨论的问题

1. **数据保留策略**: 微观经历数据应该保留多久？
2. **告警通知方式**: 使用什么渠道发送告警（企业微信、邮件、钉钉）？
3. **监控方案**: 是否需要引入 Prometheus + Grafana？
4. **测试覆盖率目标**: 期望达到多少测试覆盖率？
5. **部署方式**: 是否考虑 CI/CD 自动化部署？

---

*本文档会持续更新。如有新的改进建议，请及时补充。*
