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

# 导入各个传输层模块
from .api_reverse import APIReverseTransport
from .browser_drive import BrowserDriveTransport


# =============================================================================
# Transport Factory
# =============================================================================

_transport: Optional[APIReverseTransport] = None
_browser_transport: Optional[BrowserDriveTransport] = None


def get_transport() -> APIReverseTransport:
    """获取 API Reverse Transport 单例"""
    global _transport
    if _transport is None:
        _transport = APIReverseTransport()
    return _transport


async def close_transport():
    """关闭 API Reverse Transport"""
    global _transport
    if _transport:
        await _transport.close()
        _transport = None


async def get_browser_transport() -> BrowserDriveTransport:
    """获取 Browser Drive Transport 单例"""
    global _browser_transport
    if _browser_transport is None or not _browser_transport.is_running:
        _browser_transport = BrowserDriveTransport()
        await _browser_transport.start()
    return _browser_transport


async def close_browser_transport():
    """关闭 Browser Drive Transport"""
    global _browser_transport
    if _browser_transport:
        await _browser_transport.stop()
        _browser_transport = None