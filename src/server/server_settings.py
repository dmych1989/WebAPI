# -*- coding: utf-8 -*-
"""WebAPI — 服务器设置路由

监听 Host/Port 自定义：
- GET   /admin/server/settings     获取当前 host/port
- POST  /admin/server/settings     更新 host/port（写入 config，需重启生效）
- POST  /admin/server/restart      触发进程重启（os.execv）
"""

from __future__ import annotations

import os
import sys
import signal
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.core.config import get_config, save_config
from src.core.logger import logger

router = APIRouter()


# =============================================================================
# 请求模型
# =============================================================================

class ServerSettingsRequest(BaseModel):
    """服务器设置请求"""
    host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    port: int = Field(default=8080, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def _validate_host(cls, v: str) -> str:
        """验证 host 格式（IP 或 0.0.0.0 / ::）"""
        v = v.strip()
        if not v:
            raise ValueError("Host 不能为空")
        # 允许的 host 模式
        allowed = {"localhost", "0.0.0.0", "::", "127.0.0.1"}
        if v in allowed:
            return v
        # IPv4 验证
        parts = v.split(".")
        if len(parts) == 4:
            try:
                if all(0 <= int(p) <= 255 for p in parts):
                    return v
            except ValueError:
                pass
        raise ValueError(
            f"无效的 Host: {v}。允许: IPv4 地址, 'localhost', '0.0.0.0', '::'"
        )


# =============================================================================
# 端点
# =============================================================================

@router.get("/server/settings")
async def get_server_settings():
    """获取当前服务器设置"""
    config = get_config()
    return {
        "host": config.server.host,
        "port": config.server.port,
        "api_key_enabled": config.server.api_key_enabled,
        "api_key_count": len(config.server.api_key_objects) + len(config.server.api_keys),
    }


@router.post("/server/settings")
async def update_server_settings(req: ServerSettingsRequest):
    """更新服务器设置

    注意：Host/Port 变更需要重启服务进程才能生效。
    """
    config = get_config()

    # 检查端口是否与当前相同
    if config.server.host == req.host and config.server.port == req.port:
        return {
            "status": "ok",
            "message": "Host/Port 未变更",
            "host": req.host,
            "port": req.port,
            "restart_required": False,
        }

    old_host, old_port = config.server.host, config.server.port
    config.server.host = req.host
    config.server.port = req.port
    save_config(config)

    logger.info(
        f"[Server] Settings updated: {old_host}:{old_port} → {req.host}:{req.port}"
    )

    return {
        "status": "ok",
        "message": f"已保存为 {req.host}:{req.port}，需要重启服务才能生效",
        "host": req.host,
        "port": req.port,
        "old": {"host": old_host, "port": old_port},
        "restart_required": True,
    }


@router.post("/server/restart")
async def restart_server():
    """触发服务进程重启

    实现原理：
    1. 发送 SIGTERM 给自己（或子进程）
    2. 父进程 supervisor 检测到子进程退出后重启
    3. 如果没有 supervisor，使用 os.execv 替换当前进程

    注意：此端点调用后会立即返回 200，但实际进程会在 0.5s 内重启。
    """
    config = get_config()

    # 启动后台线程延迟执行重启
    def _do_restart():
        time.sleep(0.5)
        logger.warning(
            f"[Server] Restarting process (new config: "
            f"{config.server.host}:{config.server.port})..."
        )
        # Windows 下使用 os.execv 替换当前进程
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            logger.error(f"[Server] Failed to restart: {e}")
            # 退化方案：发送 SIGTERM
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except Exception:
                pass

    threading.Thread(target=_do_restart, daemon=True).start()

    return {
        "status": "ok",
        "message": "服务正在重启... 请稍候几秒后刷新页面",
        "host": config.server.host,
        "port": config.server.port,
    }
