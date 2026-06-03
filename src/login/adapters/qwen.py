# -*- coding: utf-8 -*-
"""
Qwen OAuth Adapter
参考 Chat2API src/main/oauth/adapters/qwen.ts

认证方式: Cookie (tongyi_sso_ticket)
验证端点: POST /api/v2/session/page/list
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

QWEN_API_BASE = "https://chat2-api.qianwen.com"
QWEN_WEB_BASE = "https://www.qianwen.com"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": QWEN_WEB_BASE,
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="145", "Not(A:Brand";v="24", "Google Chrome";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Referer": f"{QWEN_WEB_BASE}/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}


class QwenAdapter(BaseOAuthAdapter):
    provider_type = "qwen"

    def _generate_cookie(self, ticket: str) -> str:
        return f"tongyi_sso_ticket={ticket}"

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 Qwen tongyi_sso_ticket

        参考 Chat2API QwenAdapter.validateToken:
        POST /api/v2/session/page/list
        Headers: Cookie: tongyi_sso_ticket=<ticket>
        返回: { success: true/false, errorCode, errorMsg, data }
        """
        ticket = credentials.get("ticket") or credentials.get("tongyi_sso_ticket")
        if not ticket:
            return TokenValidationResult(valid=False, error="Ticket cannot be empty")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{QWEN_API_BASE}/api/v2/session/page/list",
                    json={},
                    headers={
                        "Cookie": self._generate_cookie(ticket),
                        **DEFAULT_HEADERS,
                        "X-Platform": "pc_tongyi",
                        "X-DeviceId": "5b68c267-cd8e-fd0e-148a-18345bc9a104",
                    },
                    params={
                        "biz_id": "ai_qwen",
                        "chat_client": "h5",
                        "device": "pc",
                        "fr": "pc",
                        "pr": "qwen",
                        "ut": "5b68c267-cd8e-fd0e-148a-18345bc9a104",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.json()

                    if resp.status != 200:
                        return TokenValidationResult(valid=False, error="Ticket is invalid or expired")

                    success = body.get("success", False)
                    if not success:
                        return TokenValidationResult(
                            valid=False,
                            error=body.get("errorMsg") or f"Validation failed: {body.get('errorCode')}",
                        )

                    return TokenValidationResult(
                        valid=True,
                        token_type="cookie",
                        account_info=body.get("data"),
                    )
        except aiohttp.ClientError as e:
            return TokenValidationResult(valid=False, error=f"Validation request failed: {e}")

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """Qwen tongyi_sso_ticket 不支持刷新"""
        return None
