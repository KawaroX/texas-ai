"""统一日志配置模块

提供整个项目的统一日志配置和格式化。
"""

import logging
import sys
import os
from typing import Optional


class TexasLogFormatter(logging.Formatter):
    """德克萨斯AI专用日志格式化器"""
    
    # 颜色代码
    COLORS = {
        logging.DEBUG: '\033[36m',    # 青色
        logging.INFO: '\033[32m',     # 绿色  
        logging.WARNING: '\033[33m',  # 黄色
        logging.ERROR: '\033[31m',    # 红色
        logging.CRITICAL: '\033[35m', # 紫色
    }
    RESET = '\033[0m'
    
    # 级别符号
    LEVEL_SYMBOLS = {
        logging.DEBUG: "🔍",
        logging.INFO: "ℹ️", 
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "🚨"
    }
    
    def __init__(self, use_colors: bool = True, use_symbols: bool = True):
        super().__init__()
        self.use_colors = use_colors
        self.use_symbols = use_symbols
        
    def format(self, record: logging.LogRecord) -> str:
        # 获取符号
        symbol = self.LEVEL_SYMBOLS.get(record.levelno, "") if self.use_symbols else ""
        
        # 构建基本格式
        level_name = record.levelname
        
        # 添加颜色
        if self.use_colors and record.levelno in self.COLORS:
            level_name = f"{self.COLORS[record.levelno]}{level_name}{self.RESET}"
        
        # 格式化消息
        formatted = f"{symbol} {record.asctime} - {level_name} - {record.name} - {record.getMessage()}"
        
        # 添加异常信息
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
            
        return formatted


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    console_output: bool = True,
    use_colors: bool = True,
    use_symbols: bool = True,
    format_string: Optional[str] = None
) -> None:
    """设置全局日志配置
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，None表示不写文件
        console_output: 是否输出到控制台
        use_colors: 是否使用颜色
        use_symbols: 是否使用符号
        format_string: 自定义格式字符串
    """
    
    # 转换日志级别
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 创建格式化器
    if format_string:
        formatter = logging.Formatter(format_string)
    else:
        formatter = TexasLogFormatter(use_colors=use_colors, use_symbols=use_symbols)
        formatter.datefmt = "%Y-%m-%d %H:%M:%S"
    
    # 控制台处理器
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # 文件处理器
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(numeric_level)
        
        # 文件日志不使用颜色和符号
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        )
        file_formatter.datefmt = "%Y-%m-%d %H:%M:%S"
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # 配置第三方库的日志级别
    _configure_third_party_loggers()


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器
    
    Args:
        name: 日志器名称，通常使用 __name__
        
    Returns:
        配置好的日志器实例
    """
    return logging.getLogger(name)


def _configure_third_party_loggers():
    """配置第三方库的日志级别"""
    
    # 第三方库日志级别配置
    third_party_levels = {
        'httpx': logging.WARNING,
        'httpcore': logging.WARNING,
        'websockets': logging.WARNING,
        'asyncio': logging.WARNING,
        'urllib3': logging.WARNING,
        'requests': logging.WARNING,
        'redis': logging.WARNING,
        'psycopg2': logging.WARNING,
        'sqlalchemy': logging.WARNING,
        'celery': logging.INFO,
        'kombu': logging.WARNING,
        'PIL': logging.WARNING,
        'matplotlib': logging.WARNING,
    }
    
    for logger_name, level in third_party_levels.items():
        logging.getLogger(logger_name).setLevel(level)


# 默认配置（如果直接导入此模块）
if not logging.getLogger().handlers:
    setup_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        console_output=True,
        use_colors=True,
        use_symbols=True
    )