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
        token_sources=[TokenSource(type="cookie", key="")],  # 全量 cookie
        target_domains=[".doubao.com", "doubao.com"],
        success_url_patterns=["doubao.com/chat"],
        window_title="Doubao Login",
    ),
    "glm": TokenExtractionConfig(
        login_url="https://open.bigmodel.cn",
        token_sources=[],  # 官方 API Key，需手动输入
        target_domains=[".bigmodel.cn", "bigmodel.cn"],
        success_url_patterns=["open.bigmodel.cn"],
        window_title="GLM Login",
    ),
    "yuanbao": TokenExtractionConfig(
        login_url="https://yuanbao.tencent.com/chat/",
        token_sources=[TokenSource(type="cookie", key="")],  # 全量 cookie
        target_domains=[".tencent.com", "yuanbao.tencent.com"],
        success_url_patterns=["yuanbao.tencent.com/chat"],
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
                args=["--no-sandbox", "--disable-setuid-sandbox"],
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

        if not self.headless:
            await self.page.goto(self.cfg.login_url, wait_until="domcontentloaded")
        else:
            await self.page.goto(self.cfg.login_url, wait_until="domcontentloaded")

        self._emit_progress(
            "pending",
            f"Login window ready — please log in at {self.cfg.login_url}\n"
            "The browser will automatically extract your credentials after login.",
        )

        # 等待登录成功（URL 变化或检测到凭证）
        deadline = time.time() + timeout
        last_check = 0.0

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
        """等待足够凭证后验证并保存"""
        deadline = time.time() + min(timeout, 60.0)  # 最多再等 60s 收集凭证

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
        """从已捕获的数据组装凭证"""
        creds: dict[str, str] = {}

        # localStorage
        for key, value in self._captured_local_storage.items():
            if self._is_valid_token(value):
                if key == "_token":
                    creds["token"] = value
                elif key == "user_detail_agent":
                    # 提取 realUserID
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
                else:
                    creds[key] = value

        # cookies
        for key, value in self._captured_cookies.items():
            if key == "_all_":
                creds["cookie"] = value
            elif self._is_valid_token(value):
                if key == "tongyi_sso_ticket":
                    creds["ticket"] = value
                elif key == "kimi-auth":
                    creds["kimi_auth"] = value
                else:
                    creds[key] = value

        # 从捕获的 auth header
        for token in self._captured_auth_headers:
            if self._is_valid_token(token):
                if "token" not in creds:
                    creds["token"] = token
                    break

        return creds

    async def _save_credentials(self, credentials: dict[str, str]):
        """保存凭证到 config.yaml（对齐 Chat2API 保存逻辑）"""
        self._emit_progress("pending", "Saving credentials to config...")

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

        # 根据 provider 类型保存字段
        if self.provider == "doubao" or self.provider == "yuanbao":
            cookie = credentials.get("cookie") or credentials.get("_all_")
            if cookie:
                account["cookie"] = cookie
        elif self.provider == "qwen":
            ticket = credentials.get("ticket") or credentials.get("tongyi_sso_ticket")
            if ticket:
                account["token"] = ticket
        elif self.provider == "minimax":
            token = credentials.get("token")
            user_id = credentials.get("user_id")
            if token:
                if user_id:
                    account["token"] = f"{user_id}:{token}"
                    account["user_id"] = user_id
                else:
                    account["token"] = token
        elif self.provider == "mimo":
            # MiMo 需要 3 个字段（对齐 Chat2API mimo.ts）
            service_token = credentials.get("service_token") or credentials.get("serviceToken")
            user_id = credentials.get("user_id") or credentials.get("userId")
            ph_token = credentials.get("xiaomichatbot_ph") or credentials.get("ph_token")
            if service_token:
                account["service_token"] = service_token
            if user_id:
                account["user_id"] = user_id
            if ph_token:
                account["xiaomichatbot_ph"] = ph_token
        else:
            token = credentials.get("token") or credentials.get("userToken") or credentials.get("access_token")
            if token:
                account["token"] = token

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
