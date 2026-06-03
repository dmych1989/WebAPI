# -*- coding: utf-8 -*-
"""
GLM (Zhipu AI ChatGLM) OAuth Adapter
参考 Chat2API src/main/oauth/adapters/glm.ts

认证方式: refresh_token（从 chatglm.cn localStorage 获取）
验证端点: POST /chatglm/user-api/user/refresh（带专用签名）

GLM 登录流程（对齐 Chat2API）：
  1. 浏览器打开 chatglm.cn，用户手动登录
  2. 从 localStorage.token 提取 refresh_token
  3. 用 refresh_token 调用 /user/refresh 获取 access_token
  4. 用 access_token 调用 /user/info 获取用户信息
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Optional

import aiohttp
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo

GLM_API_BASE = "https://chatglm.cn"

FAKE_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "App-Name": "chatglm",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json",
    "Origin": GLM_API_BASE,
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-App-Fr": "browser_extension",
    "X-App-Platform": "pc",
    "X-App-Version": "0.0.1",
    "X-Device-Brand": "",
    "X-Device-Model": "",
    "X-Lang": "zh",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
}

# GLM 专用签名密钥（对齐 Chat2API）
SIGN_SECRET = "8a1317a7468aa3ad86e997d08f3f31cb"


def _generate_sign() -> tuple[str, str, str]:
    """生成 GLM 专用签名（对齐 Chat2API generateSign）

    算法: timestamp 由 Date.now() 的数字和拼接组成
    - 取 timestamp 前 len-2 位 + (各位之和 - 最后第二位) + 最后一位
    - nonce = uuid 去掉连字符
    - sign = md5(timestamp-nonce-SIGN_SECRET)
    """
    now = int(time.time() * 1000)
    A = str(now)
    t = len(A)
    digits = [int(c) for c in A]
    total = sum(digits) - digits[t - 2]
    a_digit = total % 10
    timestamp = A[: t - 2] + str(a_digit) + A[t - 1 :]
    nonce = uuid.uuid4().hex.replace("-", "")
    raw_sign = f"{timestamp}-{nonce}-{SIGN_SECRET}"
    sign = hashlib.md5(raw_sign.encode()).hexdigest()
    return timestamp, nonce, sign


def _generate_device_id() -> str:
    return uuid.uuid4().hex.replace("-", "")


class GLMAdapter(BaseOAuthAdapter):
    provider_type = "glm"

    def _extract_refresh_token(self, credentials: dict) -> Optional[str]:
        """从多种 key 提取 refresh_token（对齐 Chat2API）"""
        return (
            credentials.get("chatglm_refresh_token")
            or credentials.get("refreshToken")
            or credentials.get("refresh_token")
            or credentials.get("token")
        )

    async def _call_refresh(self, refresh_token: str) -> Optional[dict]:
        """调用 GLM refresh 接口（对齐 Chat2API refreshToken）"""
        timestamp, nonce, sign = _generate_sign()
        device_id = _generate_device_id()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GLM_API_BASE}/chatglm/user-api/user/refresh",
                    json={},
                    headers={
                        "Authorization": f"Bearer {refresh_token}",
                        "X-Device-Id": device_id,
                        "X-Nonce": nonce,
                        "X-Request-Id": uuid.uuid4().hex.replace("-", ""),
                        "X-Sign": sign,
                        "X-Timestamp": timestamp,
                        **FAKE_HEADERS,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return data.get("result") or data
        except aiohttp.ClientError:
            return None

    async def _get_user_info(self, access_token: str) -> Optional[dict]:
        """获取 GLM 用户信息（对齐 Chat2API getUserInfo）"""
        timestamp, nonce, sign = _generate_sign()
        device_id = _generate_device_id()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{GLM_API_BASE}/chatglm/user-api/user/info",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Device-Id": device_id,
                        "X-Request-Id": uuid.uuid4().hex.replace("-", ""),
                        "X-Sign": sign,
                        "X-Timestamp": timestamp,
                        "X-Nonce": nonce,
                        **FAKE_HEADERS,
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return data.get("result") or data
        except aiohttp.ClientError:
            return None

    def _is_guest_account(self, user_info: Optional[dict]) -> bool:
        """检测访客账号（对齐 Chat2API 访客检测逻辑）"""
        if not user_info:
            return True
        nickname = user_info.get("nickname", "")
        email = user_info.get("email", "")
        is_guest = user_info.get("is_guest")
        phone = user_info.get("phone")
        # 任何字段显示为访客均拒绝
        if is_guest is True:
            return True
        if nickname and "访客" in nickname:
            return True
        if email and "@guest" in email:
            return True
        # 无 phone 无 email 视为访客
        if not phone and not email:
            return True
        return False

    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证 GLM ChatGLM refresh_token（对齐 Chat2API validateToken）

        流程:
        1. 用 refresh_token 调用 /user/refresh 获取 access_token
        2. 用 access_token 调用 /user/info 获取用户信息
        3. 检查是否为访客账号
        """
        refresh_token = self._extract_refresh_token(credentials)
        if not refresh_token:
            return TokenValidationResult(valid=False, error="Refresh Token cannot be empty")

        # Step 1: 刷新 access_token
        result = await self._call_refresh(refresh_token)
        if not result:
            return TokenValidationResult(
                valid=False,
                error="Refresh Token is invalid or expired (refresh failed)",
            )

        access_token = result.get("access_token")
        if not access_token:
            return TokenValidationResult(
                valid=False,
                error="Token validation failed: Unable to get access_token",
            )

        # 检查访客
        if result.get("is_guest") is True:
            return TokenValidationResult(
                valid=False,
                error="Guest account not allowed, please login with a real account",
            )

        # Step 2: 获取用户信息
        user_info = await self._get_user_info(access_token)

        if self._is_guest_account(user_info):
            return TokenValidationResult(
                valid=False,
                error="Guest account not allowed, please login with a real account",
            )

        nickname = user_info.get("nickname") if user_info else None
        email = user_info.get("email") if user_info else None
        phone = user_info.get("phone") if user_info else None

        return TokenValidationResult(
            valid=True,
            token_type="refresh",
            account_info={
                "user_id": result.get("user_id") or (user_info.get("user_id") if user_info else None),
                "email": email or "",
                "name": nickname or phone or email or str(result.get("user_id", "")),
                "nickname": nickname,
                "phone": phone,
            },
        )

    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """用 refresh_token 获取新 access_token（对齐 Chat2API refreshToken）"""
        refresh_token = self._extract_refresh_token(credentials)
        if not refresh_token:
            return None

        result = await self._call_refresh(refresh_token)
        if not result or not result.get("access_token"):
            return None

        return CredentialInfo(
            type="access",
            value=result["access_token"],
            refresh_token=result.get("refresh_token"),
            expires_at=int(time.time()) + 3600,
        )
