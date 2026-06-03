# -*- coding: utf-8 -*-
"""
Yuanbao (腾讯元宝) Provider Adapter

网页 API 协议:
- Base URL: https://yuanbao.tencent.com
- 认证: Cookie（登录后的 session cookie）+ 自动维护 x-uskey 等请求头
- 对话: POST /api/chat/send（SSE 流）
- 模型: hunyuan-pro, hunyuan-turbo, hunyuan-lite, hunyuan-t1

使用 Playwright 浏览器自动化：
1. 启动浏览器并访问 yuanbao.tencent.com
2. 扫码登录（首次）
3. 自动维护 Cookie 和 x-uskey 等请求头
4. 使用 fetch API 发送请求

依赖：pip install playwright webapi[browser]
"""

from __future__ import annotations

import asyncio
import json
import re
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
YUANBAO_BASE = "https://yuanbao.tencent.com"
YUANBAO_CHAT_URL = f"{YUANBAO_BASE}/api/chat/send"

# ─────────────────────────────────────────────────────────────
# Default Headers
# ─────────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": YUANBAO_BASE,
    "Referer": f"{YUANBAO_BASE}/chat/",
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
    "hunyuan-pro",
    "hunyuan-turbo",
    "hunyuan-lite",
    "hunyuan-t1",
    "deepseek-v3",
    "deepseek-r1",
]

# 模型映射：用户友好的名称 → 元宝内部 model_id
MODEL_MAP: dict[str, str] = {
    "hunyuan-pro": "hunyuan-pro",
    "hunyuan-turbo": "hunyuan-turbo",
    "hunyuan-lite": "hunyuan-lite",
    "hunyuan-t1": "hunyuan-t1",
    "deepseek-v3": "deepseek-v3",
    "deepseek-r1": "deepseek-r1",
    # 别名
    "pro": "hunyuan-pro",
    "turbo": "hunyuan-turbo",
    "lite": "hunyuan-lite",
    "t1": "hunyuan-t1",
}


def _random_hex(length: int) -> str:
    return uuid.uuid4().hex[:length]


def _now_ts() -> int:
    return int(time.time())


@ProviderRegistry.register("yuanbao")
class YuanbaoProvider(BaseProvider):
    """腾讯元宝 (Yuanbao) 网页 API 适配器

    使用 Playwright 浏览器自动化：
    1. 访问 yuanbao.tencent.com
    2. 扫码登录（首次）
    3. 自动维护 Cookie 和 x-uskey 等请求头
    4. 使用 fetch API 发送请求

    配置要求：
    - cookie: 腾讯元宝登录后的 Cookie（可选，首次使用会自动维护）
    - headless: 浏览器模式（False 方便扫码登录，True 方便自动化）
    """

    name = "yuanbao"
    display_name = "腾讯元宝 (Yuanbao)"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._cookie: Optional[str] = account.cookie or account.token
        self._headless: bool = account.headless if hasattr(account, "headless") else False
        self._transport = BrowserAutomationTransport(headless=self._headless)
        self._session_validated: float = 0
        self._x_id: Optional[str] = None
        self._x_token: Optional[str] = None
        self._hy_token: Optional[str] = None

    # ---- Auth ----

    async def login(self) -> str:
        """登录腾讯元宝并维护会话

        流程：
        1. 如果有 Cookie，尝试访问页面验证
        2. 如果 Cookie 失效，打开浏览器让用户扫码登录
        3. 自动提取 Cookie、X-ID、X-Token
        4. 缓存验证结果

        Returns:
            Cookie 字符串
        """
        if not self._cookie:
            logger.warning("[Yuanbao] Cookie not configured. Will open browser for login.")

        now = time.time()
        if self._session_validated and self._x_token and (now - self._session_validated) < 600:
            return self._cookie

        # 防御：检查 cookie 是否还是未解密的密文
        if isinstance(self._cookie, str) and self._cookie.startswith("enc:v1:"):
            raise AuthError(
                "Yuanbao Cookie 是加密密文，但密钥不匹配（无法解密）。"
                "请运行: python -m src.login yuanbao 重新登录。"
            )

        logger.info("[Yuanbao] Validating session...")

        try:
            # 1. 访问首页验证 Cookie 并提取 Token
            await self._transport.navigate(f"{YUANBAO_BASE}/chat/")

            # 2. 提取页面中的 Token 信息
            await self._extract_tokens_from_page()

            # 3. 如果没有 Token，可能需要登录
            if not self._x_token:
                logger.info("[Yuanbao] No valid token found. Opening browser for manual login...")

                # 等待用户扫码登录
                logger.info("[Yuanbao] Please scan the QR code to login...")
                logger.info("[Yuanbao] Waiting for login... (max 5 minutes)")

                for attempt in range(30):  # 最多等待 2.5 分钟
                    await asyncio.sleep(5)
                    await self._extract_tokens_from_page()
                    if self._x_token:
                        logger.info(f"[Yuanbao] Login successful! ({attempt + 1} attempts)")
                        break
                    logger.info(f"[Yuanbao] Login not detected, retrying... ({attempt + 1}/30)")

                if not self._x_token:
                    raise AuthError("元宝登录超时，请检查扫码是否成功")

            # 4. 提取 Cookie
            cookies = await self._transport.get_cookies()
            self._cookie = await self._cookie_to_string(cookies)

            self._session_validated = time.time()

            logger.info(
                f"[Yuanbao] Session validated "
                f"(x_id={'✓' if self._x_id else '✗'} "
                f"x_token={'✓' if self._x_token else '✗'})"
            )
            return self._cookie

        except AuthError:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Yuanbao] Login failed: {error_msg}")

            # 捕获浏览器提前关闭的错误（常见于 health_check 场景）
            if "Target page, context or browser has been closed" in error_msg:
                logger.warning("[Yuanbao] Browser was closed prematurely (likely during health check)")
                logger.info("[Yuanbao] This is not a fatal error - cookie might still be valid")
                return self._cookie  # 假设 cookie 仍然有效，返回缓存值

            raise AuthError(f"元宝登录失败: {e}")

    async def _extract_tokens_from_page(self) -> None:
        """从页面中提取 X-ID 和 X-Token"""
        try:
            # 尝试从页面 URL 或 DOM 中提取 token
            tokens = await self._transport.execute_js(
                """
                () => {
                    // 方法 1: 从 __NEXT_DATA__ 中提取
                    const nextData = document.getElementById('__NEXT_DATA__');
                    if (nextData) {
                        try {
                            const data = JSON.parse(nextData.textContent);
                            const xId = data?.props?.pageProps?.x_id || '';
                            const xToken = data?.props?.pageProps?.x_token || '';
                            if (xId || xToken) {
                                return { x_id: xId, x_token: xToken };
                            }
                        } catch (e) {}
                    }

                    // 方法 2: 从 cookie 中提取 hy_token
                    const cookies = document.cookie.split(';');
                    for (const cookie of cookies) {
                        const [name, value] = cookie.trim().split('=');
                        if (name === 'hy_token') {
                            return { x_id: '', x_token: value };
                        }
                    }

                    // 方法 3: 从 localStorage 中提取
                    try {
                        const userInfo = localStorage.getItem('userInfo');
                        if (userInfo) {
                            const data = JSON.parse(userInfo);
                            return {
                                x_id: data.x_id || '',
                                x_token: data.x_token || data.token || '',
                            };
                        }
                    } catch (e) {}

                    // 方法 4: 检查页面是否在登录页
                    const loginButton = document.querySelector('.login-button, [class*="login"]');
                    if (loginButton) {
                        return { x_id: '', x_token: '' };
                    }

                    return { x_id: '', x_token: '' };
                }
                """
            )

            if tokens:
                self._x_id = tokens.get("x_id", "") or None
                self._x_token = tokens.get("x_token", "") or None

        except Exception as e:
            logger.debug(f"[Yuanbao] Failed to extract tokens: {e}")

    async def _cookie_to_string(self, cookies: list[dict]) -> str:
        """将 Cookies 列表转为 Cookie 字符串"""
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

    def _auth_headers(self) -> dict:
        """构建认证 headers"""
        headers = {}
        if self._cookie:
            headers["Cookie"] = self._cookie
        if self._x_id:
            headers["X-ID"] = self._x_id
        if self._x_token:
            headers["X-Token"] = self._x_token
        return headers

    # ---- Messages → Payload ----

    def _messages_to_prompt(self, request: ChatCompletionRequest) -> str:
        """OpenAI messages → 元宝 prompt 格式"""
        parts: list[str] = []
        for msg in request.messages:
            role = msg.role
            content = self._get_text(msg)

            if role == "system":
                parts.append(f"系统: {content}")
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(content)
            elif role == "tool":
                parts.append(f"[工具返回] {content}")

        return "\n\n".join(parts)

    @staticmethod
    def _get_text(msg) -> str:
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

    def _resolve_model(self, request: ChatCompletionRequest) -> str:
        """解析实际模型名"""
        model_lower = request.model.lower()

        # 精确匹配
        if model_lower in MODEL_MAP:
            return MODEL_MAP[model_lower]

        # 模糊匹配
        if "pro" in model_lower:
            return "hunyuan-pro"
        if "turbo" in model_lower:
            return "hunyuan-turbo"
        if "t1" in model_lower:
            return "hunyuan-t1"
        if "lite" in model_lower:
            return "hunyuan-lite"
        if "deepseek-v3" in model_lower or "ds-v3" in model_lower:
            return "deepseek-v3"
        if "deepseek-r1" in model_lower or "ds-r1" in model_lower:
            return "deepseek-r1"

        return self.account.models[0] if self.account.models else "hunyuan-pro"

    # ---- Chat Completion ----

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        """非流式对话"""
        await self.login()
        model = self._resolve_model(request)
        prompt = self._messages_to_prompt(request)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "temperature": request.temperature or 0.8,
            "max_tokens": request.max_tokens or 4096,
            "chat_id": _random_hex(16),
            "plugin": "Adaptive",
        }

        try:
            response = await self._transport.fetch_api(
                url=YUANBAO_CHAT_URL,
                method="POST",
                headers={**DEFAULT_HEADERS, **self._auth_headers()},
                body=payload,
                timeout=120000,
            )

            # 提取回复内容
            content = ""
            if isinstance(response, dict):
                data = response.get("data", response)
                if isinstance(data, dict):
                    content = (
                        data.get("message", "")
                        or data.get("reply", "")
                        or data.get("content", "")
                    )
                elif isinstance(data, str):
                    content = data
            elif isinstance(response, str):
                content = response

            if not content:
                raise ProviderError("元宝返回空内容")

            return ProviderResponse(
                status_code=200,
                data={
                    "id": f"chatcmpl-{_random_hex(12)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
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
            logger.error(f"[Yuanbao] chat_completion failed: {e}")
            raise ProviderError(f"Yuanbao API error: {e}")

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话"""
        await self.login()
        model = self._resolve_model(request)
        prompt = self._messages_to_prompt(request)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "temperature": request.temperature or 0.8,
            "max_tokens": request.max_tokens or 4096,
            "chat_id": _random_hex(16),
            "plugin": "Adaptive",
        }

        logger.info(f"[Yuanbao] Stream: model={model}")

        try:
            full_content = ""

            async for chunk in self._transport.fetch_stream(
                url=YUANBAO_CHAT_URL,
                method="POST",
                headers={**DEFAULT_HEADERS, **self._auth_headers()},
                body=payload,
                timeout=120000,
            ):
                # 解析 SSE
                if chunk.strip():
                    for line in chunk.split("\n"):
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break

                            try:
                                parsed = json.loads(data_str)
                                content = self._extract_delta_content(parsed)
                                if content:
                                    full_content += content
                                    yield StreamChunk(
                                        content=content,
                                        model=model,
                                    )
                            except json.JSONDecodeError:
                                continue

            logger.debug(f"[Yuanbao] Stream completed: {len(full_content)} chars")

        except Exception as e:
            logger.error(f"[Yuanbao] chat_completion_stream failed: {e}")
            yield StreamChunk(
                content="",
                model=model,
                finish_reason="error",
            )

    def _extract_delta_content(self, parsed: dict) -> str:
        """从 SSE chunk 提取 delta 内容"""
        # 腾讯元宝的 SSE 可能是多种格式
        if "data" in parsed:
            d = parsed["data"]
            if isinstance(d, dict):
                return d.get("message", "") or d.get("content", "")
            if isinstance(d, str):
                return d
        if "choices" in parsed:
            delta = parsed["choices"][0].get("delta", {})
            return delta.get("content", "")
        if "message" in parsed:
            return str(parsed["message"])
        if "content" in parsed:
            return str(parsed["content"])
        return ""

    # ---- Models ----

    async def list_models(self) -> list[str]:
        # 始终返回 Provider 全量模型（不受 account.models 限制）
        return DEFAULT_MODELS

    # ---- Health Check ----

    async def health_check(self) -> bool:
        """验证 Token 有效性

        重要：浏览器异常不等于认证失败（常见于 health_check 场景）。
        - 如果有缓存的 token，假设仍然有效
        - 否则尝试重新验证
        """
        # 乐观检查：如果有缓存的 token，假设仍然有效
        if self._x_token:
            return True

        # 完整验证（可能打开浏览器）
        try:
            await self.login()
            return bool(self._x_token)
        except Exception as e:
            error_msg = str(e)
            if "Target page, context or browser has been closed" in error_msg:
                logger.warning("[Yuanbao] Browser closed during health check - assuming token still valid")
                return bool(self._x_token)
            return False

    # ---- Session Management ----

    async def create_session(self) -> str:
        return f"yuanbao_{_random_hex(8)}"

    async def delete_session(self, session_id: str) -> bool:
        return True

    # ---- Token Refresh ----

    async def refresh_token(self) -> bool:
        # Cookie 会话自动维护，无需刷新
        return True
