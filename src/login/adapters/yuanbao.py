# -*- coding: utf-8 -*-
"""
Yuanbao (腾讯元宝) OAuth Adapter
参考 Chat2API YuanbaoAdapter

认证方式: Cookie 全量 + x_token
验证端点: 直接用 Cookie 请求主页，检查是否包含 yuanbao 标识
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

YUANBAO_WEB_BASE = "https://yuanbao.tencent.com"


class YuanbaoAdapter(BaseOAuthAdapter):
    provider_type = "yuanbao"

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证腾讯元宝 Cookie + x_token

        直接用 Cookie 访问主页，检查 HTML 中是否包含 yuanbao
        """
        cookie = credentials.get("cookie")
        x_token = credentials.get("x_token")

        if not cookie:
            return TokenValidationResult(valid=False, error="Cookie cannot be empty")

        try:
            async with aiohttp.ClientSession() as session:
                # 先用 Cookie 访问主页
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Cookie": cookie,
                }
                if x_token:
                    headers["X-Token"] = x_token

                async with session.get(
                    f"{YUANBAO_WEB_BASE}/chat/",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.text()

                    if resp.status == 200 and len(body) > 200:
                        if "yuanbao" in body.lower() or "元宝" in body or "hunyuan" in body.lower():
                            return TokenValidationResult(
                                valid=True,
                                token_type="cookie",
                                account_info={
                                    "logged_in": True,
                                    "has_x_token": bool(x_token),
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

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """元宝 Cookie 不支持刷新"""
        return None
