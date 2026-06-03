# -*- coding: utf-8 -*-
"""
OAuth Flow Manager — 浏览器内嵌登录 + Token 自动提取

参考 Chat2API src/main/oauth/manager.ts + inAppLogin.ts

核心流程：
1. 启动 Playwright 浏览器（内嵌或外部）
2. 导航到 Provider 登录页面
3. 拦截网络请求/响应，捕获 Token/Cookie
4. 轮询 localStorage/cookies 检测凭证
5. 用 OAuthAdapter 验证凭证有效性
6. 保存到 config.yaml
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

# =============================================================================
# Token 提取配置（对齐 Chat2API tokenExtractionConfig.ts）
# =============================================================================

TOKEN_SOURCE_TYPES = {"networkHeader", "localStorage", "cookie"}


@dataclass
class TokenSource:
    type: str  # networkHeader | localStorage | cookie
    key: str
    url_pattern: Optional[str] = None
    extract_pattern: Optional[str] = None


@dataclass
class TokenExtractionConfig:
    """单个 Provider 的 Token 提取配置"""
    login_url: str
    token_sources: list[TokenSource]
    target_domains: list[str]
    success_url_patterns: list[str] = field(default_factory=list)
    window_title: str = "Login"


# 对齐 Chat2API TOKEN_EXTRACTION_CONFIGS
TOKEN_EXTRACTION_CONFIGS: dict[str, TokenExtractionConfig] = {
    "deepseek": TokenExtractionConfig(
        login_url="https://chat.deepseek.com",
        token_sources=[TokenSource(type="localStorage", key="userToken")],
        target_domains=[".deepseek.com", "deepseek.com"],
        success_url_patterns=["chat.deepseek.com"],
        window_title="DeepSeek Login",
    ),
    "kimi": TokenExtractionConfig(
        login_url="https://www.kimi.com",
        token_sources=[
            TokenSource(type="cookie", key="kimi-auth"),
            TokenSource(type="networkHeader", key="token", url_pattern="*://*.kimi.com/*", extract_pattern="^Bearer\\s+(.+)$"),
            TokenSource(type="localStorage", key="access_token"),
            TokenSource(type="localStorage", key="refresh_token"),
        ],
        target_domains=[".kimi.com", "kimi.com"],
        success_url_patterns=["kimi.com"],
        window_title="Kimi Login",
    ),
    "qwen": TokenExtractionConfig(
        login_url="https://www.qianwen.com",
        token_sources=[
            TokenSource(type="cookie", key="tongyi_sso_ticket"),
            TokenSource(type="networkHeader", key="tongyi_sso_ticket", url_pattern="*://*.qianwen.com/*", extract_pattern="tongyi_sso_ticket=([^;]+)"),
        ],
        target_domains=[".qianwen.com", "qianwen.com"],
        success_url_patterns=["qianwen.com"],
        window_title="Qwen Login",
    ),
    "minimax": TokenExtractionConfig(
        login_url="https://agent.minimaxi.com",
        token_sources=[
            TokenSource(type="localStorage", key="_token"),
            TokenSource(type="localStorage", key="user_detail_agent"),
        ],
        target_domains=[".minimaxi.com", "minimaxi.com"],
        success_url_patterns=["agent.minimaxi.com"],
        window_title="MiniMax Login",
    ),
    "doubao": TokenExtractionConfig(
        login_url="https://www.doubao.com/chat/",
        token_sources=[
            # Cookie 全量提取（豆包 Cookie 有效期长，无需特定字段）
            TokenSource(type="cookie", key="_ddq_view"),
            TokenSource(type="cookie", key="passport_csrf_token"),
            TokenSource(type="cookie", key="sid_tc"),
            TokenSource(type="cookie", key="sid_ucp_v2"),
            TokenSource(type="localStorage", key="BEAKER_SESSION_ID"),
            TokenSource(type="networkHeader", key="Authorization", url_pattern="*://*.doubao.com/*", extract_pattern="^Bearer\\s+(.+)$"),
        ],
        target_domains=[".doubao.com", "doubao.com"],
        success_url_patterns=["doubao.com/chat", "doubao.com/conversation", "doubao.com/aichat"],
        window_title="Doubao Login",
    ),
    "glm": TokenExtractionConfig(
        login_url="https://chatglm.cn",
        token_sources=[
            # GLM 把 refresh_token 存到 localStorage.token
            # 同时存在 cookie chatglm_refresh_token（双保险）
            TokenSource(type="localStorage", key="token"),
            TokenSource(type="localStorage", key="chatglm_refresh_token"),
            TokenSource(type="localStorage", key="refreshToken"),
            TokenSource(type="cookie", key="chatglm_refresh_token"),
            # 拦截 chatglm.cn 的 Authorization 头
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.chatglm.cn/*",
                extract_pattern="^Bearer\\s+(.+)$",
            ),
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.bigmodel.cn/*",
                extract_pattern="^Bearer\\s+(.+)$",
            ),
        ],
        target_domains=[".chatglm.cn", "chatglm.cn", ".bigmodel.cn", "bigmodel.cn"],
        # 登录成功的 URL 模式（区分于登录页 / 静态资源）
        success_url_patterns=[
            "chatglm.cn/main",          # 主聊天页
            "chatglm.cn/chat",
            "chatglm.cn/conversation",
            "bigmodel.cn/center",
            "bigmodel.cn/big",          # 模型广场
            "bigmodel.cn/console",
        ],
        window_title="GLM Login",
    ),
    "yuanbao": TokenExtractionConfig(
        login_url="https://yuanbao.tencent.com/chat/",
        token_sources=[
            # 腾讯元宝 Cookie 全量提取
            TokenSource(type="cookie", key="appid"),
            TokenSource(type="cookie", key="qqhelp_enter_time"),
            TokenSource(type="cookie", key="sessionid"),
            TokenSource(type="cookie", key="session_type"),
            # x_token 从页面 HTML 中提取（对齐 __init__.py）
            TokenSource(type="localStorage", key="x_token"),
        ],
        target_domains=[".tencent.com", "yuanbao.tencent.com"],
        success_url_patterns=["yuanbao.tencent.com/chat", "yuanbao.tencent.com/conversation"],
        window_title="Yuanbao Login",
    ),
    "mimo": TokenExtractionConfig(
        login_url="https://aistudio.xiaomimimo.com/",
        token_sources=[
            # MiMo 需要 3 个 Cookie 字段（对齐 Chat2API）
            TokenSource(type="cookie", key="serviceToken"),
            TokenSource(type="cookie", key="userId"),
            TokenSource(type="cookie", key="xiaomichatbot_ph"),
            # localStorage 兜底
            TokenSource(type="localStorage", key="serviceToken"),
            TokenSource(type="localStorage", key="userId"),
            TokenSource(type="localStorage", key="xiaomichatbot_ph"),
        ],
        target_domains=[".xiaomimimo.com", "xiaomimimo.com", ".mi.com"],
        success_url_patterns=["aistudio.xiaomimimo.com"],
        window_title="MiMo Login",
    ),
}


# =============================================================================
# OAuth 结果类型
# =============================================================================

@dataclass
class OAuthResult:
    success: bool
    provider: str
    credentials: Optional[dict[str, str]] = None
    account_info: Optional[dict] = None
    error: Optional[str] = None


# =============================================================================
# OAuth Manager
# =============================================================================

class OAuthManager:
    """OAuth 流程管理器

    参考 Chat2API OAuthManager + InAppLoginManager 的合并实现：
    - 管理浏览器登录会话
    - 拦截网络请求/响应捕获凭证
    - 自动提取 localStorage / cookies
    - 调用 OAuthAdapter 验证
    - 保存到 config.yaml
    """

    def __init__(self, provider: str, headless: bool = False):
        self.provider = provider
        self.headless = headless
        self.cfg = TOKEN_EXTRACTION_CONFIGS.get(provider)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        # 事件回调
        self._on_progress: Optional[Callable[[str, str], None]] = None
        self._on_token_found: Optional[Callable[[str, str], None]] = None

        # 捕获状态
        self._captured_auth_headers: list[str] = []
        self._captured_cookies: dict[str, str] = {}
        self._captured_local_storage: dict[str, str] = {}
        self._login_start_time: float = 0.0
        self._is_completed: bool = False

    # ---- 公开 API ----

    def set_progress_callback(self, cb: Callable[[str, str], None]):
        """设置进度回调 (status, message)"""
        self._on_progress = cb

    def set_token_callback(self, cb: Callable[[str, str], None]):
        """设置 Token 找到回调 (key, value)"""
        self._on_token_found = cb

    async def login(self, timeout: float = 360.0) -> OAuthResult:
        """启动 OAuth 登录流程

        Args:
            timeout: 超时秒数，默认 6 分钟
        """
        if not self.cfg:
            return OAuthResult(
                success=False,
                provider=self.provider,
                error=f"No OAuth config for provider: {self.provider}",
            )

        self._emit_progress("pending", "Opening login window...")

        try:
            await self._start_browser()
            await self._setup_interceptors()
            await self._navigate_and_wait(timeout)
            result = await self._extract_and_validate(timeout)
            return result
        except asyncio.TimeoutError:
            return OAuthResult(success=False, provider=self.provider, error="Login timeout")
        except Exception as e:
            return OAuthResult(success=False, provider=self.provider, error=str(e))
        finally:
            await self._cleanup()

    async def validate_credentials(self, credentials: dict) -> OAuthResult:
        """仅验证凭证，不启动浏览器"""
        from src.login.adapters import get_adapter

        adapter = get_adapter(self.provider)
        if not adapter:
            return OAuthResult(success=False, provider=self.provider, error="No adapter for provider")

        self._emit_progress("pending", f"Validating {self.provider} credentials...")

        result = await adapter.validate_token(credentials)

        if result.valid:
            self._emit_progress("success", "Credentials valid")
            return OAuthResult(
                success=True,
                provider=self.provider,
                credentials=credentials,
                account_info=result.account_info,
            )
        else:
            self._emit_progress("error", result.error or "Validation failed")
            return OAuthResult(success=False, provider=self.provider, error=result.error)

    # ---- 浏览器初始化 ----

    async def _start_browser(self):
        """启动 Playwright 浏览器"""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright 未安装，请运行:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            ) from e

        self.playwright = await async_playwright().start()

        try:
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    # 反自动化检测（对齐 Chat2API）
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--disable-popup-blocking",
                    "--ignore-certificate-errors",
                    "--disable-web-security",
                ],
            )
        except Exception as e:
            if self.playwright:
                await self.playwright.stop()
            raise RuntimeError(f"浏览器启动失败: {e}")

        # 持久化 storage_state
        storage_dir = PROJECT_ROOT / "data" / "browser_states"
        storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_dir / f"{self.provider}.json"

        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if self._storage_path.exists():
            context_kwargs["storage_state"] = str(self._storage_path)

        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()

    async def _setup_interceptors(self):
        """设置网络拦截器（对齐 Chat2API inAppLogin.ts）"""
        self._captured_auth_headers.clear()
        self._captured_cookies.clear()
        self._login_start_time = time.time()

        # 拦截请求：捕获 Authorization / Cookie headers
        async def on_request(route):
            request = route.request
            headers = dict(request.headers)

            # Authorization header
            auth = headers.get("authorization", "") or headers.get("Authorization", "")
            if auth.startswith("Bearer ") and len(auth) > 20:
                token = auth[7:]
                if token not in self._captured_auth_headers:
                    self._captured_auth_headers.append(token)
                    self._emit_progress("pending", f"Captured Auth header ({len(token)} chars)")
                    self._emit_token("token", token)

            # Cookie header
            cookie = headers.get("cookie", "") or headers.get("Cookie", "")
            if cookie:
                for src in self.cfg.token_sources:
                    if src.type == "networkHeader":
                        continue
                    if src.key and src.key in cookie:
                        match = re.search(rf"{re.escape(src.key)}=([^;]+)", cookie)
                        if match:
                            val = match.group(1)
                            self._captured_cookies[src.key] = val
                            self._emit_progress("pending", f"Captured Cookie header ({src.key}, {len(val)} chars)")
                            self._emit_token(src.key, val)

            await route.continue_()

        await self.page.route("**/*", on_request)

        # 拦截响应：捕获 Set-Cookie
        def on_response(response):
            try:
                set_cookie = response.headers.get("set-cookie", "") or response.headers.get("Set-Cookie", "")
                if set_cookie:
                    for part in set_cookie.split(";"):
                        part = part.strip()
                        if "=" in part:
                            k, v = part.split("=", 1)
                            k, v = k.strip(), v.strip()
                            # 去掉引号
                            if v.startswith('"') and v.endswith('"'):
                                v = v[1:-1]
                            if k and v:
                                self._captured_cookies[k] = v
                                self._emit_token(k, v)
            except Exception:
                pass

        self.page.on("response", on_response)

        # 页面导航事件
        self.page.on("framenavigated", lambda f: self._schedule_token_check())
        self.page.on("domcontentloaded", lambda _: self._schedule_token_check())

    async def _navigate_and_wait(self, timeout: float):
        """导航到登录页面，等待用户操作"""
        self._emit_progress("pending", "Opening login page...")

        await self.page.goto(self.cfg.login_url, wait_until="domcontentloaded")
        # 移除浏览器自动化特征（对齐 Chat2API: webSecurity + 修改 navigator）
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        self._emit_progress(
            "pending",
            f"Login window ready — please log in at {self.cfg.login_url}\n"
            "The browser will automatically extract your credentials after login.",
        )

        # 等待登录成功（URL 变化或检测到凭证）
        deadline = time.time() + timeout
        last_check = 0.0
        last_html_check = 0.0

        while time.time() < deadline:
            # 检查是否完成
            if self._is_completed:
                return

            # 延迟 Token 检查（最少等待 5 秒）
            now = time.time()
            if now - self._login_start_time >= 5.0 and now - last_check >= 2.0:
                last_check = now
                await self._check_for_tokens()

                # 检查是否已登录（URL 匹配成功模式）
                current_url = self.page.url
                for pattern in self.cfg.success_url_patterns:
                    if pattern.lower() in current_url.lower():
                        self._emit_progress("pending", "Login detected! Extracting credentials...")
                        break

            # 每 10 秒检查一次页面 HTML（yuanbao 等通过 HTML 注入 x_token）
            if now - self._login_start_time >= 5.0 and now - last_html_check >= 10.0:
                last_html_check = now
                await self._check_html_for_tokens()

            await asyncio.sleep(1.0)

        raise asyncio.TimeoutError()

    async def _check_for_tokens(self):
        """检查 localStorage 和 cookies 中的凭证"""
        try:
            if self.page.is_closed():
                return

            # localStorage
            for src in self.cfg.token_sources:
                if src.type == "localStorage":
                    value = await self.page.evaluate(f"localStorage.getItem('{src.key}')")
                    if value and self._is_valid_token(value):
                        self._captured_local_storage[src.key] = value
                        self._emit_progress("pending", f"Found localStorage.{src.key} ({len(value)} chars)")

                        # 特殊处理：user_detail_agent → 提取 realUserID
                        if src.key == "user_detail_agent" and value:
                            user_detail = self._try_parse_json(value)
                            if user_detail:
                                real_user_id = (
                                    user_detail.get("realUserID")
                                    or user_detail.get("id")
                                    or (user_detail.get("user", {}).get("id") if isinstance(user_detail.get("user"), dict) else None)
                                )
                                if real_user_id:
                                    self._emit_token("realUserID", str(real_user_id))

                        self._emit_token(src.key, value)

            # cookies
            for src in self.cfg.token_sources:
                if src.type == "cookie":
                    if src.key:
                        # 特定 cookie
                        cookies = await self.context.cookies()
                        for c in cookies:
                            if c["name"] == src.key and c["value"]:
                                if self._is_valid_token(c["value"]):
                                    self._captured_cookies[src.key] = c["value"]
                                    self._emit_token(src.key, c["value"])
                    else:
                        # 全量 cookie
                        cookies = await self.context.cookies()
                        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies if c["name"] and c["value"])
                        if cookie_str and len(cookie_str) > 50:
                            self._captured_cookies["_all_"] = cookie_str
                            self._emit_token("_all_", cookie_str)

        except Exception as e:
            self._emit_progress("pending", f"Token check error: {e}")

    async def _check_html_for_tokens(self):
        """从页面 HTML 中提取 x_token 等（对齐 Chat2API html extractor）"""
        if not self.page or self.page.is_closed():
            return
        try:
            html = await self.page.content()
            if not html:
                return
            # yuanbao x_token
            patterns = [
                (r'["\']x_token["\']\s*:\s*["\']([^"\']+)["\']', "x_token"),
                (r'x_token["\s]*[:=]["\s]*([^"\';\s,&]+)', "x_token"),
            ]
            for pattern, key in patterns:
                match = re.search(pattern, html)
                if match and match.group(1):
                    val = match.group(1).strip()
                    if self._is_valid_token(val):
                        self._emit_progress("pending", f"Found x_token from HTML ({len(val)} chars)")
                        self._captured_local_storage[key] = val
                        self._emit_token(key, val)
        except Exception:
            pass

    def _schedule_token_check(self):
        """安排延迟的 Token 检查（使用 asyncio）"""
        async def delayed_check():
            await asyncio.sleep(2)
            if not self._is_completed:
                await self._check_for_tokens()

        asyncio.create_task(delayed_check())

    # ---- Token 有效性判断（对齐 Chat2API isValidToken） ----

    def _is_valid_token(self, value: str) -> bool:
        """判断 Token 是否有效（对齐 Chat2API inAppLogin.ts isValidToken）"""
        if not value or len(str(value)) < 5:
            return False

        v = str(value)

        # JWT / JWE
        if v.startswith("eyJ"):
            parts = v.split(".")
            if len(parts) == 5 and len(v) >= 100:  # JWE
                return True
            if len(parts) == 3:  # JWT
                payload = self._parse_jwt(v)
                if payload:
                    if payload.get("email", "").endswith("@guest.com"):
                        return False
                    if any(payload.get(k) for k in ("app_id", "sub", "exp", "id", "user_id", "uid", "email")):
                        return True

        # 长 Token >= 64
        if len(v) >= 64 and all(c.isalnum() or c in "_-+/*" for c in v):
            return True

        # 中等 Token 32-63
        if 32 <= len(v) < 64 and all(c.isalnum() or c in "_-+/*" for c in v):
            return True

        # Base64 >= 20
        if len(v) >= 20 and all(c.isalnum() or c in "_-+/=" for c in v):
            return True

        # 通用 >= 5
        if len(v) >= 5 and not any(c.isspace() for c in v):
            return True

        return False

    def _parse_jwt(self, token: str) -> Optional[dict]:
        """解析 JWT payload"""
        if "." not in token:
            return None
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8", errors="replace"))
            return payload
        except Exception:
            return None

    def _try_parse_json(self, value: str) -> Optional[dict]:
        """尝试 JSON 解析"""
        if not value:
            return None
        if value.startswith("{") and value.endswith("}"):
            try:
                return json.loads(value)
            except Exception:
                pass
        return None

    # ---- 提取和验证 ----

    async def _extract_and_validate(self, timeout: float) -> OAuthResult:
        """等待足够凭证后验证并保存

        对齐 Chat2API OAuthManager.validateAndComplete():
        - 持续等待最多 5 分钟收集凭证（用户输入密码等操作）
        - 捕获到凭证后立即验证
        - 验证通过后保存到 config.yaml
        """
        deadline = time.time() + min(timeout, 300.0)  # 最多等 5 分钟收集凭证

        while time.time() < deadline:
            credentials = self._assemble_credentials()
            if credentials:
                # 用适配器验证
                result = await self.validate_credentials(credentials)
                if result.success:
                    # 保存到 config.yaml
                    await self._save_credentials(result.credentials or credentials)
                    return result

            await asyncio.sleep(2.0)

        return OAuthResult(
            success=False,
            provider=self.provider,
            error="No valid credentials captured after login",
        )

    def _assemble_credentials(self) -> dict[str, str]:
        """从已捕获的数据组装凭证

        对齐 Chat2API OAuthManager._assembleCredentials():
        1. 从 localStorage 组装 token / user_id
        2. 从 cookies 组装 cookie / ticket
        3. 从 network headers 组装 token
        """
        creds: dict[str, str] = {}

        # localStorage
        for key, value in self._captured_local_storage.items():
            if not self._is_valid_token(value):
                continue

            if key == "_token":
                creds["token"] = value
            elif key == "user_detail_agent":
                user_detail = self._try_parse_json(value)
                if user_detail:
                    real_user_id = (
                        user_detail.get("realUserID")
                        or user_detail.get("id")
                        or (user_detail.get("user", {}).get("id") if isinstance(user_detail.get("user"), dict) else None)
                    )
                    if real_user_id:
                        creds["user_id"] = str(real_user_id)
                    token_val = (
                        user_detail.get("token")
                        or user_detail.get("value")
                        or (user_detail.get("user", {}).get("token") if isinstance(user_detail.get("user"), dict) else None)
                    )
                    if token_val:
                        creds["token"] = str(token_val)
            elif key == "userToken":
                creds["token"] = value
            elif key == "access_token":
                creds["token"] = value
            elif key == "refresh_token":
                if "token" not in creds:
                    creds["refresh_token"] = value
            elif key == "x_token":
                creds["x_token"] = value
            elif key == "serviceToken":
                creds["serviceToken"] = value
            elif key == "xiaomichatbot_ph":
                creds["xiaomichatbot_ph"] = value
            elif key == "token":
                # GLM 把 refresh_token 存到 localStorage.token
                # 必须优先于通用 else 分支处理
                if "refresh_token" not in creds and "chatglm_refresh_token" not in creds:
                    creds["refresh_token"] = value
                creds["token"] = value
            elif key == "chatglm_refresh_token":
                creds["chatglm_refresh_token"] = value
                creds["refresh_token"] = value
            elif key == "refreshToken":
                creds["refresh_token"] = value
            else:
                creds[key] = value

        # cookies — 构建完整 cookie 字符串（对齐 Chat2API）
        captured_cookie_parts = []
        for key, value in self._captured_cookies.items():
            if key == "_all_" and self._is_valid_token(value):
                # 全量 cookie 字符串直接使用
                if value not in captured_cookie_parts:
                    captured_cookie_parts.append(value)
            elif key and value and self._is_valid_token(value):
                if f"{key}=" not in "; ".join(captured_cookie_parts):
                    captured_cookie_parts.append(f"{key}={value}")

        if captured_cookie_parts:
            full_cookie = "; ".join(captured_cookie_parts)
            if len(full_cookie) > 50:
                creds["cookie"] = full_cookie

        # network Authorization headers
        for token in self._captured_auth_headers:
            if self._is_valid_token(token) and "token" not in creds:
                creds["token"] = token
                break

        return creds

    async def _save_credentials(self, credentials: dict[str, str]):
        """保存凭证到 config.yaml（对齐 Chat2API 保存逻辑 + 实际 Provider API）"""
        self._emit_progress("pending", "Saving credentials to config...")

        from src.utils.crypto import credential_crypto

        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        providers = config.setdefault("providers", {})
        provider_entry = providers.setdefault(self.provider, {"enabled": True, "accounts": []})

        accounts = provider_entry["accounts"]
        if not accounts:
            accounts.append({
                "name": "account-1",
                "models": [],
                "max_concurrent": 5,
                "health_check_interval": 60,
            })
        account = accounts[0]

        # 清空旧凭证字段（避免混淆）
        for f in ("token", "cookie", "user_id", "refresh_token",
                  "service_token", "xiaomichatbot_ph", "x_token"):
            account.pop(f, None)

        # 根据 provider 类型保存字段（对齐各 Provider 传输协议）
        # 所有凭证字段都要加密存储（对齐 Chat2API storeManager.encryptCredentials）
        if self.provider == "doubao":
            # 豆包：完整 Cookie 字符串
            cookie = credentials.get("cookie")
            if cookie and len(cookie) > 50:
                account["cookie"] = credential_crypto.encrypt(cookie)
                self._emit_progress("success", f"Cookie saved ({len(cookie)} chars, encrypted)")
            else:
                self._emit_progress("error", "No valid cookie captured for Doubao")
                return
        elif self.provider == "yuanbao":
            # 腾讯元宝：Cookie + x_token
            cookie = credentials.get("cookie")
            x_token = credentials.get("x_token")
            if cookie and len(cookie) > 50:
                account["cookie"] = credential_crypto.encrypt(cookie)
                self._emit_progress("success", f"Cookie saved ({len(cookie)} chars, encrypted)")
            else:
                self._emit_progress("error", "No valid cookie captured for Yuanbao")
                return
            if x_token:
                account["x_token"] = credential_crypto.encrypt(x_token)
        elif self.provider == "qwen":
            # 通义千问：tongyi_sso_ticket
            ticket = credentials.get("ticket") or credentials.get("tongyi_sso_ticket") or credentials.get("token")
            if ticket:
                account["token"] = credential_crypto.encrypt(ticket)
                self._emit_progress("success", f"Qwen token saved ({len(ticket)} chars, encrypted)")
            else:
                self._emit_progress("error", "No valid ticket captured for Qwen")
                return
        elif self.provider == "minimax":
            # MiniMax：user_id:token 拼接
            token = credentials.get("token")
            user_id = credentials.get("user_id")
            if token:
                if user_id:
                    account["token"] = credential_crypto.encrypt(f"{user_id}:{token}")
                    account["user_id"] = credential_crypto.encrypt(user_id)
                else:
                    account["token"] = credential_crypto.encrypt(token)
                self._emit_progress("success", f"MiniMax token saved (encrypted)")
            else:
                self._emit_progress("error", "No valid token captured for MiniMax")
                return
        elif self.provider == "mimo":
            # MiMo：3 个必需字段（对齐 Chat2API mimo.ts）
            service_token = credentials.get("service_token") or credentials.get("serviceToken") or credentials.get("token")
            user_id = credentials.get("user_id") or credentials.get("userId")
            ph_token = credentials.get("xiaomichatbot_ph") or credentials.get("ph_token")
            if not service_token:
                self._emit_progress("error", "MiMo: serviceToken is required")
                return
            account["service_token"] = credential_crypto.encrypt(service_token)
            if user_id:
                account["user_id"] = credential_crypto.encrypt(user_id)
            if ph_token:
                account["xiaomichatbot_ph"] = credential_crypto.encrypt(ph_token)
            self._emit_progress("success", "MiMo credentials saved (encrypted)")
        elif self.provider == "glm":
            # 智谱 GLM：Bearer Token
            token = credentials.get("token") or credentials.get("refresh_token")
            if token:
                account["token"] = credential_crypto.encrypt(token)
                self._emit_progress("success", f"GLM token saved ({len(token)} chars, encrypted)")
            else:
                self._emit_progress("error", "No valid token captured for GLM")
                return
        elif self.provider == "coze":
            # Coze: PAT
            token = credentials.get("token")
            if token:
                account["token"] = credential_crypto.encrypt(token)
                self._emit_progress("success", "Coze token saved (encrypted)")
            else:
                self._emit_progress("error", "No token captured for Coze")
                return
        else:
            # deepseek / kimi 等：直接 Bearer Token
            token = (
                credentials.get("token")
                or credentials.get("userToken")
                or credentials.get("access_token")
                or credentials.get("refresh_token")
            )
            if token:
                account["token"] = credential_crypto.encrypt(token)
                self._emit_progress("success", f"Token saved ({len(token)} chars, encrypted)")
            else:
                self._emit_progress("error", f"No valid token captured for {self.provider}")
                return

        # 写回
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        self._emit_progress("success", "Credentials saved to config.yaml")

    # ---- 事件发射 ----

    def _emit_progress(self, status: str, message: str):
        """发射进度事件"""
        if self._on_progress:
            self._on_progress(status, message)

    def _emit_token(self, key: str, value: str):
        """发射 Token 找到事件"""
        if self._on_token_found:
            self._on_token_found(key, value)

    # ---- 清理 ----

    async def _cleanup(self):
        """清理浏览器资源"""
        self._is_completed = True

        if self.context:
            try:
                await self.context.storage_state(path=str(self._storage_path))
            except Exception:
                pass

        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
