"""统一日志配置。

用法：
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("some message")
"""

import logging
import sys
from pathlib import Path

# ---------- 配置 ----------
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "agent.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 标记是否已经初始化过（避免重复添加 handler）
_initialized = False


def _init_root_logger() -> None:
    """初始化根 logger，只执行一次。"""
    global _initialized
    if _initialized:
        return

    # 确保日志目录存在
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 清空可能存在的 handler（避免重复）
    root.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Handler 1：文件（所有 INFO 及以上）
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Handler 2：stderr（实时查看）
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取 logger 实例。

    :param name: 通常传 __name__，用于区分日志来源
    """
    _init_root_logger()
    return logging.getLogger(name)
