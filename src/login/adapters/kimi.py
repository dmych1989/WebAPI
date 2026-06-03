# -*- coding: utf-8 -*-
"""
Kimi OAuth Adapter
参考 Chat2API src/main/oauth/adapters/kimi.ts

认证方式: Bearer JWT Token
验证端点: POST /apiv2/kimi.gateway.order.v1.SubscriptionService/GetSubscription (gRPC JSON)
"""

from __future__ import annotations

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

KIMI_API_BASE = "https://www.kimi.com"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": KIMI_API_BASE,
    "R-Timezone": "Asia/Shanghai",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Priority": "u=1, i",
    "X-Msh-Platform": "web",
}


class KimiAdapter(BaseOAuthAdapter):
    provider_type = "kimi"

    def _detect_token_type(self, token: str) -> str:
        """检测 Token 类型: jwt | refresh"""
        if token.startswith("eyJ") and token.count(".") == 2:
            payload = self.parse_jwt(token)
            if payload and payload.get("app_id") == "kimi" and payload.get("typ") == "access":
                return "jwt"
        return "refresh"

    def _extract_device_id(self, token: str) -> Optional[str]:
        """从 JWT 提取 device_id"""
        payload = self.parse_jwt(token)
        return payload.get("device_id") if payload else None

    def _extract_session_id(self, token: str) -> Optional[str]:
        """从 JWT 提取 ssid"""
        payload = self.parse_jwt(token)
        return payload.get("ssid") if payload else None

    def _extract_user_id(self, token: str) -> Optional[str]:
        """从 JWT 提取 sub (user_id)"""
        payload = self.parse_jwt(token)
        return payload.get("sub") if payload else None

    def _get_headers(self, token: Optional[str] = None, device_id: Optional[str] = None) -> dict:
        """构建请求头"""
        import uuid as _uuid
        headers = {
            **FAKE_HEADERS,
            "X-Msh-Device-Id": device_id or str(_uuid.uuid4()),
            "X-Msh-Session-Id": str(_uuid.uuidint() if hasattr(_uuid, "uuidint") else 0),
            "Connect-Protocol-Version": "1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _call_grpc_api(self, token: str, service: str, body: dict) -> Optional[dict]:
        """调用 Kimi gRPC JSON API"""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            **FAKE_HEADERS,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{KIMI_API_BASE}{service}",
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except aiohttp.ClientError:
            return None

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 Kimi Token

        参考 Chat2API KimiAdapter.validateToken:
        - 兼容多种 key: accessToken, token, access_token, apiKey, api_key
        - POST /apiv2/kimi.gateway.order.v1.SubscriptionService/GetSubscription
        - 返回 subscription.userId, subscription.userName
        """
        # 兼容多种 key 名称
        token = (
            credentials.get("accessToken")
            or credentials.get("token")
            or credentials.get("access_token")
            or credentials.get("apiKey")
            or credentials.get("api_key")
        )
        if not token:
            return TokenValidationResult(valid=False, error="Token cannot be empty")

        if self.is_guest_account(token):
            return TokenValidationResult(valid=False, error="Guest account tokens are not supported")

        token_type = self._detect_token_type(token)
        user_id = self._extract_user_id(token)

        # 调用订阅 API 验证
        result = await self._call_grpc_api(
            token,
            "/apiv2/kimi.gateway.order.v1.SubscriptionService/GetSubscription",
            {},
        )

        if not result or "subscription" not in result:
            return TokenValidationResult(valid=False, error="Token is invalid or expired")

        subscription = result.get("subscription") or {}
        return TokenValidationResult(
            valid=True,
            token_type=token_type,
            account_info={
                "user_id": subscription.get("userId") or user_id,
                "name": subscription.get("userName"),
            },
        )

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """Kimi 不再支持 refresh token"""
        return None
