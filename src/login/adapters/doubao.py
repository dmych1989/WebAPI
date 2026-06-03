# -*- coding: utf-8 -*-
"""
Doubao OAuth Adapter
参考 Chat2API DoubaoAdapter

认证方式: Cookie 全量
验证端点: 直接用 Cookie 请求主页，检查是否包含 doubao 关键字
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

DOUBAO_WEB_BASE = "https://www.doubao.com"


class DoubaoAdapter(BaseOAuthAdapter):
    provider_type = "doubao"

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证豆包 Cookie

        直接用 Cookie 访问主页，检查 HTML 中是否包含 doubao
        （Cookie 有效则响应包含登录态的 HTML）
        """
        cookie = credentials.get("cookie")
        if not cookie:
            return TokenValidationResult(valid=False, error="Cookie cannot be empty")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DOUBAO_WEB_BASE}/chat/",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                        "Cookie": cookie,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.text()

                    if resp.status == 200 and len(body) > 200:
                        # 检查是否包含 doubao 标识（Cookie 有效通常有登录态）
                        if "doubao" in body.lower() or "豆包" in body:
                            return TokenValidationResult(
                                valid=True,
                                token_type="cookie",
                                account_info={"logged_in": True},
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

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """豆包 Cookie 不支持刷新"""
        return None
