# -*- coding: utf-8 -*-
"""Playwright Browser Automation Transport Layer

浏览器自动化传输层，通过 Playwright 驱动 Chromium 操作网页版对话。
适用于需要浏览器自动化、反爬规避、WebSocket 通信等场景。

使用场景：
- Doubao: a_bogus 签名生成
- Yuanbao: 自动维护 x-uskey 等请求头
- 其他需要浏览器操作的 API

依赖：pip install playwright webapi[browser]
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Optional

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.core.logger import logger


class BrowserAutomationTransport:
    """Playwright 浏览器自动化传输层

    核心能力：
    1. 浏览器实例管理（启动/关闭/复用）
    2. Cookie/Session 自动维护
    3. JavaScript 执行（签名生成、页面操作）
    4. API 请求执行（fetch API）
    5. SSE 流式响应处理

    使用方式：
    ```python
    transport = BrowserAutomationTransport(headless=False)
    await transport.start()
    await transport.navigate("https://doubao.com")
    await transport.set_cookies(cookies)
    await transport.execute_js("window.byted_acrawler.frontierSign(...)")
    response = await transport.fetch_api(url, method, headers, body)
    ```
    """

    def __init__(self, headless: bool = False, slow_mo: int = 100):
        """
        Args:
            headless: 是否无头模式（默认非无头，方便调试）
            slow_mo: 操作延迟（毫秒），方便观察执行过程
        """
        self.headless = headless
        self.slow_mo = slow_mo
        self._playwright = None
        self._browser = None
        self._context = None
        self._page: Optional[Page] = None
        self._base_url: str = ""

    async def start(self) -> None:
        """启动浏览器实例"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        logger.info(f"[Browser] Starting (headless={self.headless})...")
        self._playwright = await async_playwright().start()

        # 启动 Chromium 浏览器
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )

        # 创建浏览器上下文
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        # 创建新页面
        self._page = await self._context.new_page()
        self._page.set_default_timeout(30000)  # 30 秒超时
        self._page.set_default_navigation_timeout(60000)  # 60 秒导航超时

        logger.info("[Browser] Started successfully")

    async def navigate(self, url: str, wait_selector: Optional[str] = None) -> None:
        """
        导航到目标页面

        Args:
            url: 目标 URL
            wait_selector: 可选等待元素选择器（导航完成后）
        """
        if not self._page:
            await self.start()

        self._base_url = url.split("/")[0] + "//" + url.split("/")[2]

        logger.info(f"[Browser] Navigating to {url}")
        await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)

        if wait_selector:
            logger.debug(f"[Browser] Waiting for selector: {wait_selector}")
            await self._page.wait_for_selector(wait_selector, timeout=30000)

        logger.debug("[Browser] Navigation complete")

    async def set_cookies(self, cookies: list[dict]) -> None:
        """设置 Cookies

        Args:
            cookies: Cookie 列表，格式：[{"name": "session_id", "value": "..."}]
        """
        if not self._page:
            await self.start()

        await self._page.context.add_cookies(cookies)
        logger.debug(f"[Browser] Cookies set: {len(cookies)} cookies")

    async def get_cookies(self) -> list[dict]:
        """获取所有 Cookies"""
        if not self._page:
            return []

        cookies = await self._page.context.cookies()
        logger.debug(f"[Browser] Cookies retrieved: {len(cookies)} cookies")
        return cookies

    async def execute_js(self, script: str, *args, timeout: int = 30000) -> Any:
        """
        在页面上下文中执行 JavaScript

        Args:
            script: JavaScript 代码（可以用字符串格式化参数）
            *args: 传递给 JavaScript 的参数
            timeout: 执行超时时间（毫秒）

        Returns:
            JavaScript 执行结果

        示例：
            await transport.execute_js("const result = window.byted_acrawler.frontierSign(params); result;")
            await transport.execute_js("document.querySelector('.login-button').click()")
        """
        if not self._page:
            await self.start()

        try:
            logger.debug(f"[Browser] Executing JS: {script[:100]}...")
            result = await self._page.evaluate(script, *args)
            logger.debug(f"[Browser] JS executed successfully")
            return result
        except PlaywrightTimeoutError as e:
            logger.error(f"[Browser] JS execution timeout: {script[:100]}...")
            raise TimeoutError(f"JavaScript execution timed out after {timeout}ms") from e
        except Exception as e:
            logger.error(f"[Browser] JS execution failed: {e}")
            raise

    async def execute_js_function(
        self, func_name: str, *args, timeout: int = 30000
    ) -> Any:
        """
        在页面上下文中执行全局函数（推荐方式）

        Args:
            func_name: 函数名
            *args: 参数
            timeout: 执行超时时间（毫秒）

        Returns:
            执行结果

        示例：
            await transport.execute_js_function("window.byted_acrawler.frontierSign", params)
        """
        if not self._page:
            await self.start()

        try:
            logger.debug(f"[Browser] Executing function: {func_name}(...)")
            result = await self._page.evaluate(
                f"typeof {func_name} !== 'undefined' ? {func_name}(...arguments) : null",  # noqa: E501
                *args,
            )
            logger.debug(f"[Browser] Function executed: {func_name}")
            return result
        except PlaywrightTimeoutError as e:
            logger.error(f"[Browser] Function execution timeout: {func_name}")
            raise TimeoutError(f"JavaScript function '{func_name}' timed out after {timeout}ms") from e
        except Exception as e:
            logger.error(f"[Browser] Function execution failed ({func_name}): {e}")
            raise

    async def fetch_api(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout: int = 30000,
    ) -> dict[str, Any]:
        """
        使用 fetch API 发送 HTTP 请求（在页面上下文中）

        Args:
            url: 请求 URL
            method: HTTP 方法（GET/POST/PUT/DELETE）
            headers: 请求头
            body: 请求体（dict 或 str）
            timeout: 请求超时时间（毫秒）

        Returns:
            响应数据（解析为 JSON）

        示例：
            await transport.fetch_api(
                "https://doubao.com/api/chat",
                method="POST",
                headers={"Cookie": "..."},
                body={"message": "hello"}
            )
        """
        if not self._page:
            await self.start()

        try:
            # 构造请求体
            fetch_body: str = ""
            if body:
                if isinstance(body, dict):
                    fetch_body = json.dumps(body, ensure_ascii=False)
                else:
                    fetch_body = str(body)

            logger.debug(
                f"[Browser] Fetch: {method} {url} (body={len(fetch_body) if fetch_body else 0} bytes)"
            )

            # 执行 fetch 请求
            result = await self._page.evaluate(
                """
                async (url, method, headers, body) => {
                    const response = await fetch(url, {
                        method: method,
                        headers: headers || {},
                        body: body || null,
                    });

                    const status = response.status;
                    const headers = Object.fromEntries(response.headers.entries());
                    const text = await response.text();

                    // 尝试解析 JSON
                    let data;
                    try {
                        data = JSON.parse(text);
                    } catch (e) {
                        data = text;
                    }

                    return { status, headers, data };
                }
                """,
                url,
                method.upper(),
                headers or {},
                fetch_body,
                timeout,
            )

            if result["status"] >= 400:
                logger.warning(
                    f"[Browser] Fetch failed: {result['status']} - {result.get('data', 'N/A')[:200]}"
                )
                raise Exception(
                    f"HTTP {result['status']}: {result.get('data', 'N/A')}"
                )

            logger.debug(f"[Browser] Fetch success: {result['status']}")
            return result["data"]

        except PlaywrightTimeoutError as e:
            logger.error(f"[Browser] Fetch timeout: {url}")
            raise TimeoutError(f"API request timed out after {timeout}ms") from e
        except Exception as e:
            logger.error(f"[Browser] Fetch failed ({url}): {e}")
            raise

    async def fetch_stream(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout: int = 30000,
    ) -> AsyncIterator[str]:
        """
        使用 fetch API 发送 HTTP 请求并获取 SSE 流式响应

        Args:
            url: 请求 URL
            method: HTTP 方法（GET/POST）
            headers: 请求头
            body: 请求体
            timeout: 请求超时时间（毫秒）

        Yields:
            SSE 事件块（如 "event: xxx\ndata: {...}\n\n"）

        示例：
            async for chunk in await transport.fetch_stream(url, method="POST", body=payload):
                print(chunk)
        """
        if not self._page:
            await self.start()

        try:
            # 构造请求体
            fetch_body: str = ""
            if body:
                if isinstance(body, dict):
                    fetch_body = json.dumps(body, ensure_ascii=False)
                else:
                    fetch_body = str(body)

            logger.debug(f"[Browser] Fetch stream: {method} {url}")

            # 执行 fetch 流式请求
            result = await self._page.evaluate(
                """
                async (url, method, headers, body) => {
                    const response = await fetch(url, {
                        method: method,
                        headers: headers || {},
                        body: body || null,
                    });

                    const status = response.status;
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder('utf-8');
                    let buffer = '';

                    return {
                        status,
                        async *stream() {
                            while (true) {
                                const { done, value } = await reader.read();
                                if (done) break;
                                const chunk = decoder.decode(value, { stream: true });
                                buffer += chunk;
                                yield chunk;
                            }
                        }
                    };
                }
                """,
                url,
                method.upper(),
                headers or {},
                fetch_body,
                timeout,
            )

            if result["status"] >= 400:
                raise Exception(f"HTTP {result['status']}: API request failed")

            # 生成流式数据
            async for chunk in result["stream"]():
                yield chunk

            logger.debug(f"[Browser] Fetch stream completed")

        except PlaywrightTimeoutError as e:
            logger.error(f"[Browser] Fetch stream timeout: {url}")
            raise TimeoutError(f"API request timed out after {timeout}ms") from e
        except Exception as e:
            logger.error(f"[Browser] Fetch stream failed ({url}): {e}")
            raise

    async def wait_for_selector(
        self, selector: str, timeout: int = 30000, state: str = "visible"
    ) -> bool:
        """
        等待元素出现

        Args:
            selector: CSS 选择器
            timeout: 超时时间（毫秒）
            state: 等待状态（visible/attached/hidden）

        Returns:
            是否找到元素

        示例：
            await transport.wait_for_selector(".chat-input")
        """
        if not self._page:
            await self.start()

        try:
            await self._page.wait_for_selector(selector, state=state, timeout=timeout)
            logger.debug(f"[Browser] Selector found: {selector}")
            return True
        except PlaywrightTimeoutError:
            logger.warning(f"[Browser] Selector not found: {selector} (timeout={timeout})")
            return False

    async def click(self, selector: str) -> None:
        """点击元素"""
        if not self._page:
            await self.start()

        logger.debug(f"[Browser] Clicking: {selector}")
        await self._page.click(selector, timeout=30000)

    async def fill(self, selector: str, text: str) -> None:
        """填写输入框"""
        if not self._page:
            await self.start()

        logger.debug(f"[Browser] Filling: {selector} = {text[:50]}...")
        await self._page.fill(selector, text, timeout=30000)

    async def screenshot(self, path: str) -> None:
        """截图保存到本地"""
        if self._page:
            await self._page.screenshot(path=path)
            logger.debug(f"[Browser] Screenshot saved: {path}")

    async def close(self) -> None:
        """关闭浏览器"""
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            logger.info("[Browser] Browser closed")
        if self._playwright:
            await self._playwright.stop()
            logger.info("[Browser] Playwright stopped")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()
