from utils.logging_config import get_logger

logger = get_logger(__name__)

from fastapi import FastAPI, HTTPException, Depends, Query, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from app.config import settings
import asyncio
import json
from services.ai_config.gemini_config import GeminiConfigManager
import os
from app.mattermost_client import MattermostWebSocketClient
from services.redis_cleanup_service import cleanup_service
from app.life_system import (
    generate_and_store_daily_life,
    collect_interaction_experiences,
)
from datetime import date

# 统一日志配置
from utils.logging_config import setup_logging, get_logger

# 配置日志系统
setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_file=os.getenv("LOG_FILE", "logs/texas-ai.log"),
    console_output=True
)
logger = get_logger(__name__)

# 创建全局配置管理器实例
gemini_config = GeminiConfigManager()

# 第二套默认 Gemini 配置
DEFAULT_GEMINI_CFG_2 = {
    "model": "gemini-2.5-flash",
    "connect_timeout": 10.0,
    "read_timeout": 60.0,
    "write_timeout": 60.0,
    "pool_timeout": 60.0,
    "stop_sequences": ["NO_REPLY"],
    "include_thoughts": True,
    "thinking_budget": 24576,
    "response_mime_type": "text/plain",
}

DEFAULT_GEMINI_CFG = gemini_config.get_default_config()
ALLOWED_KEYS = set(DEFAULT_GEMINI_CFG.keys())


class SecurityMiddleware(BaseHTTPMiddleware):
    """安全中间件：静默处理恶意扫描请求"""
    
    # 常见的恶意扫描路径
    MALICIOUS_PATHS = {
        "/favicon.ico",
        "/robots.txt", 
        "/sitemap.xml",
        "/wp-login.php",
        "/admin",
        "/login",
        "/phpMyAdmin",
        "/images/js/eas/eas.js",
        "/.env",
        "/.git",
        "/config",
        "/setup",
        "/install",
    }
    
    # 可疑的查询参数
    SUSPICIOUS_PARAMS = {"format": "json"}
    
    async def dispatch(self, request: Request, call_next):
        # WebSocket升级请求不进行过滤
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        
        client_ip = request.client.host if request.client else "unknown"
        
        # 检查是否为恶意路径
        if request.url.path in self.MALICIOUS_PATHS:
            logger.warning(f"阻止恶意扫描请求: {request.url.path} from {client_ip}")
            return Response(status_code=404, content="")
        
        # 检查可疑查询参数
        for param, value in self.SUSPICIOUS_PARAMS.items():
            if request.query_params.get(param) == value:
                logger.warning(f"阻止可疑查询参数: {param}={value} from {client_ip}")
                return Response(status_code=404, content="")
        
        # 对根路径的非正常请求静默处理
        if request.url.path == "/" and request.method == "GET":
            # 检查User-Agent是否像爬虫/扫描器
            user_agent = request.headers.get("user-agent", "").lower()
            if any(bot in user_agent for bot in ["bot", "crawler", "spider", "scanner", "curl", "wget"]):
                logger.info(f"阻止爬虫/扫描器访问根路径: {user_agent[:50]} from {client_ip}")
                return Response(status_code=404, content="")
        
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器"""
    logger.info("德克萨斯AI系统启动中...")
    
    try:
        # 启动事件
        logger.info("初始化 Mattermost WebSocket 客户端")
        ws_client = MattermostWebSocketClient()
        asyncio.create_task(ws_client.connect())
        
        # 启动 Redis 清理服务
        logger.info("启动 Redis 清理服务")
        asyncio.create_task(cleanup_service.start_cleanup_scheduler())
        
        logger.info("所有服务已启动，系统就绪")
        
        yield
        
        # 关闭事件
        logger.info("德克萨斯AI系统正在关闭...")
        logger.info("系统已安全关闭")
        
    except Exception as e:
        logger.critical(f"系统启动失败: {e}", exc_info=True)
        raise


app = FastAPI(title=settings.BOT_NAME, lifespan=lifespan)

# 添加安全中间件
app.add_middleware(SecurityMiddleware)


# 静默404异常处理器 - 减少日志噪音
@app.exception_handler(404)
@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc):
    # 对于恶意扫描请求，直接返回空响应，不记录日志
    if (request.url.path in SecurityMiddleware.MALICIOUS_PATHS or 
        request.url.path == "/" or
        any(param in request.query_params for param in SecurityMiddleware.SUSPICIOUS_PARAMS.keys())):
        return Response(status_code=404, content="")
    
    # 对于正常的404请求，使用默认处理器
    return await http_exception_handler(request, exc)


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
    return await gemini_config.load_config()


@app.post("/llm-config/gemini/reset/{which}")
async def reset_gemini_cfg(which: int, _=Depends(check_k)):
    if which == 1:
        cfg = DEFAULT_GEMINI_CFG
    elif which == 2:
        cfg = DEFAULT_GEMINI_CFG_2
    else:
        raise HTTPException(status_code=400, detail="无效的默认值编号（只能是 1 或 2）")
    await gemini_config.save_config(cfg)
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
        current = await gemini_config.load_config()
        new_cfg = _filter_and_merge(current, payload)
        await gemini_config.save_config(new_cfg)
        return {"ok": True, "config": new_cfg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/llm-config/gemini")
async def replace_gemini_cfg(payload: dict, _=Depends(check_k)):
    try:
        new_cfg = _filter_and_merge(DEFAULT_GEMINI_CFG, payload)
        await gemini_config.save_config(new_cfg)
        return {"ok": True, "config": new_cfg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Keep root path returning 404 (not accessible)


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


