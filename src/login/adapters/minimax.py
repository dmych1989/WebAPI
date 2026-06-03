# -*- coding: utf-8 -*-
"""
MiniMax OAuth Adapter
参考 Chat2API src/main/oauth/adapters/minimax.ts

认证方式: JWT Token (支持 realUserID+token 拼接)
验证端点: GET /v1/api/user/info (带签名)

注意: WebAPI 使用官方 API (https://api.minimaxi.com/v1)，
此适配器主要用于验证从浏览器提取的凭证。
"""

from __future__ import annotations

import hashlib
import time as _time
from typing import Optional

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

MINIMAX_API_BASE = "https://agent.minimaxi.com"

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": MINIMAX_API_BASE,
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _unix_timestamp() -> int:
    return int(_time.time())


class MiniMaxAdapter(BaseOAuthAdapter):
    provider_type = "minimax"

    def _extract_real_user_id(self, token: str) -> Optional[str]:
        """从 JWT payload 提取 realUserId / user.id"""
        payload = self.parse_jwt(token)
        if payload:
            # 嵌套 user.id
            user = payload.get("user", {})
            if isinstance(user, dict):
                return user.get("id")
            # 直接字段
            for key in ("realUserId", "real_user_id", "user_id", "userId", "id", "sub"):
                v = payload.get(key)
                if v:
                    return str(v)
        return None

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 MiniMax Token

        参考 Chat2API MiniMaxAdapter.validateToken:
        - 支持 token 格式: "jwtToken" 或 "realUserID+jwtToken"
        - GET /v1/api/user/info (带签名)
        - 需要构建特殊的签名头: x-timestamp, x-signature, yy
        """
        raw_token = credentials.get("token")
        if not raw_token:
            return TokenValidationResult(valid=False, error="Token cannot be empty")

        # 解析 token
        if "+" in raw_token:
            parts = raw_token.split("+", 1)
            real_user_id = parts[0]
            jwt_token = parts[1]
        else:
            jwt_token = raw_token
            real_user_id = self._extract_real_user_id(jwt_token) or ""

        if not real_user_id:
            return TokenValidationResult(valid=False, error="Could not extract realUserID from token")

        # 构建请求参数 (参考 Chat2API MiniMaxAdapter)
        unix = str(int(_time.time() * 1000))
        timestamp = _unix_timestamp()
        user_data = {
            "device_platform": "web",
            "biz_id": "3",
            "app_id": "3001",
            "version_code": "22201",
            "uuid": real_user_id,
            "device_id": None,
            "os_name": "Mac",
            "browser_name": "chrome",
            "device_memory": 8,
            "cpu_core_num": 11,
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "user_id": real_user_id,
            "screen_width": 1920,
            "screen_height": 1080,
            "unix": unix,
            "lang": "zh",
            "token": jwt_token,
        }

        # 构建 query string
        query_parts = []
        for key, value in user_data.items():
            if value is None:
                continue
            query_parts.append(f"{key}={value}")
        query_str = "&".join(query_parts)

        uri = "/v1/api/user/info"
        full_uri = f"{uri}?{query_str}"
        data_json = "{}"
        yy = _md5(f"{full_uri}_{data_json}{_md5(unix)}ooui")
        signature = _md5(f"{timestamp}{jwt_token}{data_json}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{MINIMAX_API_BASE}{full_uri}",
                    headers={
                        "Referer": f"{MINIMAX_API_BASE}/",
                        "token": jwt_token,
                        **FAKE_HEADERS,
                        "Content-Type": "application/json",
                        "x-timestamp": str(timestamp),
                        "x-signature": signature,
                        "yy": yy,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.json()
                    status_info = body.get("statusInfo", {})
                    code = status_info.get("code")

                    if resp.status != 200 or code != 0:
                        return TokenValidationResult(
                            valid=False,
                            error=status_info.get("message") or "Token is invalid or expired",
                        )

                    user_info = body.get("data", {}).get("userInfo") or body.get("data", {})

                    return TokenValidationResult(
                        valid=True,
                        token_type="jwt",
                        account_info={
                            "user_id": real_user_id or user_info.get("id"),
                            "name": user_info.get("name") or user_info.get("nickname"),
                            "email": user_info.get("email"),
                        },
                    )
        except aiohttp.ClientError as e:
            return TokenValidationResult(valid=False, error=f"Validation request failed: {e}")

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """MiniMax JWT 不支持刷新"""
        return None
