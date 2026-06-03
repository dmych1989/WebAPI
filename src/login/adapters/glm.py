# -*- coding: utf-8 -*-
"""
GLM OAuth Adapter
参考 Chat2API src/main/oauth/adapters/glm.ts

认证方式: Bearer Token (API Key, sk- 或 eyJ 开头)
验证端点: GET /api/paas/v4/models (官方 BigModel API)
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

GLM_API_BASE = "https://open.bigmodel.cn/api/paas/v4"


class GLMAdapter(BaseOAuthAdapter):
    provider_type = "glm"

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 GLM BigModel API Token

        参考 Chat2API GLMAdapter.validateToken:
        - Bearer Token 认证 (sk-xxx 或 eyJxxx)
        - GET /api/paas/v4/models
        - 返回 200 表示 token 有效
        """
        token = credentials.get("token") or credentials.get("refresh_token")
        if not token:
            return TokenValidationResult(valid=False, error="Token cannot be empty")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{GLM_API_BASE}/models",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 401:
                        return TokenValidationResult(valid=False, error="Token is invalid or expired (401)")
                    if resp.status == 403:
                        return TokenValidationResult(valid=False, error="Token is forbidden (403)")
                    if resp.status != 200:
                        return TokenValidationResult(
                            valid=False,
                            error=f"Token validation failed (HTTP {resp.status})",
                        )

                    body = await resp.json()
                    data = body.get("data", {})
                    models = data.get("data", []) if isinstance(data, dict) else []

                    return TokenValidationResult(
                        valid=True,
                        token_type="bearer",
                        account_info={
                            "models_count": len(models),
                        },
                    )
        except aiohttp.ClientError as e:
            return TokenValidationResult(valid=False, error=f"Validation request failed: {e}")

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """GLM API Key 不支持刷新"""
        return None
