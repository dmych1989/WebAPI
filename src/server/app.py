# -*- coding: utf-8 -*-
"""WebAPI — FastAPI 应用入口

提供 OpenAI 兼容 API：
- /v1/chat/completions
- /v1/models
- /health
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.server.middleware import AuthMiddleware, LoggingMiddleware
from src.server.routes import router as api_router
from src.server.admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期（替代 on_event）"""
    from src.core.logger import logger
    from src.transport.api_reverse import close_transport

    logger.info("================== WebAPI Starting ==================")
    _init_providers()
    health_task = _start_health_check()
    try:
        yield
    finally:
        # 关闭
        if health_task and not health_task.done():
            health_task.cancel()
            try:
                await health_task
            except (asyncio.CancelledError, Exception):
                pass
        await close_transport()
        logger.info("================== WebAPI Stopped ==================")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""

    app = FastAPI(
        title="WebAPI",
        description="网页版大模型对话 → 本地 OpenAI 兼容 API",
        version="0.1.0",
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 自定义中间件
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(AuthMiddleware)

    # 注册路由
    app.include_router(api_router)
    app.include_router(admin_router, prefix="/admin")

    # API Key 管理路由（/admin/api-keys/...）
    from src.server.api_keys import router as api_keys_router
    app.include_router(api_keys_router, prefix="/admin")

    # 服务器设置路由（/admin/server/...）
    from src.server.server_settings import router as server_settings_router
    app.include_router(server_settings_router, prefix="/admin")

    # 账号管理路由（/admin/providers/...）
    from src.server.accounts import router as accounts_router
    app.include_router(accounts_router, prefix="/admin")

    # 静态管理界面
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/admin/ui", StaticFiles(directory=str(static_dir), html=True), name="admin_ui")

    return app


def _init_providers():
    """初始化所有 Provider 并注册到账号池

    遍历配置中所有 Provider（不受 enabled 状态影响），
    这样管理 UI 能完整显示所有 Provider 行。
    """
    # 触发 @ProviderRegistry.register 装饰器（导入所有 Provider）
    from src.provider.registration import (  # noqa: F401
        DeepSeekProvider,
        KimiProvider,
        QwenProvider,
        MiniMaxProvider,
        DoubaoProvider,
        YuanbaoProvider,
        GLMProvider,
        CozeProvider,
    )

    from src.core.config import get_config
    from src.pool.account_pool import account_pool
    from src.core.logger import logger

    config = get_config()
    for provider_type, provider_config in config.providers.items():
        if not provider_config.accounts:
            logger.debug(f"[Init] Provider {provider_type} has no accounts, skip")
            continue
        # 总是注册（含 enabled=False），让管理 UI 能看到全部 6 个 Provider
        account_pool.register_provider(provider_type, provider_config)
        status = "enabled" if provider_config.enabled else "disabled"
        logger.info(
            f"[Init] ✓ {provider_type} ({status}): {len(provider_config.accounts)} accounts"
        )


def _start_health_check() -> asyncio.Task:
    """启动定时健康检查后台任务，返回 Task 句柄供 lifespan 关闭时取消"""
    from src.core.config import get_config
    from src.pool.account_pool import account_pool
    from src.provider.base import ProviderRegistry
    from src.core.logger import logger

    config = get_config()

    # 找到最小 health_check_interval
    intervals = []
    for ptype, pcfg in config.providers.items():
        if not pcfg.enabled:
            continue
        for acc in pcfg.accounts:
            intervals.append(acc.health_check_interval or 60)

    interval = min(intervals) if intervals else 60

    async def _loop():
        logger.info(f"[HealthCheck] Starting loop (interval={interval}s)")
        while True:
            await asyncio.sleep(interval)
            try:
                await _run_health_checks()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[HealthCheck] Loop error: {e}")

    return asyncio.create_task(_loop())


async def _run_health_checks():
    """执行一轮健康检查"""
    from src.core.config import get_config
    from src.pool.account_pool import account_pool
    from src.provider.base import ProviderRegistry
    from src.core.logger import logger

    config = get_config()
    checked = 0

    for provider_type, pcfg in config.providers.items():
        if not pcfg.enabled:
            continue

        provider_cls = ProviderRegistry.get(provider_type)
        if provider_cls is None:
            continue

        for acc in pcfg.accounts:
            if not acc.enabled:
                continue
            checked += 1
            try:
                provider = provider_cls(acc)
                is_healthy = await provider.health_check()
                if is_healthy:
                    account_pool.mark_healthy(provider_type, acc.name)
                else:
                    account_pool.mark_unhealthy(provider_type, acc.name, "health check failed")
            except Exception as e:
                account_pool.mark_unhealthy(provider_type, acc.name, str(e))

    if checked > 0:
        logger.debug(f"[HealthCheck] Round complete: {checked} accounts checked")


app = create_app()
