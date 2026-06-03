# -*- coding: utf-8 -*-
"""WebAPI — FastAPI 中间件

- AuthMiddleware: API Key 鉴权
- LoggingMiddleware: 请求日志
"""

from __future__ import annotations

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.core.config import get_config
from src.core.logger import logger


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key 鉴权中间件"""

    async def dispatch(self, request: Request, call_next):
        # 公开路径不需要认证
        public_paths = {"/", "/health", "/stats", "/v1/docs", "/v1/redoc", "/v1/openapi.json"}
        if request.method == "OPTIONS":
            return await call_next(request)

        config = get_config()

        if not config.server.api_key_enabled:
            return await call_next(request)

        if request.url.path in public_paths:
            return await call_next(request)

        # Admin API 有自己的认证
        if request.url.path.startswith("/admin/"):
            return await call_next(request)

        # API Key 验证
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Missing or invalid Authorization header",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )

        provided_key = auth_header[7:]  # "Bearer " 之后的部分

        # 优先检查 api_key_objects（新版 ApiKey 对象列表）
        # 回退到 api_keys（旧版字符串列表，向后兼容）
        valid_keys: set[str] = set()
        for ak in config.server.api_key_objects or []:
            if ak.enabled:
                valid_keys.add(ak.key)
        valid_keys.update(config.server.api_keys or [])

        if provided_key not in valid_keys:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Incorrect API key provided",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )

        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # 跳过健康检查和静态文件
        if request.url.path in ("/health", "/favicon.ico"):
            return await call_next(request)

        response = await call_next(request)
        elapsed = time.time() - start_time

        logger.info(
            f"{request.method} {request.url.path} → {response.status_code} "
            f"({elapsed:.3f}s)"
        )

        return response
