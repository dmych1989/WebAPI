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
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

# =============================================================================
# Provider 配置：每个 Provider 的登录 URL、Token 提取规则
# =============================================================================

PROVIDER_CONFIGS = {
    "deepseek": {
        "name": "DeepSeek",
        "login_url": "https://chat.deepseek.com/",
        "auth_type": "both",
        "extractors": [
            # Cookie 用于过 Cloudflare WAF
            {
                "type": "all_cookies",
                "format": "header_string",
                "save_as": "cookie",
            },
            # 从网络请求中截取 Authorization header（优先）
            {
                "type": "network_auth",
                "save_as": "token",
                "url_pattern": "/api/v0/",
            },
            # 兜底：localStorage userToken（可能为空 JSON）
            {
                "type": "localStorage",
                "key": "userToken",
                "save_as": "token",
            },
        ],
        "cookie_validate_url": "https://chat.deepseek.com/api/v0/user/info",
        "cookie_validate_check": "email",
        "config_key": "cookie",
        "token_config_key": "token",
    },
    "kimi": {
        "name": "Kimi (月之暗面)",
        "login_url": "https://www.kimi.com/",
        "auth_type": "token",
        "extractors": [
            # Kimi 新站 kimi.com 的 token 存储在 localStorage 中
            # 历史上有多种 key 名，依次尝试以兼容
            {
                "type": "localStorage",
                "key": "access_token",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            {
                "type": "localStorage",
                "key": "refresh_token",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            {
                "type": "localStorage",
                "key": "kimi_at",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            {
                "type": "localStorage",
                "key": "kimi_rt",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            {
                "type": "localStorage",
                "key": "auth_token",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            {
                "type": "localStorage",
                "key": "userToken",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            # 从 kimi.com 域的任何 API 请求截取 Authorization header（最可靠）
            {
                "type": "network_auth",
                "url_pattern": "kimi.com/api",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
        ],
        "validate_url": "https://www.kimi.com/api/user",
        "validate_field": "name",
        "config_key": "token",
    },
    "qwen": {
        "name": "通义千问 (Alibaba)",
        "login_url": "https://www.qianwen.com/?source=tongyigw",
        "auth_type": "token",
        "extractors": [
            # 通义千问 Provider 实际使用的是 tongyi_sso_ticket cookie
            # 优先从网络请求中截取（最可靠）
            {
                "type": "network_auth",
                "url_pattern": "qianwen.com",
                "header_key": "Cookie",
                "header_prefix": "tongyi_sso_ticket=",
                "save_as": "token",
            },
            # 兜底：从浏览器 cookie 直接取 tongyi_sso_ticket
            {
                "type": "cookie",
                "keys": ["tongyi_sso_ticket"],
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
                "save_as": "token",
            },
            # 兜底 2：localStorage 备选
            {
                "type": "localStorage",
                "key": "loginParams",
                "parser": "json",
                "json_path": "token",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
                "save_as": "token",
            },
            # 兜底 3：其他可能的 cookie
            {
                "type": "cookie",
                "keys": ["_qwen_token", "qwen-auth-token"],
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
                "save_as": "token",
            },
        ],
        # 验证时尝试 chat2-api 域（Provider 真实使用的 API 域名）
        "validate_url": "https://chat2-api.qianwen.com/api/v1/user/info",
        "validate_field": "nickname",
        "config_key": "token",
    },
    "minimax": {
        "name": "MiniMax (Hailuo AI)",
        "login_url": "https://agent.minimaxi.com/",
        "auth_type": "token",
        "extractors": [
            {
                "type": "localStorage",
                "key": "access_token",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
            {
                "type": "localStorage",
                "key": "token",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
            },
        ],
        "validate_url": "https://hailuoai.com/api/user/info",
        "validate_field": "name",
        "config_key": "token",
    },
    "doubao": {
        "name": "豆包 (Doubao · 字节跳动)",
        "login_url": "https://www.doubao.com/chat/",
        "auth_type": "cookie",
        "extractors": [
            # 豆包: Cookie 全量提取
            {
                "type": "all_cookies",
                "format": "header_string",
            },
        ],
        "cookie_validate_url": "https://www.doubao.com/chat/",
        "cookie_validate_check": "doubao",  # 响应中必须包含这个字串（不重定向到登录）
        "config_key": "cookie",
    },
    "yuanbao": {
        "name": "腾讯元宝 (Yuanbao)",
        "login_url": "https://yuanbao.tencent.com/chat/",
        "auth_type": "cookie",
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
        """启动 Playwright 浏览器"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("\n  [ERR] 需要安装 playwright:")
            print("     pip install playwright")
            print("     playwright install chromium")
            sys.exit(1)

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
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
        """导航到登录页面，登录后触发 API 请求以截取 Token"""
        await self.page.goto(self.cfg["login_url"], wait_until="domcontentloaded")
        await asyncio.sleep(3)
        
        self._start_url = self.page.url
        print("  [...] Waiting for login (auto-detect if already logged in)...")
        print("  [i]  Please operate in the browser window. Do not close it.")

    async def _wait_and_extract(self) -> Optional[str]:
        """等待用户登录后提取 Token"""
        extractors = self.cfg.get("extractors", [])
        max_wait_seconds = 600  # 最多等 10 分钟
        poll_interval = 2

        start = time.time()
        last_url = ""
        login_detected = False
        api_triggered = False
        
        # 检测当前是否已登录
        logged_in_keywords = ["/chat/", "/a/chat/"]
        if any(kw in self.page.url for kw in logged_in_keywords):
            login_detected = True
        
        # 多提取器结果收集
        extracted_values = {}  # save_as -> value

        while time.time() - start < max_wait_seconds:
            # 检查 URL 是否变化（检测登录跳转）
            current_url = self.page.url
            if not login_detected and current_url != last_url:
                last_url = current_url
                if any(kw in current_url for kw in logged_in_keywords):
                    login_detected = True
                    print(f"\n  [OK] Login detected! URL: {current_url[:80]}...")

            # 登录后，触发 API 请求以捕获 Authorization header
            if login_detected and not api_triggered:
                api_triggered = True
                print("  [*] Triggering API requests to capture auth token...")
                await self._trigger_api_requests()
                print(f"  [i]  Captured {len(self._network_requests)} network requests")

            # 尝试提取
            for extractor in extractors:
                save_as = extractor.get("save_as", self.cfg["config_key"])
                existing = extracted_values.get(save_as)
                # 已有好的值则跳过（token > 40 字符且不是 JSON 包装的）
                if existing and len(str(existing)) > 40:
                    continue
                
                value = await self._try_extract(extractor)
                if value:
                    # 过滤明显无效的 token（JSON 空值包装）
                    if extractor["type"] == "localStorage" and save_as == "token":
                        try:
                            obj = json.loads(value)
                            if isinstance(obj, dict) and obj.get("value") is None:
                                continue  # userToken {"value": null} → 跳过, 等 network_auth
                        except (json.JSONDecodeError, TypeError):
                            pass
                    extracted_values[save_as] = value
                    src = extractor.get("type")
                    detail = extractor.get("key", extractor.get("keys", extractor.get("url_pattern", "all")))
                    print(f"\n  [OK] Extracted: {save_as} (source: {src}.{detail})")
                    print(f"       Length: {len(str(value))} chars")

            # 判断是否全部提取完毕
            auth_type = self.cfg["auth_type"]
            if auth_type == "both":
                if extracted_values.get("cookie") and extracted_values.get("token"):
                    self.extracted = extracted_values
                    return extracted_values["cookie"]
            else:
                config_key = self.cfg["config_key"]
                if extracted_values.get(config_key):
                    self.extracted = {
                        "type": self.cfg["auth_type"],
                        "value": extracted_values[config_key],
                        "config_key": config_key,
                    }
                    return extracted_values[config_key]

            await asyncio.sleep(poll_interval)

            # 每 30 秒提示一次
            elapsed = int(time.time() - start)
            if elapsed % 30 == 0 and elapsed > 0:
                missing = []
                if auth_type == "both":
                    if not extracted_values.get("cookie"): missing.append("cookie")
                    if not extracted_values.get("token"): missing.append("token")
                else:
                    if not extracted_values.get(self.cfg["config_key"]):
                        missing.append(self.cfg["config_key"])
                if missing:
                    print(f"  [...] Waiting... ({elapsed}s / {max_wait_seconds}s) missing: {', '.join(missing)}")

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

                return value if value else None

            elif ext_type == "cookie":
                keys = extractor.get("keys", [])
                cookies = await self.context.cookies()
                for cookie in cookies:
                    if cookie["name"] in keys:
                        return cookie["value"]
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
                # 从已捕获的网络请求中提取指定的 header 值
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
                return None

            elif ext_type == "html":
                pattern = extractor.get("pattern", "")
                if pattern:
                    html = await self.page.content()
                    import re as _re
                    match = _re.search(pattern, html)
                    if match:
                        self.extracted[extractor.get("name", "extra")] = match.group(1)
                        return match.group(1)
                return None

        except Exception as e:
            # 提取失败继续尝试下一个
            pass

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

    extractor = TokenExtractor(provider, headless=headless)
    asyncio.run(extractor.run())


if __name__ == "__main__":
    main()
