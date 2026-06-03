# -*- coding: utf-8 -*-
"""WebAPI — Main Entry Point

Usage:
    python -m src.main                    # 默认启动
    python -m src.main --host 0.0.0.0    # 指定 host
    python -m src.main --port 3000        # 指定 port
    python -m src.main --config config/prod.yaml  # 指定配置文件
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="WebAPI — 网页版大模型对话转本地 API 调用",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="服务器监听地址 (默认: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="服务器监听端口 (默认: 8080)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="配置文件路径 (默认: config/config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main():
    """主入口"""
    args = parse_args()

    # 1. 加载配置
    from src.core.config import load_config, get_config
    load_config(args.config)
    config = get_config()

    # 2. 命令行参数覆盖
    if args.host:
        config.server.host = args.host
    if args.port:
        config.server.port = args.port

    # 3. 启动服务器
    import uvicorn

    uvicorn.run(
        "src.server.app:app",
        host=config.server.host,
        port=config.server.port,
        log_level=args.log_level or config.logging.level.lower(),
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    main()
