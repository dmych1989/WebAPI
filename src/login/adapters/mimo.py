# -*- coding: utf-8 -*-
"""
MiMo (Xiaomi AI Studio) OAuth Adapter
参考 Chat2API src/main/oauth/adapters/mimo.ts

认证方式: Cookie 全量（serviceToken, userId, xiaomichatbot_ph）
验证端点: 直接用 Cookie 请求主页，检查登录态
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

MIMO_WEB_BASE = "https://aistudio.xiaomimimo.com"


class MiMoAdapter(BaseOAuthAdapter):
    provider_type = "mimo"

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 MiMo Cookie

        参考 Chat2API MiMoAdapter.validateToken:
        - 需要 3 个字段: serviceToken, userId, xiaomichatbot_ph
        - 用 Cookie 访问主页检查登录态
        """
        service_token = (
            credentials.get("serviceToken")
            or credentials.get("service_token")
            or credentials.get("token")
        )
        user_id = credentials.get("userId") or credentials.get("user_id")
        ph_token = (
            credentials.get("xiaomichatbot_ph")
            or credentials.get("ph_token")
            or credentials.get("phToken")
        )

        # 必须有 3 个字段
        if not service_token:
            return TokenValidationResult(valid=False, error="Missing required field: serviceToken")
        if not user_id:
            return TokenValidationResult(valid=False, error="Missing required field: userId")
        if not ph_token:
            return TokenValidationResult(valid=False, error="Missing required field: xiaomichatbot_ph")

        # 长度检查
        if len(service_token) < 10:
            return TokenValidationResult(valid=False, error="serviceToken format appears invalid (too short)")
        if len(ph_token) < 10:
            return TokenValidationResult(valid=False, error="xiaomichatbot_ph format appears invalid (too short)")

        cookie = (
            f"serviceToken={service_token}; "
            f"userId={user_id}; "
            f"xiaomichatbot_ph={ph_token}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{MIMO_WEB_BASE}/",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                        "Cookie": cookie,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.text()

                    if resp.status == 200 and len(body) > 200:
                        if "mimo" in body.lower() or "MiMo" in body:
                            return TokenValidationResult(
                                valid=True,
                                token_type="cookie",
                                account_info={
                                    "user_id": user_id,
                                    "logged_in": True,
                                },
                            )
                        return TokenValidationResult(
                            valid=False,
                            error="Cookie may be invalid (no login state detected)",
                        )
                    return TokenValidationResult(
                        valid=False,
                        error=f"Cookie validation failed (HTTP {resp.status})",
                    )
        except aiohttp.ClientError as e:
            return TokenValidationResult(valid=False, error=f"Validation request failed: {e}")

    async def refresh_token(self, credentials: dict) -> CredentialInfo | None:
        """MiMo Cookie 不支持刷新"""
        return None
