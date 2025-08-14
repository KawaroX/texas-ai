import logging
from fastapi import FastAPI, HTTPException, Depends, Query
from app.config import settings
import asyncio
import json
import redis.asyncio as redis
from services.ai_service import _redis, REDIS_GEMINI_CFG_KEY, DEFAULT_GEMINI_CFG

import os

# 第二套默认 Gemini 配置
DEFAULT_GEMINI_CFG_2 = {
    "model": "gemini-2.5-flash",
    "connect_timeout": 10.0,
    "read_timeout": 60.0,
    "write_timeout": 60.0,
    "pool_timeout": 60.0,
    "stop_sequences": ["SEND", "NO_REPLY"],
    "include_thoughts": True,
    "thinking_budget": 24576,
    "response_mime_type": "text/plain",
}
ALLOWED_KEYS = set(DEFAULT_GEMINI_CFG.keys())

# 配置日志：时间戳、级别、模块、函数、行号、消息
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s:%(funcName)s:%(lineno)d - %(message)s",
)

from app.mattermost_client import MattermostWebSocketClient
from services.redis_cleanup_service import start_redis_cleanup
from app.life_system import (
    generate_and_store_daily_life,
    collect_interaction_experiences,
)
from datetime import date

app = FastAPI(title=settings.BOT_NAME)

@app.get("/")
def root():
    raise HTTPException(status_code=404, detail="Not Found")

# === Lightweight query param auth for /llm-config/* ===
# Set ADMIN_K to a long random string; if empty, auth is disabled.
ADMIN_K = os.getenv("ADMIN_K", "k8yyjSAVsbavobY92oTGcN7brVLUAD")
def check_k(k: str = Query(default="")):
    if ADMIN_K and k != ADMIN_K:
        raise HTTPException(status_code=401, detail="unauthorized")


# ===== LLM Gemini 配置管理接口 =====

@app.get("/llm-config/gemini")
async def get_gemini_cfg(_=Depends(check_k)):
    raw = await _redis.get(REDIS_GEMINI_CFG_KEY)
    return json.loads(raw) if raw else DEFAULT_GEMINI_CFG

@app.post("/llm-config/gemini/reset/{which}")
async def reset_gemini_cfg(which: int, _=Depends(check_k)):
    if which == 1:
        cfg = DEFAULT_GEMINI_CFG
    elif which == 2:
        cfg = DEFAULT_GEMINI_CFG_2
    else:
        raise HTTPException(status_code=400, detail="无效的默认值编号（只能是 1 或 2）")
    await _redis.set(REDIS_GEMINI_CFG_KEY, json.dumps(cfg, ensure_ascii=False))
    return {"ok": True, "config": cfg}

def _filter_and_merge(base: dict, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("payload 必须是 JSON 对象")
    clean = {k: v for k, v in patch.items() if k in ALLOWED_KEYS}
    merged = {**base, **clean}
    return merged

@app.patch("/llm-config/gemini")
async def patch_gemini_cfg(payload: dict, _=Depends(check_k)):
    try:
        current_raw = await _redis.get(REDIS_GEMINI_CFG_KEY)
        current = json.loads(current_raw) if current_raw else DEFAULT_GEMINI_CFG
        new_cfg = _filter_and_merge(current, payload)
        await _redis.set(REDIS_GEMINI_CFG_KEY, json.dumps(new_cfg, ensure_ascii=False))
        return {"ok": True, "config": new_cfg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/llm-config/gemini")
async def replace_gemini_cfg(payload: dict, _=Depends(check_k)):
    try:
        new_cfg = _filter_and_merge(DEFAULT_GEMINI_CFG, payload)
        await _redis.set(REDIS_GEMINI_CFG_KEY, json.dumps(new_cfg, ensure_ascii=False))
        return {"ok": True, "config": new_cfg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.BOT_NAME}!"}


@app.get("/generate-daily-life")
async def generate_daily_life_endpoint(target_date: str = None):
    """
    触发生成指定日期的德克萨斯生活日程。
    如果未指定日期，则生成今天的日程。
    """
    if target_date:
        try:
            target_date_obj = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="日期格式不正确，请使用 YYYY-MM-DD 格式。"
            )
    else:
        target_date_obj = date.today()

    await generate_and_store_daily_life(target_date_obj)
    return {
        "message": f"已触发生成 {target_date_obj.strftime('%Y-%m-%d')} 的每日日程。请查看日志和 'generated_content' 文件夹。"
    }


@app.get("/collect-interactions")
async def collect_interactions_endpoint(target_date: str = None):
    """
    手动收集需要交互的微观经历并存入Redis
    """
    if target_date:
        try:
            target_date_obj = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="日期格式不正确，请使用 YYYY-MM-DD 格式。"
            )
    else:
        target_date_obj = date.today()

    from app.life_system import collect_interaction_experiences

    success = await collect_interaction_experiences(target_date_obj)

    if success:
        return {
            "message": f"已成功收集 {target_date_obj.strftime('%Y-%m-%d')} 需要交互的微观经历"
        }
    else:
        return {
            "message": f"未找到 {target_date_obj.strftime('%Y-%m-%d')} 的日程数据或微观经历",
            "found": False,
        }


@app.on_event("startup")
async def startup_event():
    """启动 WebSocket 客户端和Redis清理服务"""
    # 启动 WebSocket 客户端
    ws_client = MattermostWebSocketClient()
    asyncio.create_task(ws_client.connect())

    # 启动 Redis 清理服务
    asyncio.create_task(start_redis_cleanup())
