# -*- coding: utf-8 -*-
"""
DeepSeek OAuth Adapter
参考 Chat2API src/main/oauth/adapters/deepseek.ts

认证方式: Bearer Token (localStorage.userToken)
验证端点: GET /api/v0/users/current
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

DEEPSEEK_API_BASE = "https://chat.deepseek.com"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": DEEPSEEK_API_BASE,
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Referer": f"{DEEPSEEK_API_BASE}/",
    "Sec-Ch-Ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "X-App-Version": "20241129.1",
    "X-Client-Locale": "zh-CN",
    "X-Client-Platform": "web",
    "X-Client-Version": "1.6.1",
}


class DeepSeekAdapter(BaseOAuthAdapter):
    provider_type = "deepseek"

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 DeepSeek Token (Bearer userToken)

        参考 Chat2API DeepSeekAdapter.validateToken:
        GET /api/v0/users/current
        返回: { code: 0, data: { biz_data: { id, email, name } } }
        """
        token = credentials.get("token") or credentials.get("userToken")
        if not token:
            return TokenValidationResult(valid=False, error="Token cannot be empty")

        # 拒绝 guest 账号
        if self.is_guest_account(token):
            return TokenValidationResult(valid=False, error="Guest account tokens are not supported")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DEEPSEEK_API_BASE}/api/v0/users/current",
                    headers={
                        "Authorization": f"Bearer {token}",
                        **FAKE_HEADERS,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.json()

                    if resp.status != 200 or not body:
                        return TokenValidationResult(valid=False, error="Token is invalid or expired")

                    data_field = body.get("data") or {}
                    biz_data = data_field.get("biz_data") or {}
                    if not biz_data:
                        return TokenValidationResult(valid=False, error="Token validation failed: Invalid response data")

                    return TokenValidationResult(
                        valid=True,
                        token_type="access",
                        account_info={
                            "user_id": biz_data.get("id"),
                            "email": biz_data.get("email"),
                            "name": biz_data.get("name"),
                        },
                    )
        except aiohttp.ClientError as e:
            return TokenValidationResult(valid=False, error=f"Validation request failed: {e}")

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """DeepSeek 支持从响应中获取新 Token"""
        token = credentials.get("token") or credentials.get("refreshToken")
        if not token:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DEEPSEEK_API_BASE}/api/v0/users/current",
                    headers={
                        "Authorization": f"Bearer {token}",
                        **FAKE_HEADERS,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.json()
                    if resp.status == 200 and body.get("data", {}).get("biz_data", {}).get("token"):
                        new_token = body["data"]["biz_data"]["token"]
                        return CredentialInfo(
                            type="access",
                            value=new_token,
                            expires_at=0,  # 未知过期时间
                        )
        except Exception:
            pass
        return None
