# -*- coding: utf-8 -*-
"""WebAPI — Transport Layer

两种传输模式：
1. API Reverse: 直接用 aiohttp 重放内部 HTTP API（优先，轻量高效）
2. Browser Drive: Playwright 驱动无头浏览器（兜底，对抗强反爬）

参考 Chat2API 的 Axios Http Client 和 AIClient2API 的 TLS Sidecar。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

import aiohttp
from src.core.logger import logger

from src.core.config import get_config
from src.core.exceptions import ProviderError, RateLimitError, AuthError


# =============================================================================
# API Reverse Transport
# =============================================================================

class APIReverseTransport:
    """API 反向代理传输层

    直接调用厂商内部 HTTP API，模拟网页版行为。
    参考 Chat2API 的 requestForwarder.forwardDeepSeek() 等。
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=get_config().proxy.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/131.0.0.0 Safari/537.36"},
            )
        return self._session

    async def post(
        self,
        url: str,
        json: dict | None = None,
        headers: dict | None = None,
        stream: bool = False,
        extra_headers: dict | None = None,
    ) -> aiohttp.ClientResponse:
        """发送 POST 请求"""
        session = await self._get_session()

        merged_headers = {**(headers or {})}
        if extra_headers:
            merged_headers.update(extra_headers)

        logger.debug(f"[API] POST {url}")

        return await session.post(
            url,
            json=json,
            headers=merged_headers,
        )

    async def get(
        self,
        url: str,
        headers: dict | None = None,
    ) -> aiohttp.ClientResponse:
        """发送 GET 请求"""
        session = await self._get_session()
        return await session.get(url, headers=headers or {})

    async def check_response(self, response: aiohttp.ClientResponse) -> None:
        """检查响应状态，抛出相应异常"""
        if response.status == 401:
            raise AuthError("Token expired or invalid", status_code=401)
        if response.status == 429:
            raise RateLimitError("Rate limit exceeded", status_code=429)
        if response.status >= 500:
            raise ProviderError(
                f"Provider server error: {response.status}",
                status_code=response.status,
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# =============================================================================
# Browser Drive Transport (Playwright)
# =============================================================================

class BrowserDriveTransport:
    """浏览器自动化传输层

    通过 Playwright 驱动 Chromium，操控网页版对话。
    适用于 API Reverse 无法使用的场景（Cloudflare 保护、WebSocket 通信等）。

    注意：需要安装 playwright 依赖（pip install webapi[browser]）
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None

    async def start(self):
        """启动浏览器"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        logger.info("[Browser] Started")

    async def navigate(self, url: str):
        """导航到目标页面"""
        if self._page is None:
            await self.start()
        await self._page.goto(url, wait_until="domcontentloaded")

    async def get_cookies(self) -> list[dict]:
        """获取所有 Cookies"""
        if self._context is None:
            return []
        return await self._context.cookies()

    async def close(self):
        """关闭浏览器"""
        if self._browser:
            await self._browser.close()
            logger.info("[Browser] Closed")
        if self._playwright:
            await self._playwright.stop()


# =============================================================================
# Transport Factory
# =============================================================================

_transport: Optional[APIReverseTransport] = None


def get_transport() -> APIReverseTransport:
    """获取 API Reverse Transport 单例"""
    global _transport
    if _transport is None:
        _transport = APIReverseTransport()
    return _transport


async def close_transport():
    global _transport
    if _transport:
        await _transport.close()
        _transport = None