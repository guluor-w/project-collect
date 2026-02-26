# mylogger.py
import logging
import os
from datetime import datetime

from ccgp.config import LOGGING_DIR, LOGGING_LEVEL

# 全局logger实例
_logger = None

def setup_logging(log_dir=LOGGING_DIR, log_level=LOGGING_LEVEL):
    """设置全局日志配置"""
    global _logger
    
    if _logger is not None:
        return _logger
    os.makedirs(log_dir, exist_ok=True)
    
    # 生成日志文件名（带日期时间）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"app_{timestamp}.log")
    
    _logger = logging.getLogger("myapp")
    _logger.setLevel(log_level)
    if not _logger.handlers:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        _logger.addHandler(file_handler)
        _logger.addHandler(console_handler)
    
    return _logger

def get_logger():
    """获取全局logger实例"""
    global _logger
    if _logger is None:
        setup_logging()
    return _logger