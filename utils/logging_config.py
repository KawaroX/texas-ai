"""
Texas AI 统一日志配置模块

提供丰富的符号表达和清晰的日志格式，让日志更易读和美观。
支持根据日志内容智能选择符号，而不是简单的级别符号。
"""

import logging
import logging.handlers
import os
import sys
import re
from datetime import datetime
from typing import Optional


class TexasLogFormatter(logging.Formatter):
    """德克萨斯AI专用日志格式化器 - 支持智能符号选择"""
    
    # 基础级别符号（作为备选）
    LEVEL_SYMBOLS = {
        logging.DEBUG: "🔍",
        logging.INFO: "ℹ️",
        logging.WARNING: "⚠️", 
        logging.ERROR: "❌",
        logging.CRITICAL: "🚨"
    }
    
    # 智能内容符号匹配（优先级更高）
    CONTENT_SYMBOLS = [
        # AI 和处理 (优先级最高)
        (r'(AI|LLM|Gemini|OpenAI|Claude|生成|analyze)', "✨"),
        
        # 系统和启动
        (r'(启动|初始化|开始|start|init)', "🚀"),
        (r'(配置|config|setting)', "🔧"),
        (r'(连接|connect|websocket)', "🔌"),
        (r'(成功|完成|success|done|ok)', "✅"),
        (r'(失败|错误|error|fail)', "❌"),
        (r'(图片|图像|image|photo|生成)', "🖼️"),
        (r'(聊天|消息|message|chat|回复)', "💬"),
        (r'(记忆|memory|存储|storage)', "🧠"),
        
        # 技术操作
        (r'(Redis|缓存|cache)', "⚡"),
        (r'(数据库|database|PostgreSQL|SQL)', "🗄️"),
        (r'(文件|file|保存|save)', "📁"),
        (r'(网络|network|http|api)', "🌐"),
        (r'(任务|task|job|celery)', "⚙️"),
        
        # 用户交互
        (r'(用户|user|kawaro)', "👤"),
        (r'(频道|channel|team)', "📢"),
        (r'(通知|notification|bark)', "🔔"),
        
        # 状态和监控
        (r'(检查|check|验证|verify)', "🔍"),
        (r'(清理|cleanup|删除|delete)', "🧹"),
        (r'(更新|update|修改|change)', "🔄"),
        (r'(警告|warning|注意)', "⚠️"),
    ]
    
    # ANSI 颜色代码
    COLORS = {
        logging.DEBUG: '\033[36m',     # 青色
        logging.INFO: '\033[32m',      # 绿色  
        logging.WARNING: '\033[33m',   # 黄色
        logging.ERROR: '\033[31m',     # 红色
        logging.CRITICAL: '\033[35m',  # 紫色
        'RESET': '\033[0m'             # 重置
    }
    
    # 模块名简化
    MODULE_NAMES = {
        "app.main": "MAIN",
        "app.mattermost_client": "MM", 
        "app.life_system": "LIFE",
        "core.chat_engine": "CHAT",
        "core.context_merger": "CTX",
        "core.memory_buffer": "MEM",
        "core.persona": "PERSONA",
        "services.ai_service": "AI",
        "services.memory_storage": "STORAGE",
        "services.image_service": "IMG",
        "services.character_manager": "CHAR",
        "tasks.daily_tasks": "TASKS",
        "tasks.interaction_tasks": "INTERACT",
        "tasks.image_generation_tasks": "IMG_GEN",
    }
    
    def __init__(self, use_colors: bool = True, use_smart_symbols: bool = True):
        super().__init__()
        self.use_colors = use_colors and hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()
        self.use_smart_symbols = use_smart_symbols
        
    def _get_smart_symbol(self, record: logging.LogRecord) -> str:
        """根据日志内容智能选择符号"""
        if not self.use_smart_symbols:
            return self.LEVEL_SYMBOLS.get(record.levelno, "📝")
            
        message = record.getMessage().lower()
        
        # 优先匹配内容符号
        for pattern, symbol in self.CONTENT_SYMBOLS:
            if re.search(pattern, message, re.IGNORECASE):
                return symbol
                
        # 如果没有匹配到内容符号，使用级别符号
        return self.LEVEL_SYMBOLS.get(record.levelno, "📝")
    
    def format(self, record: logging.LogRecord) -> str:
        # 时间戳
        record.asctime = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        
        # 获取智能符号
        symbol = self._get_smart_symbol(record)
        
        # 模块简称
        module_name = self.MODULE_NAMES.get(record.name, record.name.split('.')[-1].upper())
        
        # 颜色处理
        if self.use_colors:
            color = self.COLORS.get(record.levelno, '')
            reset = self.COLORS['RESET']
            level_str = f"{color}{record.levelname:<8}{reset}"
            module_str = f"{color}{module_name:<12}{reset}"
        else:
            level_str = f"{record.levelname:<8}"
            module_str = f"{module_name:<12}"
        
        # 位置信息
        location = f"{record.funcName}:{record.lineno}"
        
        # 构建日志
        formatted = f"{symbol} {record.asctime} - {level_str} - {module_str} - {location:<20} - {record.getMessage()}"
        
        # 添加异常信息
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
            
        return formatted


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    console_output: bool = True,
    use_smart_symbols: bool = True
):
    """
    设置Texas AI统一日志配置
    
    Args:
        level: 日志级别
        log_file: 日志文件路径
        max_file_size: 单个日志文件最大大小
        backup_count: 保留的备份文件数量
        console_output: 是否输出到控制台
        use_smart_symbols: 是否使用智能符号选择
    """
    # 清除已有handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 设置级别
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(log_level)
    
    # 控制台输出
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_formatter = TexasLogFormatter(
            use_colors=True, 
            use_smart_symbols=use_smart_symbols
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # 文件输出
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_formatter = TexasLogFormatter(
            use_colors=False, 
            use_smart_symbols=use_smart_symbols
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # 第三方库配置
    _configure_third_party_loggers()
    
    # 启动消息
    logger = logging.getLogger(__name__)
    logger.info(f"🚀 Texas AI日志系统已配置 - 级别: {level}, 智能符号: {'开启' if use_smart_symbols else '关闭'}")


def _configure_third_party_loggers():
    """配置第三方库日志级别"""
    third_party_configs = {
        'httpx': logging.WARNING,
        'httpcore': logging.WARNING,
        'urllib3': logging.WARNING,
        'requests': logging.WARNING,
        'asyncio': logging.WARNING,
        'celery': logging.INFO,
        'redis': logging.WARNING,
        'websockets': logging.WARNING,
        'PIL': logging.WARNING,
    }
    
    for logger_name, level in third_party_configs.items():
        logging.getLogger(logger_name).setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """获取标准配置的logger"""
    return logging.getLogger(name)


# 便捷方法：为特定操作添加符号
def log_success(logger, message: str):
    """记录成功操作"""
    logger.info(f"✅ {message}")

def log_start(logger, message: str):
    """记录开始操作"""
    logger.info(f"🚀 {message}")

def log_ai_operation(logger, message: str):
    """记录AI操作"""
    logger.info(f"✨ {message}")

def log_config(logger, message: str):
    """记录配置操作"""
    logger.info(f"🔧 {message}")

def log_user_action(logger, message: str):
    """记录用户操作"""
    logger.info(f"👤 {message}")

def log_network(logger, message: str):
    """记录网络操作"""
    logger.info(f"🌐 {message}")


# 默认初始化（如果直接导入）
if not logging.getLogger().handlers:
    setup_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        console_output=True,
        use_smart_symbols=True
    )