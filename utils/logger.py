"""统一日志配置。

用法：
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("some message")

设计要点（都对应踩过的坑）：
- 日志文件在 `<repo>/logs/agent.log`（可用 `LOGS_DIR` 覆盖），**不依赖 cwd**；
- 用 `RotatingFileHandler` + `delay=True`：不会无限增长，也不会在 import 时
  就凭空建出文件；
- **不清空宿主的 logging handler**：本模块可能作为库被别的应用引用，
  `root.handlers.clear()` 会把调用方的日志配置一起干掉；
- 级别与轮转参数可用环境变量调整：`LOG_LEVEL` / `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT`。

⚠️ 隐私提示：默认 INFO 级别会把用户输入与工具返回值写进日志，
其中可能包含员工姓名、薪资等个人信息。生产环境请调高到 `LOG_LEVEL=WARNING`
（或接入脱敏 handler）。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils.paths import AGENT_LOG, LOGS_DIR

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LEVEL = "INFO"

_initialized = False


class _AgentFileHandler(RotatingFileHandler):
    """带标记的文件 handler，用于识别"是不是我们自己加的"。"""


class _AgentStreamHandler(logging.StreamHandler):
    """带标记的 stderr handler。"""


def _log_level() -> int:
    name = os.getenv("LOG_LEVEL", DEFAULT_LEVEL).upper()
    return getattr(logging, name, logging.INFO)


def _has_our_handler(logger: logging.Logger) -> bool:
    return any(
        isinstance(h, (_AgentFileHandler, _AgentStreamHandler))
        for h in logger.handlers
    )


def _init_root_logger() -> None:
    """初始化根 logger，只执行一次。"""
    global _initialized
    if _initialized:
        return

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    level = _log_level()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if not _has_our_handler(root):
        # Handler 1：文件（自动轮转，第一条日志写入时才创建文件）
        file_handler = _AgentFileHandler(
            AGENT_LOG,
            maxBytes=int(os.getenv("LOG_MAX_BYTES", str(2 * 1024 * 1024))),
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", "3")),
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        # Handler 2：stderr（实时查看）
        stream_handler = _AgentStreamHandler(sys.stderr)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取 logger 实例。

    :param name: 通常传 __name__，用于区分日志来源
    """
    _init_root_logger()
    return logging.getLogger(name)
