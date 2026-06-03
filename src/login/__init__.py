# -*- coding: utf-8 -*-
"""
WebAPI — 自动登录 Token 提取器

通过 Playwright 驱动浏览器打开各厂商网页版，引导用户登录后自动提取
Token / Cookie / JWT，保存到 config.yaml。

用法：
  python -m src.login deepseek    # 打开 DeepSeek 网页提取 Token
  python -m src.login minimax     # 打开 MiniMax 网页提取 Token
  python -m src.login doubao      # 打开豆包网页提取 Cookie
  python -m src.login yuanbao     # 打开元宝网页提取 Cookie
  python -m src.login qwen        # 打开通义千问网页提取 Token
  python -m src.login kimi        # 打开 Kimi 网页提取 Token

支持 provider: deepseek, kimi, qwen, minimax, doubao, yuanbao
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

# =============================================================================
# Provider 配置：每个 Provider 的登录 URL、Token 提取规则
# =============================================================================

PROVIDER_CONFIGS = {
    # ─── 对齐 Chat2API tokenExtractionConfig.ts ───
    "deepseek": {
        "name": "DeepSeek",
        "login_url": "https://chat.deepseek.com/",
        # Chat2API 只需 localStorage.userToken（JWT），不需要 cookie
        "auth_type": "token",
        "success_url_patterns": ["chat.deepseek.com"],
        "target_domains": [".deepseek.com", "deepseek.com"],
        "extractors": [
            # 优先：localStorage.userToken（Chat2API 的主提取方式）
            {
                "type": "localStorage",
                "key": "userToken",
                "save_as": "token",
            },
            # 兜底：从网络请求截取 Authorization header
            {
                "type": "network_auth",
                "save_as": "token",
                "url_pattern": "deepseek.com/api/",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
        ],
        # Chat2API DeepSeekAdapter.validateToken: GET /api/v0/users/current
        "validate_url": "https://chat.deepseek.com/api/v0/users/current",
        "validate_method": "bearer",
        "config_key": "token",
    },
    "kimi": {
        "name": "Kimi (月之暗面)",
        "login_url": "https://www.kimi.com/",
        "auth_type": "token",
        "success_url_patterns": ["kimi.com"],
        "target_domains": [".kimi.com", "kimi.com"],
        "extractors": [
            # ★ 用户明确要求：Kimi 访问令牌从浏览器 Cookie 的 kimi-auth 字段值（推荐）
            # 优先：浏览器 cookie 中的 kimi-auth
            {
                "type": "cookie",
                "keys": ["kimi-auth"],
                "save_as": "token",
            },
            # 兜底 1：从网络请求的 Cookie header 中截取 kimi-auth
            {
                "type": "network_cookie",
                "url_pattern": "kimi.com",
                "cookie_name": "kimi-auth",
                "save_as": "token",
            },
            # 兜底 2：从网络请求截取 Authorization header (JWT Token)
            {
                "type": "network_auth",
                "url_pattern": "kimi.com/api",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
                "save_as": "token",
            },
            # 兜底 3：localStorage 中的 refresh_token
            {
                "type": "localStorage",
                "key": "refresh_token",
                "save_as": "token",
            },
            # 兜底 4：localStorage 中的 access_token
            {
                "type": "localStorage",
                "key": "access_token",
                "save_as": "token",
            },
            # 兜底 5：localStorage 中的 kimi_at
            {
                "type": "localStorage",
                "key": "kimi_at",
                "save_as": "token",
            },
            # 兜底 6：localStorage 中的 auth_token
            {
                "type": "localStorage",
                "key": "auth_token",
                "save_as": "token",
            },
        ],
        "validate_url": "https://www.kimi.com/api/user",
        "validate_method": "bearer",
        "validate_field": "name",
        "config_key": "token",
    },
    "qwen": {
        "name": "通义千问 (Alibaba)",
        "login_url": "https://www.qianwen.com/?source=tongyigw",
        "auth_type": "token",
        "success_url_patterns": ["qianwen.com"],
        "target_domains": [".qianwen.com", "qianwen.com"],
        "extractors": [
            # Chat2API qwen tokenSource: cookie, key=tongyi_sso_ticket
            # 优先：从浏览器 cookie 直接取 tongyi_sso_ticket
            {
                "type": "cookie",
                "keys": ["tongyi_sso_ticket"],
                "save_as": "token",
            },
            # 兜底：从网络请求的 Cookie header 中截取
            {
                "type": "network_cookie",
                "url_pattern": "qianwen.com",
                "cookie_name": "tongyi_sso_ticket",
                "save_as": "token",
            },
        ],
        # Chat2API QwenAdapter.validateToken: POST chat2-api.qianwen.com/api/v2/session/page/list
        "validate_url": "https://chat2-api.qianwen.com/api/v2/session/page/list",
        "validate_method": "cookie_ticket",
        "validate_field": "success",
        "config_key": "token",
    },
    "minimax": {
        "name": "MiniMax (海螺 AI) — 官方 OpenAI 兼容 API",
        # 官方 API: https://api.minimaxi.com/v1
        # 用户在 https://platform.minimaxi.com/ 创建 API Key（eyJ 开头的 JWT）
        "login_url": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
        "auth_type": "manual_token",
        "success_url_patterns": ["minimaxi.com", "platform.minimaxi"],
        "target_domains": [".minimaxi.com", "minimaxi.com"],
        "extractors": [
            # 官方 API Key 需要用户手动从控制台复制
            # 不支持浏览器自动登录提取（agent.minimaxi.com 是消费版，不是 API 入口）
        ],
        "validate_url": "https://api.minimaxi.com/v1/models",
        "validate_method": "bearer",
        "validate_header_prefix": "Bearer ",
        "config_key": "token",
        "instructions": [
            "MiniMax 使用官方 OpenAI 兼容 API。",
            "",
            "获取 API Key 步骤：",
            "1. 访问 https://platform.minimaxi.com/ 登录账号",
            "2. 右上角「接口密钥」 → 「创建新的 API Key」",
            "3. 复制 eyJ... 格式的 Key（JWT）",
            "4. 粘贴到 config.yaml 的 providers.minimax.accounts[0].token",
            "",
            "⚠️ 账号配置中如果存在 api_base 字段，请设为 https://api.minimaxi.com/v1",
            "💡 支持的模型: MiniMax-M3, MiniMax-M2.7, MiniMax-M2.7-highspeed, MiniMax-M2.5, MiniMax-M2.5-highspeed, MiniMax-M2.1, MiniMax-M2.1-highspeed, MiniMax-M2",
        ],
    },
    "doubao": {
        "name": "豆包 (Doubao · 字节跳动)",
        "login_url": "https://www.doubao.com/chat/",
        "auth_type": "cookie",
        "success_url_patterns": ["doubao.com/chat", "doubao.com/conversation"],
        "target_domains": [".doubao.com", "doubao.com"],
        "extractors": [
            # 豆包: Cookie 全量提取
            {
                "type": "all_cookies",
                "format": "header_string",
            },
        ],
        "cookie_validate_url": "https://www.doubao.com/chat/",
        "cookie_validate_check": "doubao",
        "config_key": "cookie",
    },
    "glm": {
        "name": "智谱 GLM (ZhipuAI) — 官方 BigModel API",
        # 官方 API: https://open.bigmodel.cn/api/paas/v4
        # 用户在 https://open.bigmodel.cn/ 创建 API Key（以 sk- 开头）
        "login_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "auth_type": "manual_token",
        "success_url_patterns": ["open.bigmodel.cn"],
        "target_domains": [".bigmodel.cn", "bigmodel.cn"],
        "extractors": [
            # 官方 API Key 需要用户手动从控制台复制
            # 不支持浏览器自动登录提取
        ],
        "validate_url": "https://open.bigmodel.cn/api/paas/v4/models",
        "validate_method": "bearer",
        "validate_header_prefix": "Bearer ",
        "config_key": "token",
        "instructions": [
            "智谱 GLM 使用官方 BigModel API（OpenAI 兼容）。",
            "",
            "获取 API Key 步骤：",
            "1. 访问 https://open.bigmodel.cn/ 登录账号",
            "2. 右上角「API 密钥」 → 「创建新的 API Key」",
            "3. 复制 sk-xxx... 格式的 Key",
            "4. 粘贴到 config.yaml 的 providers.glm.accounts[0].token",
            "",
            "⚠️ API Key 仅创建时显示一次，请妥善保存。",
            "💡 智谱新账号通常有 200万 Tokens 免费额度，足够测试用。",
        ],
    },
    "yuanbao": {
        "name": "腾讯元宝 (Yuanbao)",
        "login_url": "https://yuanbao.tencent.com/chat/",
        "auth_type": "cookie",
        "success_url_patterns": ["yuanbao.tencent.com/chat", "yuanbao.tencent.com/conversation"],
        "target_domains": [".tencent.com", "yuanbao.tencent.com"],
        "extractors": [
            # 腾讯元宝: 全部 Cookie
            {
                "type": "all_cookies",
                "format": "header_string",
            },
            # 额外提取 page HTML 中的 x_token
            {
                "type": "html",
                "pattern": r'["\']x_token["\']\s*:\s*["\']([^"\']+)["\']',
                "name": "x_token",
            },
        ],
        "cookie_validate_url": "https://yuanbao.tencent.com/chat/",
        "cookie_validate_check": "yuanbao",
        "config_key": "cookie",
    },
    "coze": {
        "name": "Coze (扣子)",
        "login_url": "https://www.coze.cn/",
        "auth_type": "manual_pat",
        "extractors": [],
        "config_key": "token",
        "pat_instructions": [
            "Coze 使用 Personal Access Token (PAT) 认证",
            "",
            "获取 PAT 步骤：",
            "1. 访问 https://www.coze.cn/home/ → 登录你的扣子账号",
            "2. 点击左下角头像 → 「个人设置」→「访问令牌 (PAT)」",
            "3. 点击「新建令牌」→ 设置名称和过期时间 → 复制生成的 Token",
            "",
            "⚠️ Token 只显示一次，请妥善保存！",
        ],
    },
}


# =============================================================================
# 主登录逻辑
# =============================================================================

class TokenExtractor:
    """自动登录 Token 提取器"""

    def __init__(self, provider: str, headless: bool = False):
        if provider not in PROVIDER_CONFIGS:
            raise ValueError(
                f"Unknown provider: {provider}. "
                f"Available: {', '.join(PROVIDER_CONFIGS.keys())}"
            )
        self.provider = provider
        self.cfg = PROVIDER_CONFIGS[provider]
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.extracted = {}
        self._network_requests = []  # 存储捕获的网络请求头

    async def run(self) -> dict:
        """主流程：打开浏览器 → 等待用户登录 → 提取 Token → 保存"""
        print(f"\n{'='*60}")
        print(f"  {self.cfg['name']} 自动登录 & Token 提取")
        print(f"{'='*60}")
        print(f"\n  登录页面: {self.cfg['login_url']}")
        print(f"  认证方式: {self.cfg['auth_type']}")
        print(f"  浏览器模式: {'无头' if self.headless else '可视化'}")
        print(f"\n  请在打开的浏览器窗口中完成登录...")
        print(f"  登录成功后 Token 将自动提取。\n")

        await self._start_browser()
        await self._navigate_login()
        token = await self._wait_and_extract()

        if token:
            await self._validate_token(token)
            await self._save_to_config(token)

        await self._cleanup()
        return self.extracted

    async def _start_browser(self):
        """启动 Playwright 浏览器（自动 fallback headless 模式）"""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "未安装 playwright，请先运行:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            ) from e

        # 检查 Chromium 是否已安装
        self.playwright = await async_playwright().start()
        try:
            self.playwright.chromium.executable_path
        except Exception:
            if self.playwright:
                await self.playwright.stop()
            raise RuntimeError(
                "Playwright Chromium 浏览器未安装，请运行:\n"
                "  playwright install chromium"
            )

        # 尝试启动浏览器（GUI 模式 → 无头模式自动降级）
        browser_started = False
        attempts = [
            (self.headless, "GUI"),
            (True, "无头"),
        ]

        last_error = ""
        for headless_mode, mode_name in attempts:
            try:
                self.browser = await self.playwright.chromium.launch(
                    headless=headless_mode,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                browser_started = True
                if headless_mode != self.headless:
                    print(f"  [i]  GUI 模式不可用，已自动切换到无头模式")
                    print(f"       浏览器将在后台运行，登录页面 URL 见下方提示")
                if headless_mode:
                    print(f"  [i]  无头模式：请手动打开浏览器访问登录页面")
                break
            except Exception as e:
                last_error = str(e)
                if headless_mode == self.headless:
                    print(f"  [i]  {mode_name} 模式启动失败: {e}")
                if self.browser:
                    try:
                        await self.browser.close()
                    except Exception:
                        pass
                    self.browser = None
                continue

        if not browser_started:
            if self.playwright:
                await self.playwright.stop()
            raise RuntimeError(
                f"Playwright 浏览器启动失败（已尝试 GUI 和无头模式）\n"
                f"  错误: {last_error}\n"
                f"  可能原因:\n"
                f"    1. Chromium 未安装: playwright install chromium\n"
                f"    2. 系统缺少依赖（Linux 需 libnss3 等）\n"
                f"  替代方案: 使用「✏️ 输入」按钮手动粘贴 Token/Cookie"
            )

        # 持久化 storage_state 以便复用登录
        storage_dir = PROJECT_ROOT / "data" / "browser_states"
        storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_dir / f"{self.provider}.json"

        context_kwargs = dict(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        if self._storage_path.exists():
            context_kwargs["storage_state"] = str(self._storage_path)
            print("  [i]  加载了已保存的浏览器状态（保持登录）")

        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()

        # 拦截所有网络请求，捕获 Authorization header
        def capture_request_info(request):
            try:
                self._network_requests.append({
                    "url": request.url,
                    "headers": dict(request.headers),
                })
            except Exception:
                pass
        self.page.on("request", capture_request_info)

    async def _navigate_login(self):
        """导航到登录页面，并设置请求/响应拦截捕获 Token"""
        await self.page.goto(self.cfg["login_url"], wait_until="domcontentloaded")
        await asyncio.sleep(3)

        self._start_url = self.page.url
        self._captured_auth_headers: list[str] = []  # 拦截到的 Authorization header
        self._captured_cookies: dict[str, str] = {}   # 拦截到的 Set-Cookie（cookie_name → value）
        self._captured_cookie_headers: dict[str, list[str]] = {}  # 从请求 Cookie header 中提取的值

        # ── 模拟 Chat2API 的 onBeforeSendHeaders ──
        # 用 page.route() 拦截所有请求，捕获 Authorization 和 Cookie headers
        async def intercept_request(route):
            request = route.request
            auth = request.headers.get("authorization", "")
            cookie = request.headers.get("cookie", "")

            # 捕获 Authorization header
            if auth and auth.startswith("Bearer ") and len(auth) > 20:
                token = auth[7:]  # 去掉 "Bearer "
                if token not in self._captured_auth_headers:
                    self._captured_auth_headers.append(token)
                    print(f"  [>>] Captured Auth header ({len(token)} chars)")

            # 捕获 Cookie header（用于 qwen 的 tongyi_sso_ticket 等）
            if cookie:
                # 提取已知的关键 cookie 字段
                _cookie_keys_of_interest = ("tongyi_sso_ticket", "chatglm_refresh_token")
                for ck_name in _cookie_keys_of_interest:
                    if ck_name in cookie:
                        match = re.search(rf"{re.escape(ck_name)}=([^;]+)", cookie)
                        if match:
                            val = match.group(1)
                            bucket = self._captured_cookie_headers.setdefault(ck_name, [])
                            if val not in bucket:
                                bucket.append(val)
                                print(f"  [>>] Captured Cookie header ({ck_name}, {len(val)} chars)")

            await route.continue_()

        await self.page.route("**/*", intercept_request)

        # ── 模拟 Chat2API 的 onHeadersReceived ──
        # 捕获 Set-Cookie 响应头
        def capture_response(response):
            try:
                set_cookie = response.headers.get("set-cookie", "")
                if set_cookie:
                    for part in set_cookie.split(";"):
                        part = part.strip()
                        if "=" in part:
                            k, v = part.split("=", 1)
                            if k and v:
                                self._captured_cookies[k] = v
            except Exception:
                pass
        self.page.on("response", capture_response)

        # ── Chat2API 风格：导航事件触发延迟 Token 检查 ──
        # 当页面完成导航（登录后跳转）时，触发 token 检查
        self._login_start_time = time.time()
        self._last_token_check = 0.0

        async def on_navigated(frame):
            if frame != self.page.main_frame:
                return
            # 等待最少 5 秒后再检查（避免 storage_state 直接命中）
            await asyncio.sleep(1)
            # 触发一轮立即检查（不等待 poll_interval）
            self._last_token_check = 0.0  # 重置，下次循环会立即检查

        self.page.on("framenavigated", on_navigated)

        print("  [...] Waiting for login (auto-detect if already logged in)...")
        print("  [i]  Please operate in the browser window. Do not close it.")

    async def _wait_and_extract(self) -> Optional[str]:
        """等待用户登录后提取 Token（复刻 Chat2API 的事件驱动方式）

        不再通过 URL 判断登录，而是直接监控：
        1. page.route() 拦截的 Authorization headers（onBeforeSendHeaders）
        2. page.on("response") 捕获的 Set-Cookie（onHeadersReceived）
        3. localStorage / cookies 轮询（delayedTokenCheck）
        """
        auth_type = self.cfg["auth_type"]
        config_key = self.cfg["config_key"]
        extractors = self.cfg.get("extractors", [])

        # success URL patterns — 登录后跳转到的页面特征
        success_patterns = self.cfg.get("success_url_patterns", [])
        if not success_patterns:
            # 默认：URL 中出现 /chat/ 即可（排除 login_url 本身含 /chat/ 的情况）
            success_patterns = ["/chat/", "/a/chat/"]

        max_wait_seconds = 600  # 最多等 10 分钟
        poll_interval = 1.5    # 轮询间隔
        min_wait = 5           # 最少等 5 秒再开始判断（避免存储态直接命中）

        start = time.time()
        login_detected = False
        extracted_values: dict[str, Any] = {}

        # ── 检查是否已登录（storage_state 恢复时）──
        if any(p in self.page.url for p in success_patterns):
            if self.page.url != self.cfg["login_url"]:
                login_detected = True
                print(f"\n  [i]  Already logged in (URL: {self.page.url[:80]}...)")

        last_token_check = 0.0

        while time.time() - start < max_wait_seconds:
            current_url = self.page.url

            # ── 1. 检测登录成功（URL 跳转）──
            if not login_detected:
                if current_url != self._start_url and any(p in current_url for p in success_patterns):
                    login_detected = True
                    print(f"\n  [OK] Login detected! URL: {current_url[:80]}...")

            # ── 2. 延迟 Token 检查（模拟 delayedTokenCheck）──
            now = time.time()
            elapsed = now - start
            if elapsed > min_wait and now - last_token_check >= 2.0:
                last_token_check = now

                # 2a. 从 localStorage 提取
                if not login_detected:
                    # 未登录时也检查（可能之前已登录但 storage_state 没反应过来）
                    await asyncio.sleep(0.5)

                for extractor in extractors:
                    save_as = extractor.get("save_as", config_key)
                    t = extractor["type"]

                    # 使用 _try_extract 统一处理所有提取器类型
                    extracted_value = await self._try_extract(extractor)
                    if extracted_value:
                        # 长度校验
                        min_len = 80 if save_as == "cookie" else 20
                        if len(str(extracted_value)) >= min_len:
                            if self._is_valid_token(extracted_value):
                                extracted_values[save_as] = extracted_value
                                # ★ 后处理钩子：例如 jwt_user_id 解析 Real User ID
                                post_proc = extractor.get("post_process")
                                if post_proc:
                                    processed = self._post_process(extracted_value, extractor)
                                    extra_user_id = processed.get("user_id")
                                    if extra_user_id:
                                        # 如果用户明确要求从 JWT 解析 user_id（如 minimax），覆盖
                                        extracted_values["user_id"] = extra_user_id
                                        self.extracted["user_id"] = extra_user_id
                                        print(f"  [OK] {t}.{extractor.get('key', extractor.get('cookie_name', extractor.get('name', '')))} → {save_as} ({len(str(extracted_value))} chars) + user_id={extra_user_id}")
                                    else:
                                        print(f"  [OK] {t}.{extractor.get('key', extractor.get('cookie_name', extractor.get('name', '')))} → {save_as} ({len(str(extracted_value))} chars) [post_process={post_proc} 无结果]")
                                else:
                                    print(f"  [OK] {t}.{extractor.get('key', extractor.get('cookie_name', extractor.get('name', '')))} → {save_as} ({len(str(extracted_value))} chars)")
                            else:
                                print(f"  [WARN]  Extracted value too short or invalid ({len(str(extracted_value))} chars)")
                        else:
                            print(f"  [WARN]  Extracted value too short ({len(str(extracted_value))} chars, min {min_len})")

            # ── 3. 判断是否提取完毕（Chat2API 风格：信任 localStorage，信任 network_header）──
            if auth_type == "both":
                # deepseek: 需要 cookie + token
                has_cookie = bool(extracted_values.get("cookie", ""))
                has_token = bool(extracted_values.get("token", ""))
                if has_cookie and has_token and len(str(extracted_values["cookie"])) > 80:
                    self.extracted = extracted_values
                    return extracted_values["cookie"]
            else:
                val = extracted_values.get(config_key)
                if val:
                    # 长度校验
                    min_len = 80 if config_key == "cookie" else 20
                    if len(str(val)) >= min_len:
                        # 信任 localStorage / network_header 来源的 token（它们是浏览器实际使用的凭证）
                        # 仅对 cookie 类型做实际 API 验证（Cookie 可被服务端直接验证）
                        if config_key == "cookie":
                            is_valid = await self._validate_extracted_value(val, config_key)
                            if not is_valid:
                                # Cookie 无效，清除并继续等待
                                extracted_values.pop(config_key, None)
                                if login_detected:
                                    print(f"  [WARN]  Cookie validation failed, waiting for re-login...")
                                    login_detected = False
                                val = None
                        # token 类型：信任 localStorage/network_header（浏览器已用过，无需重复验证）
                        if val:
                            self.extracted = {
                                "type": auth_type,
                                "value": val,
                                "config_key": config_key,
                            }
                            # 附加 user_id
                            if extracted_values.get("user_id"):
                                self.extracted["user_id"] = extracted_values["user_id"]
                            return val

            await asyncio.sleep(poll_interval)

            # 每 30 秒提示
            et = int(time.time() - start)
            if et % 30 == 0 and et > 0:
                if not login_detected:
                    print(f"  [...] Waiting for login... ({et}s / {max_wait_seconds}s)")
                else:
                    print(f"  [...] Waiting for valid token... ({et}s / {max_wait_seconds}s)")

        print(f"\n  [WARN]  Timeout after {max_wait_seconds}s")
        return None

    # 各 Provider 用来触发 API 请求以捕获 Cookie/Token 的探测 URL
    _PROBE_URLS = {
        "deepseek": "/api/v0/user/info",
        "kimi": "/api/user",
        "qwen": "/api/v1/user/info",
        "minimax": "/api/user/info",
        "doubao": "/api/chat/get_user_info",
        "yuanbao": "/api/user/info",
    }

    async def _trigger_api_requests(self):
        """通过 JS 在页面中触发 API 请求，以便截获 Cookie/Authorization header

        每个 provider 调用自己的探测端点，保证能捕获到对应域名的请求头。
        """
        probe_path = self._PROBE_URLS.get(self.provider, "/api/user/info")
        try:
            result = await self.page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch('{probe_path}', {{
                            method: 'GET',
                            credentials: 'include',
                            headers: {{ 'Accept': 'application/json' }}
                        }});
                        const data = await resp.json();
                        return JSON.stringify({{ ok: resp.ok, status: resp.status }});
                    }} catch(e) {{
                        return JSON.stringify({{ error: e.message }});
                    }}
                }}
            """)
            print(f"  [i]  API probe [{self.provider}]: {result}")
        except Exception as e:
            print(f"  [i]  API trigger: {e}")
        await asyncio.sleep(2)

    # ── Chat2API 复刻的 Token 有效性判断 ──
    @staticmethod
    def _is_valid_token(value: str) -> bool:
        """判断提取到的 Token 是否看起来有效（复刻 Chat2API isValidToken）"""
        if not value or len(str(value)) < 5:
            return False

        v = str(value)

        # JWT / JWE 检测
        if v.startswith("eyJ"):
            parts = v.split(".")
            # JWE (5 parts)
            if len(parts) == 5 and len(v) >= 100:
                return True
            # JWT (3 parts)
            if len(parts) == 3:
                import base64 as _b64
                try:
                    payload = json.loads(_b64.b64decode(parts[1] + "==").decode())
                    # 拒绝 guest 账号
                    if payload.get("email", "").endswith("@guest.com"):
                        return False
                    if payload.get("app_id") or payload.get("sub") or payload.get("exp") or \
                       payload.get("id") or payload.get("user_id") or payload.get("uid") or \
                       payload.get("email"):
                        return True
                except Exception:
                    return False

        # 长 Token (>=64 chars, base62)
        if len(v) >= 64 and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+/*" for c in v):
            return True

        # 中等 Token (32-63 chars, base62)
        if 32 <= len(v) < 64 and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+/*" for c in v):
            return True

        # Base64 Token (>=20 chars)
        if len(v) >= 20 and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+/=" for c in v):
            return True

        # 通用 Token (>=5 chars, no whitespace)
        if len(v) >= 5 and not any(c.isspace() for c in v):
            return True

        return False

    async def _validate_extracted_value(self, value: str, config_key: str) -> bool:
        """实际 API 调用验证提取到的凭证是否有效

        Chat2API 风格：直接用 aiohttp 请求验证，不走浏览器新页面（因为新页面不会继承登录上下文的认证状态）。
        """
        validate_url = self.cfg.get("validate_url")
        cookie_validate_url = self.cfg.get("cookie_validate_url")
        cookie_validate_check = self.cfg.get("cookie_validate_check", "")
        validate_method = self.cfg.get("validate_method", "")

        # 先尝试用 aiohttp 直接验证（Chat2API 风格）
        if config_key == "token" and validate_url and validate_method:
            print(f"  [*] Validating token via API: {validate_url}")
            try:
                import aiohttp
                import certifi

                headers = {}
                async with aiohttp.ClientSession() as session:
                    if validate_method == "bearer":
                        headers["Authorization"] = f"Bearer {value}"
                    elif validate_method == "bearer_refresh":
                        # GLM 使用 refresh_token
                        headers["Authorization"] = f"Bearer {value}"
                    elif validate_method == "cookie_ticket":
                        # qwen 使用 tongyi_sso_ticket cookie
                        headers["Cookie"] = f"tongyi_sso_ticket={value}"
                    elif validate_method == "minimax":
                        # MiniMax 需要 user_id + token 拼接
                        user_id = self.extracted.get("user_id")
                        if user_id:
                            headers["Authorization"] = f"Bearer {user_id}:{value}"
                        else:
                            print(f"  [WARN] MiniMax validation requires user_id, skipping")
                            return False

                    async with session.get(
                        validate_url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                        ssl=certifi.where(),
                    ) as resp:
                        body = await resp.text()
                        validate_field = self.cfg.get("validate_field", "")

                        if resp.ok:
                            if validate_field and validate_field in body:
                                print(f"  [OK] Token validated (contains '{validate_field}')")
                                return True
                            elif len(body) > 50:
                                print(f"  [OK] Token validated (HTTP {resp.status}, body={len(body)} chars)")
                                return True
                        print(f"  [WARN] Token validation: HTTP {resp.status}, body={len(body)} chars")
            except Exception as e:
                print(f"  [WARN] Token validation error: {e}")
                return False

        # Cookie 类验证：直接用 aiohttp 请求
        if config_key == "cookie" and cookie_validate_url:
            print(f"  [*] Validating cookie via API: {cookie_validate_url}")
            try:
                import aiohttp
                import certifi

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        cookie_validate_url,
                        timeout=aiohttp.ClientTimeout(total=15),
                        ssl=certifi.where(),
                    ) as resp:
                        body = await resp.text()
                        if cookie_validate_check and cookie_validate_check in body.lower():
                            print(f"  [OK] Cookie validated (contains '{cookie_validate_check}')")
                            return True
                        elif len(body) > 200:
                            print(f"  [OK] Cookie validated (HTTP {resp.status}, body={len(body)} chars)")
                            return True
                        print(f"  [WARN] Cookie validation: HTTP {resp.status}, body={len(body)} chars")
            except Exception as e:
                print(f"  [WARN] Cookie validation error: {e}")
                return False

        # 无验证 URL：信任长度
        print(f"  [i]  No validation endpoint, trusting length")
        return len(str(value)) >= (80 if config_key == "cookie" else 20)

    async def _try_extract(self, extractor: dict) -> Optional[str]:
        """尝试用单个提取器提取"""
        try:
            ext_type = extractor["type"]

            if ext_type == "localStorage":
                key = extractor["key"]
                value = await self.page.evaluate(f"localStorage.getItem('{key}')")
                if not value:
                    return None

                # 尝试 JSON 解析（localStorage 中 token 常是 JSON 字符串）
                try:
                    obj = json.loads(value)
                    if isinstance(obj, dict):
                        # 尝试常见 key
                        for k in ("value", "token", "access_token", "refresh_token", "chat_token"):
                            if k in obj and obj[k]:
                                value = str(obj[k])
                                break
                        else:
                            value = str(value)  # 原始 JSON 字符串
                    elif isinstance(obj, str):
                        value = obj
                except (json.JSONDecodeError, TypeError):
                    pass  # 纯字符串，直接用

                # 特殊处理：user_detail_agent → realUserID
                if key == "user_detail_agent" and value:
                    try:
                        ud = json.loads(value)
                        if isinstance(ud, dict) and ud.get("realUserID"):
                            self.extracted["user_id"] = str(ud["realUserID"])
                    except Exception:
                        pass

                return value if value else None

            elif ext_type == "cookie":
                keys = extractor.get("keys", [])
                fmt = extractor.get("format", "raw")  # raw | name_value
                cookies = await self.context.cookies()
                for cookie in cookies:
                    if cookie["name"] in keys:
                        value = cookie["value"]
                        if fmt == "name_value":
                            # 包装为 "name=value" 格式的 cookie 字符串
                            return f"{cookie['name']}={value}"
                        return value
                return None

            elif ext_type == "all_cookies":
                cookies = await self.context.cookies()
                fmt = extractor.get("format", "header_string")
                if fmt == "header_string":
                    return "; ".join(
                        f"{c['name']}={c['value']}"
                        for c in cookies
                        if c.get("name") and c.get("value")
                    )
                return json.dumps(cookies, ensure_ascii=False)

            elif ext_type == "network_auth":
                # 从已捕获的 Authorization header 中提取
                url_pattern = extractor.get("url_pattern", "")
                header_key = extractor.get("header_key", "Authorization").lower()
                header_prefix = extractor.get("header_prefix", "Bearer ")

                for req in self._network_requests:
                    if url_pattern and url_pattern not in req["url"]:
                        continue
                    for key, val in req["headers"].items():
                        if key.lower() != header_key:
                            continue
                        if not val.startswith(header_prefix):
                            continue
                        token = val[len(header_prefix):]
                        if len(token) > 10:
                            return token
                # 也检查 _captured_auth_headers
                for token in self._captured_auth_headers:
                    if len(token) > 10:
                        return token
                return None

            elif ext_type == "network_cookie":
                # 从已捕获的网络请求 Cookie header 中提取指定 cookie
                url_pattern = extractor.get("url_pattern", "")
                cookie_name = extractor.get("cookie_name", "")

                # 先从 _captured_cookies 查找
                captured = self._captured_cookies.get(cookie_name, [])
                if captured:
                    return captured[-1]  # 最新捕获的

                # 兜底：从 _network_requests 的 Cookie header 中解析
                for req in self._network_requests:
                    if url_pattern and url_pattern not in req["url"]:
                        continue
                    cookie_header = req["headers"].get("cookie", "")
                    if cookie_header and cookie_name in cookie_header:
                        match = re.search(rf"{re.escape(cookie_name)}=([^;]+)", cookie_header)
                        if match:
                            return match.group(1)
                return None

            elif ext_type == "network_set_cookie":
                # 从 Set-Cookie 响应头中提取指定 cookie
                cookie_name = extractor.get("cookie_name", "")

                # 先从 _captured_cookies 查找（由 capture_response 捕获）
                # 注意 _captured_cookies 格式: { "cookie_name": "cookie_value" }
                # 但 capture_response 中是 dict[str, str]
                # 这里需要适配
                captured_val = self._captured_cookies.get(cookie_name, "")
                if captured_val and isinstance(captured_val, str):
                    return captured_val

                # 兜底：从浏览器 cookies 中查找（可能由 Set-Cookie 设置后写入）
                if cookie_name:
                    cookies = await self.context.cookies()
                    for c in cookies:
                        if c["name"] == cookie_name:
                            return c["value"]
                return None

            elif ext_type == "html":
                pattern = extractor.get("pattern", "")
                if pattern:
                    html = await self.page.content()
                    match = re.search(pattern, html)
                    if match:
                        self.extracted[extractor.get("name", "extra")] = match.group(1)
                        return match.group(1)
                return None

        except Exception:
            # 提取失败继续尝试下一个
            pass

        return None

    def _post_process(self, value: str, extractor: dict) -> dict:
        """对提取的 value 进行后处理

        当前支持:
        - jwt_user_id: 解析 JWT payload，提取 user_id（sub/uid/userId/user_id）
                     返回 {"token": jwt_str, "user_id": user_id}
        """
        proc = extractor.get("post_process")
        if not proc or not value:
            return {"value": value}

        if proc == "jwt_user_id":
            user_id = self._parse_jwt_user_id(value)
            if user_id:
                print(f"       [post_process] JWT user_id = {user_id}")
                return {"value": value, "user_id": user_id}
        return {"value": value}

    @staticmethod
    def _parse_jwt_user_id(jwt_str: str) -> Optional[str]:
        """解析 JWT，提取 user_id（尝试常见字段名）

        优先级：realUserId / real_user_id 优先（MiniMax 等需要 Real User ID），
        其次才是 sub / id / uid 等通用字段。
        """
        import base64
        if not jwt_str or "." not in jwt_str:
            return None
        try:
            # JWT: header.payload.signature
            parts = jwt_str.split(".")
            if len(parts) < 2:
                return None
            payload_b64 = parts[1]
            # base64url decode (补齐 padding)
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8", errors="replace"))
            # ★ 优先 Real User ID 字段（minimax 等）
            for key in (
                "realUserId", "real_user_id", "real_userid",
                "user_id", "userId", "uid",
                "id", "sub",
            ):
                v = payload.get(key)
                if v and isinstance(v, (str, int)):
                    return str(v)
            return None
        except Exception:
            return None

    async def _validate_token(self, token: str):
        """验证提取的凭证是否有效"""
        auth_type = self.cfg["auth_type"]

        if auth_type == "both":
            # 验证 cookie
            cookie = self.extracted.get("cookie")
            if cookie:
                validate_url = self.cfg.get("cookie_validate_url")
                check = self.cfg.get("cookie_validate_check", "")
                if validate_url:
                    print(f"  [*] 验证 Cookie: {validate_url}")
                    try:
                        vp = await self.context.new_page()
                        try:
                            # 用 cookie 访问 API
                            resp = await vp.goto(validate_url, timeout=15000)
                            if resp:
                                body = await resp.text()
                                if check and check in body.lower():
                                    print(f"  [OK] Cookie 验证成功")
                                elif resp.status == 200:
                                    print(f"  [OK] Cookie 验证通过 (HTTP 200)")
                                else:
                                    print(f"  [WARN]  Cookie 返回 HTTP {resp.status}")
                        finally:
                            await vp.close()
                    except Exception as e:
                        print(f"  [WARN]  Cookie 验证请求失败: {e}")
            # 验证 token
            user_token = self.extracted.get("token")
            if user_token:
                print(f"  [*] 验证 Token: {user_token[:20]}...")
                if len(str(user_token)) > 20:
                    print(f"  [OK] Token 已提取 ({len(str(user_token))} 字符)")

        if auth_type == "token":
            validate_url = self.cfg.get("validate_url")
            if not validate_url:
                print("  [i]  无验证接口，跳过验证")
                return

            header_key = self.extracted.get("extractor", {}).get("header_key", "Authorization")
            header_prefix = self.extracted.get("extractor", {}).get("header_prefix", "Bearer ")
            validate_field = self.cfg.get("validate_field", "")

            print(f"  [*] 验证 Token: {validate_url}")
            try:
                vp = await self.context.new_page()
                try:
                    await vp.set_extra_http_headers({
                        header_key: f"{header_prefix}{token}",
                    })
                    resp = await vp.goto(validate_url, timeout=15000)
                    if resp and resp.ok:
                        body = await resp.text()
                        if validate_field and validate_field in body:
                            print(f"  [OK] Token 验证成功（检测到 {validate_field}）")
                            return
                        elif len(body) > 50:
                            print(f"  [OK] Token 验证通过 (HTTP {resp.status})")
                            return
                    # 非 2xx — 不报错，只警告（避免端点变化导致 404 时拒绝保存有效 token）
                    if resp and resp.status in (401, 403):
                        print(f"  [ERR] 验证返回 HTTP {resp.status} — token 可能已失效")
                        # 不 return，让 save 流程继续（用户可手动检查）
                    else:
                        print(
                            f"  [WARN] 验证返回 HTTP {resp.status if resp else 'N/A'} — "
                            f"可能是验证端点变化，不影响 token 保存"
                        )
                finally:
                    await vp.close()
            except Exception as e:
                print(f"  [WARN] 验证请求失败: {e}")

        elif auth_type == "cookie":
            validate_url = self.cfg.get("cookie_validate_url")
            check = self.cfg.get("cookie_validate_check", "")
            if validate_url:
                print(f"  [*] 验证 Cookie: {validate_url}")
                try:
                    vp = await self.context.new_page()
                    try:
                        resp = await vp.goto(validate_url, timeout=15000)
                        if resp:
                            body = await resp.text()
                            if check and check in body.lower():
                                print(f"  [OK] Cookie 验证成功（未重定向到登录）")
                                return
                        print(f"  [WARN]  Cookie 可能已过期")
                    finally:
                        await vp.close()
                except Exception as e:
                    print(f"  [WARN]  验证请求失败: {e}")

    async def _save_to_config(self, token: str):
        """保存凭证到 config.yaml"""
        print(f"\n  [*] 保存配置...")
        print(f"     文件: {CONFIG_PATH}")
        print(f"     Provider: {self.provider}")

        # 读取现有配置
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 更新 Provider
        providers = config.setdefault("providers", {})
        provider_entry = providers.setdefault(self.provider, {})
        provider_entry["enabled"] = True

        accounts = provider_entry.setdefault("accounts", [])
        if not accounts:
            accounts.append({"name": "account-1", "models": [], "max_concurrent": 5, "health_check_interval": 60})
        account = accounts[0]

        auth_type = self.cfg["auth_type"]
        if auth_type == "both":
            # 同时保存 cookie 和 token
            cookie = self.extracted.get("cookie")
            user_token = self.extracted.get("token")
            if cookie:
                account["cookie"] = cookie
                print(f"     字段: cookie ({len(cookie)} 字符)")
            if user_token:
                account["token"] = user_token
                print(f"     字段: token ({len(str(user_token))} 字符)")
        else:
            config_key = self.cfg["config_key"]
            if config_key == "cookie":
                account["cookie"] = token
                if "token" in account:
                    del account["token"]
            else:
                account["token"] = token
                if "cookie" in account:
                    del account["cookie"]
            print(f"     字段: {config_key}")

        # post_process 产生的额外字段（如 jwt_user_id → user_id）
        user_id = self.extracted.get("user_id") if isinstance(self.extracted, dict) else None
        if user_id:
            account["user_id"] = user_id
            print(f"     字段: user_id ({user_id})")

        # 自动设置默认模型
        if not account.get("models"):
            default_models = self._get_default_models()
            account["models"] = default_models
            print(f"     自动设置模型: {', '.join(default_models)}")

        # 写回配置文件
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        print(f"  [OK] 配置已保存！")
        print(f"\n  [i]  配置已启用，重启 WebAPI 后生效。")
        print(f"     你可以验证: python -m src.main --port 18080")
        print(f"     然后访问: http://127.0.0.1:18080/admin/ui/admin.html")

    def _get_default_models(self) -> list[str]:
        """获取 Provider 默认模型列表"""
        defaults = {
            "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
            "kimi": ["Kimi-K2.6"],
            "qwen": ["qwen-max", "qwen-plus", "qwen-turbo"],
            "minimax": ["MiniMax-Text-01", "abab6.5s-chat"],
            "doubao": ["doubao-pro-32k", "doubao-lite-32k"],
            "yuanbao": ["hunyuan-pro", "hunyuan-turbo"],
        }
        return defaults.get(self.provider, ["default"])

    async def _cleanup(self):
        """清理浏览器"""
        if self.context:
            # 保存浏览器状态（cookies、localStorage 等）以便下次复用
            try:
                await self.context.storage_state(path=str(self._storage_path))
                print(f"  [i]  浏览器状态已保存到: {self._storage_path}")
            except Exception as e:
                print(f"  [WARN]  保存状态失败: {e}")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print(f"\n  [x] 浏览器已关闭\n")


# =============================================================================
# CLI Entry Point
# =============================================================================

async def _validate_and_save_pat(provider: str, token: str, cfg: dict):
    """验证 PAT 并保存到 config.yaml"""
    import aiohttp

    print(f"\n  正在验证 Token...")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                "https://api.coze.cn/v1/user/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    user_info = data.get("data", data)
                    user_name = user_info.get("name", user_info.get("nick_name", "Unknown"))
                    print(f"  [OK] Token 有效！用户: {user_name}")
                elif resp.status == 401:
                    print(f"  [ERR] Token 无效 (401 Unauthorized)，请检查")
                    sys.exit(1)
                else:
                    text = await resp.text()
                    print(f"  [WARN] 验证返回 HTTP {resp.status}: {text[:200]}")
                    print(f"  将继续保存 Token，但可能无法正常使用")
        except aiohttp.ClientError as e:
            print(f"  [WARN] 网络错误: {e}")
            print(f"  将继续保存 Token，但请检查网络连接")

    # Save to config.yaml
    print(f"\n  正在保存到 config.yaml...")
    try:
        import yaml as yaml_lib
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml_lib.safe_load(f) or {}

        providers = config.setdefault("providers", {})
        coze_cfg = providers.setdefault("coze", {})
        accounts = coze_cfg.setdefault("accounts", [])

        # Update or add first account
        if accounts:
            accounts[0]["token"] = token
            accounts[0]["enabled"] = True
            print(f"  已更新现有账号 token")
        else:
            accounts.append({
                "name": "account-1",
                "token": token,
                "models": ["coze-chat"],
                "max_concurrent": 5,
                "health_check_interval": 60,
                "enabled": True,
            })
            print(f"  已创建新账号 account-1")

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml_lib.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        print(f"\n  {'='*60}")
        print(f"  [OK] Coze Token 配置完成！")
        print(f"  请重启 WebAPI 服务以加载新配置")
        print(f"  {'='*60}")
    except Exception as e:
        print(f"  [ERR] 保存配置失败: {e}")
        sys.exit(1)


def main():
    """CLI 入口：python -m src.login <provider>"""
    if len(sys.argv) < 2:
        print("用法: python -m src.login <provider>")
        print(f"可选 Provider: {', '.join(PROVIDER_CONFIGS.keys())}")
        print()
        print("示例:")
        print("  python -m src.login deepseek")
        print("  python -m src.login minimax")
        print("  python -m src.login doubao")
        print("  python -m src.login yuanbao")
        print("  python -m src.login qwen")
        print("  python -m src.login kimi")
        sys.exit(1)

    provider = sys.argv[1].lower()
    headless = "--headless" in sys.argv

    if provider not in PROVIDER_CONFIGS:
        print(f"[ERR] Unknown provider: {provider}")
        print(f"   Available: {', '.join(PROVIDER_CONFIGS.keys())}")
        sys.exit(1)

    cfg = PROVIDER_CONFIGS[provider]

    # Coze / manual_pat providers: prompt for PAT instead of browser login
    if cfg.get("auth_type") == "manual_pat":
        print(f"\n{'='*60}")
        print(f"  {cfg['name']} — 手动配置 Personal Access Token")
        print(f"{'='*60}")
        for line in cfg.get("pat_instructions", []):
            print(f"  {line}")
        print()
        token = input(f"  请输入你的 Coze PAT: ").strip()
        if not token:
            print("  [ERR] Token 为空，已取消")
            sys.exit(1)

        # Validate PAT via API
        asyncio.run(_validate_and_save_pat(provider, token, cfg))
    else:
        extractor = TokenExtractor(provider, headless=headless)
        asyncio.run(extractor.run())


if __name__ == "__main__":
    main()
