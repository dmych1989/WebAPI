# -*- coding: utf-8 -*-
"""WebAPI — Browser Drive Transport

Browser Drive Transport 基于 Playwright 实现的浏览器自动化传输层，
用于对抗强反爬保护（如 Cloudflare）和需要浏览器环境的场景。

参考：Chat2API 的 BrowserHttpClient 和 AIClient2API 的 Playwright 实现。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Union

from src.core.logger import logger
from src.core.config import get_config
from src.core.exceptions import ProviderError, NetworkError


class BrowserDriveTransport:
    """浏览器自动化传输层
    
    通过 Playwright 驱动 Chromium，操控网页版对话。
    适用于 API Reverse 无法使用的场景（Cloudflare 保护、WebSocket 通信等）。
    
    特点：
    - 自动处理 Cloudflare 挑战
    - 支持 Cookie 管理
    - 自动化表单填写
    - 会话状态保持
    """

    def __init__(
        self,
        headless: bool = True,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
        timeout: int = 30,
        slow_mo: int = 0
    ):
        """初始化浏览器传输层
        
        Args:
            headless: 是否无头模式运行
            viewport: 视口尺寸，默认为 {"width": 1920, "height": 1080}
            user_agent: 自定义 User-Agent
            timeout: 超时时间（秒）
            slow_mo: 操作延迟（毫秒），用于调试
        """
        self.headless = headless
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        self.timeout = timeout
        self.slow_mo = slow_mo
        
        # Playwright 实例
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        
        # 会话状态
        self._cookies: List[Dict[str, Any]] = []
        self._session_storage: Dict[str, Any] = {}
        self._local_storage: Dict[str, Any] = {}
        
        # 配置
        self.config = get_config()
        self.browser_config = getattr(self.config, 'browser_drive', {}) or {}

    async def start(self) -> None:
        """启动浏览器"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )

        logger.info("[Browser] Starting browser...")

        # 启动 Playwright
        self._playwright = await async_playwright().start()

        # 启动浏览器
        browser_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--disable-gpu"
        ]
        
        # 添加自定义参数
        if self.browser_config.get("args"):
            browser_args.extend(self.browser_config["args"])

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=browser_args,
            slow_mo=self.slow_mo,
            timeout=self.timeout * 1000
        )

        # 创建上下文
        context_args = {
            "viewport": self.viewport,
            "user_agent": self.user_agent,
            "accept_downloads": False,
            "ignore_https_errors": True,
        }

        # 添加上下文配置
        if self.browser_config.get("context_args"):
            context_args.update(self.browser_config["context_args"])

        self._context = await self._browser.new_context(**context_args)

        # 设置默认超时
        if self._context:
            self._context.set_default_timeout(self.timeout * 1000)

        # 创建页面
        self._page = await self._context.new_page()
        
        # 设置页面超时
        if self._page:
            self._page.set_default_timeout(self.timeout * 1000)

        logger.info("[Browser] Browser started successfully")

    async def stop(self) -> None:
        """停止浏览器"""
        logger.info("[Browser] Stopping browser...")

        # 关闭页面
        if self._page and not self._page.is_closed():
            await self._page.close()

        # 关闭上下文
        if self._context:
            await self._context.close()

        # 关闭浏览器
        if self._browser:
            await self._browser.close()

        # 停止 Playwright
        if self._playwright:
            await self._playwright.stop()

        logger.info("[Browser] Browser stopped")

    async def restart(self) -> None:
        """重启浏览器"""
        await self.stop()
        await self.start()

    # =============================================================================
    # 导航和页面操作
    # =============================================================================

    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        """导航到目标页面
        
        Args:
            url: 目标 URL
            wait_until: 等待条件，可选 "domcontentloaded", "load", "networkidle"
        """
        if not self._page:
            await self.start()

        logger.info(f"[Browser] Navigating to: {url}")
        
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=self.timeout * 1000)
            logger.info("[Browser] Navigation completed")
        except Exception as e:
            logger.error(f"[Browser] Navigation failed: {e}")
            raise NetworkError(f"Navigation failed: {e}")

    async def refresh(self) -> None:
        """刷新当前页面"""
        if not self._page:
            raise ProviderError("No page available")

        logger.info("[Browser] Refreshing page...")
        await self._page.reload(wait_until="networkidle")
        logger.info("[Browser] Page refreshed")

    async def go_back(self) -> None:
        """返回上一页"""
        if not self._page:
            raise ProviderError("No page available")

        logger.info("[Browser] Going back...")
        await self._page.go_back()
        logger.info("[Browser] Went back")

    async def go_forward(self) -> None:
        """前进到下一页"""
        if not self._page:
            raise ProviderError("No page available")

        logger.info("[Browser] Going forward...")
        await self._page.go_forward()
        logger.info("[Browser] Went forward")

    # =============================================================================
    # 元素操作
    # =============================================================================

    async def click(self, selector: str, timeout: Optional[int] = None) -> None:
        """点击元素
        
        Args:
            selector: 元素选择器
            timeout: 超时时间（秒）
        """
        if not self._page:
            raise ProviderError("No page available")

        timeout = timeout or self.timeout
        logger.info(f"[Browser] Clicking element: {selector}")

        try:
            await self._page.click(selector, timeout=timeout * 1000)
            logger.info(f"[Browser] Element clicked: {selector}")
        except Exception as e:
            logger.error(f"[Browser] Failed to click element {selector}: {e}")
            raise ProviderError(f"Failed to click element {selector}: {e}")

    async def type_text(self, selector: str, text: str, delay: int = 0) -> None:
        """输入文本
        
        Args:
            selector: 元素选择器
            text: 要输入的文本
            delay: 输入延迟（毫秒）
        """
        if not self._page:
            raise ProviderError("No page available")

        logger.info(f"[Browser] Typing text in {selector}: {text}")

        try:
            await self._page.fill(selector, text, delay=delay)
            logger.info(f"[Browser] Text typed in {selector}")
        except Exception as e:
            logger.error(f"[Browser] Failed to type text in {selector}: {e}")
            raise ProviderError(f"Failed to type text in {selector}: {e}")

    async def wait_for_selector(self, selector: str, timeout: int = 30) -> None:
        """等待元素出现
        
        Args:
            selector: 元素选择器
            timeout: 超时时间（秒）
        """
        if not self._page:
            raise ProviderError("No page available")

        logger.info(f"[Browser] Waiting for selector: {selector}")

        try:
            await self._page.wait_for_selector(selector, timeout=timeout * 1000)
            logger.info(f"[Browser] Selector found: {selector}")
        except Exception as e:
            logger.error(f"[Browser] Failed to wait for selector {selector}: {e}")
            raise ProviderError(f"Failed to wait for selector {selector}: {e}")

    async def wait_for_navigation(self, timeout: int = 30) -> None:
        """等待页面导航完成"""
        if not self._page:
            raise ProviderError("No page available")

        logger.info("[Browser] Waiting for navigation...")
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            logger.info("[Browser] Navigation completed")
        except Exception as e:
            logger.error(f"[Browser] Navigation timeout: {e}")
            raise ProviderError(f"Navigation timeout: {e}")

    # =============================================================================
    # Cookie 和存储管理
    # =============================================================================

    async def get_cookies(self) -> List[Dict[str, Any]]:
        """获取所有 Cookies"""
        if not self._context:
            return []
        
        try:
            cookies = await self._context.cookies()
            self._cookies = cookies
            return cookies
        except Exception as e:
            logger.error(f"[Browser] Failed to get cookies: {e}")
            return []

    async def set_cookie(self, cookie: Dict[str, Any]) -> None:
        """设置单个 Cookie"""
        if not self._context:
            raise ProviderError("No context available")

        try:
            await self._context.add_cookies([cookie])
            logger.info(f"[Browser] Cookie set: {cookie.get('name', 'unknown')}")
        except Exception as e:
            logger.error(f"[Browser] Failed to set cookie: {e}")
            raise ProviderError(f"Failed to set cookie: {e}")

    async def clear_cookies(self) -> None:
        """清除所有 Cookies"""
        if not self._context:
            raise ProviderError("No context available")

        try:
            await self._context.clear_cookies()
            self._cookies = []
            logger.info("[Browser] Cookies cleared")
        except Exception as e:
            logger.error(f"[Browser] Failed to clear cookies: {e}")
            raise ProviderError(f"Failed to clear cookies: {e}")

    async def get_session_storage(self) -> Dict[str, Any]:
        """获取 Session Storage"""
        if not self._context:
            return {}

        try:
            storage = await self._context.storage_state()
            self._session_storage = storage.get("sessionStorage", {})
            return self._session_storage
        except Exception as e:
            logger.error(f"[Browser] Failed to get session storage: {e}")
            return {}

    async def get_local_storage(self) -> Dict[str, Any]:
        """获取 Local Storage"""
        if not self._context:
            return {}

        try:
            storage = await self._context.storage_state()
            self._local_storage = storage.get("localStorage", {})
            return self._local_storage
        except Exception as e:
            logger.error(f"[Browser] Failed to get local storage: {e}")
            return {}

    # =============================================================================
    # 等待和检查
    # =============================================================================

    async def wait_for_text(self, text: str, timeout: int = 30) -> None:
        """等待文本出现"""
        if not self._page:
            raise ProviderError("No page available")

        logger.info(f"[Browser] Waiting for text: {text}")

        try:
            await self._page.wait_for_function(
                f"() => document.body.innerText.includes('{text}')",
                timeout=timeout * 1000
            )
            logger.info(f"[Browser] Text found: {text}")
        except Exception as e:
            logger.error(f"[Browser] Failed to wait for text {text}: {e}")
            raise ProviderError(f"Failed to wait for text {text}: {e}")

    async def wait_for_url(self, url: str, timeout: int = 30) -> None:
        """等待 URL 匹配"""
        if not self._page:
            raise ProviderError("No page available")

        logger.info(f"[Browser] Waiting for URL: {url}")

        try:
            await self._page.wait_for_url(url, timeout=timeout * 1000)
            logger.info(f"[Browser] URL matched: {url}")
        except Exception as e:
            logger.error(f"[Browser] Failed to wait for URL {url}: {e}")
            raise ProviderError(f"Failed to wait for URL {url}: {e}")

    async def is_visible(self, selector: str) -> bool:
        """检查元素是否可见"""
        if not self._page:
            return False

        try:
            element = await self._page.query_selector(selector)
            return element.is_visible() if element else False
        except Exception:
            return False

    async def is_present(self, selector: str) -> bool:
        """检查元素是否存在"""
        if not self._page:
            return False

        try:
            element = await self._page.query_selector(selector)
            return element is not None
        except Exception:
            return False

    # =============================================================================
    # 内容获取
    # =============================================================================

    async def get_page_content(self) -> str:
        """获取页面内容"""
        if not self._page:
            raise ProviderError("No page available")

        try:
            content = await self._page.content()
            return content
        except Exception as e:
            logger.error(f"[Browser] Failed to get page content: {e}")
            raise ProviderError(f"Failed to get page content: {e}")

    async def get_page_title(self) -> str:
        """获取页面标题"""
        if not self._page:
            raise ProviderError("No page available")

        try:
            title = await self._page.title()
            return title
        except Exception as e:
            logger.error(f"[Browser] Failed to get page title: {e}")
            raise ProviderError(f"Failed to get page title: {e}")

    async def get_page_url(self) -> str:
        """获取当前页面 URL"""
        if not self._page:
            raise ProviderError("No page available")

        try:
            url = self._page.url
            return url
        except Exception as e:
            logger.error(f"[Browser] Failed to get page URL: {e}")
            raise ProviderError(f"Failed to get page URL: {e}")

    async def get_element_text(self, selector: str) -> str:
        """获取元素文本内容"""
        if not self._page:
            raise ProviderError("No page available")

        try:
            element = await self._page.query_selector(selector)
            if element:
                text = await element.text_content()
                return text or ""
            else:
                return ""
        except Exception as e:
            logger.error(f"[Browser] Failed to get element text for {selector}: {e}")
            raise ProviderError(f"Failed to get element text for {selector}: {e}")

    async def get_element_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """获取元素属性"""
        if not self._page:
            raise ProviderError("No page available")

        try:
            element = await self._page.query_selector(selector)
            if element:
                value = await element.get_attribute(attribute)
                return value
            else:
                return None
        except Exception as e:
            logger.error(f"[Browser] Failed to get attribute {attribute} for {selector}: {e}")
            raise ProviderError(f"Failed to get attribute {attribute} for {selector}: {e}")

    # =============================================================================
    # HTTP 请求拦截
    # =============================================================================

    async def intercept_request(self, url_pattern: str, handler) -> None:
        """拦截 HTTP 请求
        
        Args:
            url_pattern: URL 匹配模式
            handler: 处理函数
        """
        if not self._page:
            raise ProviderError("No page available")

        try:
            await self._page.route(url_pattern, handler)
            logger.info(f"[Browser] Request interception set for: {url_pattern}")
        except Exception as e:
            logger.error(f"[Browser] Failed to set request interception: {e}")
            raise ProviderError(f"Failed to set request interception: {e}")

    async def unintercept_request(self, url_pattern: str) -> None:
        """取消请求拦截"""
        if not self._page:
            raise ProviderError("No page available")

        try:
            await self._page.unroute(url_pattern)
            logger.info(f"[Browser] Request interception removed for: {url_pattern}")
        except Exception as e:
            logger.error(f"[Browser] Failed to remove request interception: {e}")
            raise ProviderError(f"Failed to remove request interception: {e}")

    # =============================================================================
    # 截图和调试
    # =============================================================================

    async def screenshot(self, path: str, full_page: bool = False) -> None:
        """截图
        
        Args:
            path: 保存路径
            full_page: 是否截取完整页面
        """
        if not self._page:
            raise ProviderError("No page available")

        logger.info(f"[Browser] Taking screenshot: {path}")

        try:
            await self._page.screenshot(
                path=path,
                full_page=full_page,
                type="png"
            )
            logger.info(f"[Browser] Screenshot saved: {path}")
        except Exception as e:
            logger.error(f"[Browser] Failed to take screenshot: {e}")
            raise ProviderError(f"Failed to take screenshot: {e}")

    async def pdf(self, path: str) -> None:
        """生成 PDF
        
        Args:
            path: 保存路径
        """
        if not self._page:
            raise ProviderError("No page available")

        logger.info(f"[Browser] Generating PDF: {path}")

        try:
            await self._page.pdf(path=path)
            logger.info(f"[Browser] PDF generated: {path}")
        except Exception as e:
            logger.error(f"[Browser] Failed to generate PDF: {e}")
            raise ProviderError(f"Failed to generate PDF: {e}")

    async def execute_script(self, script: str) -> Any:
        """执行 JavaScript
        
        Args:
            script: JavaScript 代码
        """
        if not self._page:
            raise ProviderError("No page available")

        try:
            result = await self._page.evaluate(script)
            return result
        except Exception as e:
            logger.error(f"[Browser] Failed to execute script: {e}")
            raise ProviderError(f"Failed to execute script: {e}")

    # =============================================================================
    # 上下文管理
    # =============================================================================

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.stop()

    # =============================================================================
    # 状态检查
    # =============================================================================

    @property
    def is_running(self) -> bool:
        """检查浏览器是否正在运行"""
        return self._browser is not None and not self._browser.is_closed()

    @property
    def is_page_open(self) -> bool:
        """检查页面是否打开"""
        return self._page is not None and not self._page.is_closed()

    def get_status(self) -> Dict[str, Any]:
        """获取浏览器状态"""
        return {
            "running": self.is_running,
            "page_open": self.is_page_open,
            "cookies_count": len(self._cookies),
            "session_storage_size": len(self._session_storage),
            "local_storage_size": len(self._local_storage),
            "page_url": self._page.url if self._page else None,
            "page_title": self._page.title() if self._page else None
        }


# =============================================================================
# 工厂函数
# =============================================================================

_browser_instance: Optional[BrowserDriveTransport] = None


async def get_browser_drive_transport(
    headless: bool = True,
    viewport: Optional[Dict[str, int]] = None,
    user_agent: Optional[str] = None,
    timeout: int = 30
) -> BrowserDriveTransport:
    """获取 Browser Drive Transport 单例
    
    Args:
        headless: 是否无头模式
        viewport: 视口尺寸
        user_agent: 自定义 User-Agent
        timeout: 超时时间
        
    Returns:
        BrowserDriveTransport 实例
    """
    global _browser_instance
    
    if _browser_instance is None or not _browser_instance.is_running:
        _browser_instance = BrowserDriveTransport(
            headless=headless,
            viewport=viewport,
            user_agent=user_agent,
            timeout=timeout
        )
        await _browser_instance.start()
    
    return _browser_instance


async def close_browser_drive_transport():
    """关闭 Browser Drive Transport"""
    global _browser_instance
    
    if _browser_instance:
        await _browser_instance.stop()
        _browser_instance = None