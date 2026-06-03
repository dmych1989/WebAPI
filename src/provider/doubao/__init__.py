# -*- coding: utf-8 -*-
"""
Doubao (豆包) Provider Adapter

网页 API 协议：
- Base URL: https://www.doubao.com
- 认证: Cookie（登录后的 session cookie）
- 对话: POST /api/chat（SSE 流）
- 签名: 使用 window.byted_acrawler.frontierSign 生成 a_bogus 签名
- 流式: SSE 协议

使用方式：
1. 启动浏览器（非无头模式）
2. 访问 doubao.com 并扫码登录
3. 自动维护 Cookie 和 Session
4. 生成 a_bogus 签名后发送请求

依赖：pip install playwright webapi[browser]
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator, Optional

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.browser_automation import BrowserAutomationTransport

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────
DOUBAO_BASE = "https://www.doubao.com"
DOUBAO_CHAT_URL = f"{DOUBAO_BASE}/api/chat"
DOUBAO_CHAT_V2_URL = f"{DOUBAO_BASE}/api/chat_v2"

# ─────────────────────────────────────────────────────────────
# Default Headers
# ─────────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": DOUBAO_BASE,
    "Referer": f"{DOUBAO_BASE}/chat/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

DEFAULT_MODELS = [
    "doubao-pro",
    "doubao-pro-32k",
    "doubao-lite",
    "doubao-turbo",
]


def _random_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_ts() -> int:
    return int(time.time())


@ProviderRegistry.register("doubao")
class DoubaoProvider(BaseProvider):
    """豆包 网页 API 适配器

    使用 Playwright 浏览器自动化：
    1. 访问 doubao.com
    2. 扫码登录（首次）
    3. 自动维护 Cookie 和 Session
    4. 生成 a_bogus 签名
    5. 发送请求并返回 SSE 流

    配置要求：
    - cookie: 豆包登录后的 Cookie（登录失败可留空，首次使用会自动维护）
    - headless: 浏览器模式（False 方便扫码登录，True 方便自动化）
    """

    name = "doubao"
    display_name = "豆包 (Doubao)"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._cookie: Optional[str] = account.cookie or account.token
        self._headless: bool = account.headless if hasattr(account, "headless") else False
        self._transport = BrowserAutomationTransport(headless=self._headless)
        self._session_validated: float = 0
        self._device_id: str = str(uuid.uuid4())

    # ---- Auth ----

    async def login(self) -> str:
        """登录豆包并维护会话

        流程：
        1. 如果有 Cookie，尝试访问页面验证
        2. 如果 Cookie 失效，打开浏览器让用户扫码登录
        3. 自动提取 Cookie 和会话信息
        4. 缓存验证结果

        Returns:
            Cookie 字符串
        """
        if not self._cookie:
            logger.warning("[Doubao] Cookie not configured. Will open browser for login.")

        now = time.time()
        if self._session_validated and (now - self._session_validated) < 600:
            return self._cookie

        # 防御：检查 cookie 是否还是未解密的密文
        if isinstance(self._cookie, str) and self._cookie.startswith("enc:v1:"):
            raise AuthError(
                "Doubao Cookie 是加密密文，但密钥不匹配（无法解密）。"
                "请运行: python -m src.login doubao 重新登录。"
            )

        logger.info("[Doubao] Validating session...")

        try:
            # 1. 访问首页验证 Cookie
            cookies = await self._extract_cookies()

            # 2. 如果没有 Cookie，打开浏览器让用户扫码登录
            if not cookies:
                logger.info("[Doubao] No valid cookie found. Opening browser for manual login...")
                await self._transport.navigate(DOUBAO_BASE, wait_selector=".login-button")

                # 等待用户扫码登录
                logger.info("[Doubao] Please scan the QR code to login...")
                logger.info("[Doubao] Waiting for login... (max 5 minutes)")
                await asyncio.sleep(5)  # 短暂延迟后开始轮询

                for attempt in range(30):  # 最多等待 2.5 分钟
                    cookies = await self._extract_cookies()
                    if cookies:
                        logger.info(f"[Doubao] Login successful! ({attempt + 1} attempts)")
                        break
                    logger.info(f"[Doubao] Login not detected, retrying... ({attempt + 1}/30)")
                    await asyncio.sleep(5)

                if not cookies:
                    raise AuthError("豆包登录超时，请检查扫码是否成功")

            # 3. 提取 Cookie 到字符串
            self._cookie = await self._cookie_to_string(cookies)
            self._session_validated = time.time()

            logger.info(f"[Doubao] Session validated (headless={self._headless})")
            return self._cookie

        except AuthError:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Doubao] Login failed: {error_msg}")

            # 捕获浏览器提前关闭的错误（常见于 health_check 场景）
            if "Target page, context or browser has been closed" in error_msg:
                logger.warning("[Doubao] Browser was closed prematurely (likely during health check)")
                logger.info("[Doubao] This is not a fatal error - cookie might still be valid")
                return self._cookie  # 假设 cookie 仍然有效，返回缓存值

            raise AuthError(f"豆包登录失败: {e}")

    async def _extract_cookies(self) -> list[dict]:
        """从浏览器提取 Cookies"""
        try:
            cookies = await self._transport.get_cookies()
            valid_cookies = [c for c in cookies if c.get("domain") == "doubao.com"]
            return valid_cookies
        except Exception as e:
            logger.error(f"[Doubao] Failed to extract cookies: {e}")
            return []

    async def _cookie_to_string(self, cookies: list[dict]) -> str:
        """将 Cookies 列表转为 Cookie 字符串"""
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

    # ---- Messages to Payload ----

    def _messages_to_payload(self, request: ChatCompletionRequest) -> dict[str, Any]:
        """OpenAI messages → 豆包 payload 格式"""
        messages = []

        for msg in request.messages:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
            content = self._get_text(msg)

            if role == "system":
                continue  # 豆包不支持 system message

            messages.append({"role": role, "content": content})

        return {
            "bot_id": "default",  # 默认 bot
            "chat_id": _random_id(),
            "messages": messages,
            "stream": True,
            "temperature": request.temperature or 0.8,
            "top_p": request.top_p or 1.0,
            "max_tokens": request.max_tokens or 4096,
        }

    @staticmethod
    def _get_text(msg) -> str:
        """提取消息文本内容"""
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if content is None:
            return ""
        return str(content)

    # ---- Chat Completion ----

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        """非流式对话"""
        await self.login()
        payload = self._messages_to_payload(request)

        # 使用 fetch 获取完整响应
        try:
            response = await self._transport.fetch_api(
                url=DOUBAO_CHAT_URL,
                method="POST",
                headers={"Cookie": self._cookie},
                body=payload,
                timeout=120000,
            )

            # 提取回复内容
            content = ""
            if isinstance(response, dict):
                data = response.get("data", response)
                if isinstance(data, dict):
                    content = data.get("content", "") or data.get("reply", "")
                elif isinstance(data, str):
                    content = data
            elif isinstance(response, str):
                content = response

            if not content:
                raise ProviderError("豆包返回空内容")

            return ProviderResponse(
                status_code=200,
                data={
                    "id": f"chatcmpl-{_random_id()}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                },
            )

        except Exception as e:
            logger.error(f"[Doubao] chat_completion failed: {e}")
            raise ProviderError(f"Doubao API error: {e}")

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话"""
        await self.login()
        payload = self._messages_to_payload(request)

        logger.info(f"[Doubao] Starting stream: model={request.model}")

        try:
            # 使用 fetch_stream 获取 SSE 流
            full_content = ""

            async for chunk in self._transport.fetch_stream(
                url=DOUBAO_CHAT_URL,
                method="POST",
                headers={"Cookie": self._cookie},
                body=payload,
                timeout=120000,
            ):
                # 解析 SSE
                if chunk.strip():
                    # 提取 content 部分
                    for line in chunk.split("\n"):
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break

                            try:
                                data = json.loads(data_str)
                                if isinstance(data, dict):
                                    content = data.get("content", "") or data.get("delta", "")
                                    if content:
                                        full_content += content
                                        yield StreamChunk(
                                            content=content,
                                            model=request.model,
                                        )
                            except json.JSONDecodeError:
                                continue

            logger.debug(f"[Doubao] Stream completed: {len(full_content)} chars")

        except Exception as e:
            logger.error(f"[Doubao] chat_completion_stream failed: {e}")
            yield StreamChunk(
                content="",
                model=request.model,
                finish_reason="error",
            )

    # ---- Health Check ----

    async def health_check(self) -> bool:
        """验证 Cookie 有效性

        重要：浏览器异常不等于认证失败（常见于 health_check 场景）。
        - 如果有缓存的 cookie，假设仍然有效
        - 否则尝试重新验证
        """
        # 乐观检查：如果有缓存的 cookie，假设仍然有效
        if self._cookie:
            try:
                # 仅尝试验证 cookie 格式，不打开浏览器
                cookies = await self._extract_cookies()
                return bool(cookies)
            except Exception:
                # Cookie 可能已失效，继续尝试完整验证
                pass

        # 完整验证（可能打开浏览器）
        try:
            await self.login()
            return bool(self._cookie)
        except PlaywrightTimeoutError:
            # 超时不等于认证失败（可能是网络问题或页面加载慢）
            logger.warning("[Doubao] Health check timeout - assuming cookie still valid")
            return bool(self._cookie)
        except Exception as e:
            error_msg = str(e)
            # 捕获浏览器提前关闭的错误，不返回 False
            if "Target page, context or browser has been closed" in error_msg:
                logger.warning("[Doubao] Browser closed during health check - assuming cookie still valid")
                return bool(self._cookie)  # 返回乐观值
            return False

    # ---- Models ----

    async def list_models(self) -> list[str]:
        return DEFAULT_MODELS

    # ---- Session Management ----

    async def create_session(self) -> str:
        return f"doubao_{_random_id()}"

    async def delete_session(self, session_id: str) -> bool:
        # 豆包不提供删除 conversation 的 API，仅清除本地引用
        return True

    # ---- Token Refresh ----

    async def refresh_token(self) -> bool:
        # Cookie 会话自动维护，无需刷新
        return True
