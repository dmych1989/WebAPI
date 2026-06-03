# -*- coding: utf-8 -*-
"""WebAPI — 日志模块

使用标准库 logging，统一日志格式。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


# ---- 默认 Logger ----
logger = logging.getLogger("webapi")


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = "logs",
):
    """初始化日志系统

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径 (None 则仅控制台)
        log_dir: 日志目录
    """
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 格式
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 文件 handler
    if log_file:
        path = Path(log_file)
    else:
        path = Path(log_dir) / "webapi.log"
    path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(str(path), encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.info(f"Logging initialized: level={level}, file={path}")

    return logger