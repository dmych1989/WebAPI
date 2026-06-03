# -*- coding: utf-8 -*-
"""
增强版Token提取器 - 集成Chat2API的自动提取功能

提供更强大的自动提取能力，包括：
- 网络请求拦截
- 实时Cookie监控
- localStorage监控
- 智能Token验证
- 多种提取策略
- 自动化流程
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiohttp
from playwright.async_api import Browser, BrowserContext, Page, Request, TimeoutError as PlaywrightTimeoutError
from src.core.logger import logger


@dataclass
class TokenSource:
    """Token来源配置"""
    type: str  # "networkHeader" | "localStorage" | "cookie" | "html"
    key: str
    url_pattern: Optional[str] = None
    extract_pattern: Optional[str] = None
    format: Optional[str] = None  # "raw" | "name_value" | "json"


@dataclass
class TokenExtractionConfig:
    """Token提取配置"""
    login_url: str
    token_sources: List[TokenSource]
    target_domains: List[str]
    success_url_patterns: Optional[List[str]] = None
    window_title: Optional[str] = None
    validate_url: Optional[str] = None
    validate_method: Optional[str] = None
    config_key: Optional[str] = None


@dataclass
class ExtractedToken:
    """提取的Token信息"""
    key: str
    value: str
    source: str
    timestamp: float
    metadata: Dict[str, Any] = None


class TokenValidator:
    """Token验证器"""
    
    @staticmethod
    def is_valid_jwt(token: str) -> bool:
        """验证JWT格式"""
        if not token or len(token) < 10:
            return False
        
        parts = token.split('.')
        if len(parts) not in [3, 5]:  # JWT or JWE
            return False
        
        # 检查每个部分是否为有效的base64
        for part in parts:
            try:
                import base64
                padding = 4 - len(part) % 4
                if padding != 4:
                    part += '=' * padding
                base64.urlsafe_b64decode(part)
            except:
                return False
        
        return True
    
    @staticmethod
    def is_valid_token(token: str) -> bool:
        """验证Token有效性"""
        if not token or len(token) < 5:
            return False
        
        # JWT格式
        if TokenValidator.is_valid_jwt(token):
            return True
        
        # 其他常见格式
        patterns = [
            r'^[a-zA-Z0-9\-_]{20,}$',  # 简单token
            r'^sk-[a-zA-Z0-9]{20,}$',   # OpenAI style API key
            r'^ey[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$',  # JWT
        ]
        
        return any(re.match(pattern, token) for pattern in patterns)


class BaseTokenExtractor(ABC):
    """Token提取器基类"""
    
    def __init__(self, config: TokenExtractionConfig):
        self.config = config
        self.extracted_tokens: Dict[str, ExtractedToken] = {}
        self.validators = TokenValidator()
    
    @abstractmethod
    async def extract_tokens(self, page: Page, context: BrowserContext) -> Dict[str, ExtractedToken]:
        """提取Token"""
        pass


class NetworkHeaderExtractor(BaseTokenExtractor):
    """网络请求拦截提取器"""
    
    async def extract_tokens(self, page: Page, context: BrowserContext) -> Dict[str, ExtractedToken]:
        """从网络请求头中提取Token"""
        tokens = {}
        
        # 请求拦截
        async def handle_request(request: Request):
            for source in self.config.token_sources:
                if source.type == "networkHeader" and source.url_pattern:
                    if re.match(source.url_pattern, request.url):
                        headers = request.headers
                        if source.key in headers:
                            token = headers[source.key]
                            
                            # 如果有提取模式，应用正则表达式
                            if source.extract_pattern:
                                match = re.match(source.extract_pattern, token)
                                if match and match.group(1):
                                    token = match.group(1)
                            
                            if self.validators.is_valid_token(token):
                                tokens[source.key] = ExtractedToken(
                                    key=source.key,
                                    value=token,
                                    source="networkHeader",
                                    timestamp=time.time(),
                                    metadata={"url": request.url}
                                )
        
        # 拦截请求
        page.route("**/*", handle_request)
        
        # 等待一段时间让请求完成
        await asyncio.sleep(2)
        
        return tokens


class CookieExtractor(BaseTokenExtractor):
    """Cookie提取器"""
    
    async def extract_tokens(self, page: Page, context: BrowserContext) -> Dict[str, ExtractedToken]:
        """从Cookie中提取Token"""
        tokens = {}
        
        # 等待页面加载
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        
        # 获取所有cookies
        cookies = await context.cookies()
        
        for source in self.config.token_sources:
            if source.type == "cookie":
                for cookie in cookies:
                    if cookie["name"] == source.key:
                        token = cookie["value"]
                        
                        # 格式化处理
                        if source.format == "name_value":
                            token = f"{cookie['name']}={token}"
                        
                        if self.validators.is_valid_token(token):
                            tokens[source.key] = ExtractedToken(
                                key=source.key,
                                value=token,
                                source="cookie",
                                timestamp=time.time(),
                                metadata={"domain": cookie["domain"]}
                            )
        
        return tokens


class LocalStorageExtractor(BaseTokenExtractor):
    """LocalStorage提取器"""
    
    async def extract_tokens(self, page: Page, context: BrowserContext) -> Dict[str, ExtractedToken]:
        """从LocalStorage中提取Token"""
        tokens = {}
        
        for source in self.config.token_sources:
            if source.type == "localStorage":
                try:
                    value = await page.evaluate(f"localStorage.getItem('{source.key}')")
                    if value:
                        # 尝试解析JSON
                        try:
                            parsed = json.loads(value)
                            if isinstance(parsed, dict):
                                # 寻找实际的token值
                                for key in ["value", "token", "access_token", "refresh_token"]:
                                    if key in parsed and parsed[key]:
                                        value = str(parsed[key])
                                        break
                                else:
                                    value = str(value)
                            elif isinstance(parsed, str):
                                value = parsed
                        except json.JSONDecodeError:
                            pass
                        
                        # 特殊处理：user_detail_agent → realUserID
                        if source.key == "user_detail_agent" and value:
                            try:
                                ud = json.loads(value)
                                if isinstance(ud, dict) and ud.get("realUserID"):
                                    tokens["user_id"] = ExtractedToken(
                                        key="user_id",
                                        value=str(ud["realUserID"]),
                                        source="localStorage",
                                        timestamp=time.time(),
                                        metadata={"original_key": source.key}
                                    )
                            except Exception:
                                pass
                        
                        if self.validators.is_valid_token(value):
                            tokens[source.key] = ExtractedToken(
                                key=source.key,
                                value=value,
                                source="localStorage",
                                timestamp=time.time(),
                                metadata={"key": source.key}
                            )
                except Exception as e:
                    logger.error(f"[LocalStorageExtractor] Error extracting {source.key}: {e}")
        
        return tokens


class HtmlExtractor(BaseTokenExtractor):
    """HTML内容提取器"""
    
    async def extract_tokens(self, page: Page, context: BrowserContext) -> Dict[str, ExtractedToken]:
        """从HTML内容中提取Token"""
        tokens = {}
        
        try:
            # 获取页面内容
            content = await page.content()
            
            for source in self.config.token_sources:
                if source.type == "html" and source.extract_pattern:
                    matches = re.findall(source.extract_pattern, content)
                    if matches:
                        # 取第一个匹配
                        value = matches[0]
                        
                        # 如果有name参数，使用指定的名称
                        if hasattr(source, 'name'):
                            key = source.name
                        else:
                            key = source.key
                        
                        if self.validators.is_valid_token(value):
                            tokens[key] = ExtractedToken(
                                key=key,
                                value=value,
                                source="html",
                                timestamp=time.time(),
                                metadata={"pattern": source.extract_pattern}
                            )
        except Exception as e:
            logger.error(f"[HtmlExtractor] Error: {e}")
        
        return tokens


class AllCookiesExtractor(BaseTokenExtractor):
    """所有Cookie提取器"""
    
    async def extract_tokens(self, page: Page, context: BrowserContext) -> Dict[str, ExtractedToken]:
        """提取所有Cookie"""
        tokens = {}
        
        try:
            cookies = await context.cookies()
            
            for source in self.config.token_sources:
                if source.type == "all_cookies":
                    cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies if c['value']])
                    
                    if source.format == "header_string":
                        tokens["cookie"] = ExtractedToken(
                            key="cookie",
                            value=cookie_string,
                            source="all_cookies",
                            timestamp=time.time(),
                            metadata={"count": len(cookies)}
                        )
                    else:
                        # 返回单个cookie
                        for cookie in cookies:
                            if cookie["value"]:
                                tokens[cookie["name"]] = ExtractedToken(
                                    key=cookie["name"],
                                    value=cookie["value"],
                                    source="all_cookies",
                                    timestamp=time.time(),
                                    metadata={"domain": cookie["domain"]}
                                )
        except Exception as e:
            logger.error(f"[AllCookiesExtractor] Error: {e}")
        
        return tokens


class EnhancedTokenExtractor:
    """增强版Token提取器"""
    
    def __init__(self, provider: str, headless: bool = False):
        self.provider = provider
        self.headless = headless
        self.config = self._get_extraction_config()
        self.extractors = self._create_extractors()
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.found_tokens: Dict[str, ExtractedToken] = {}
        self.is_completed: bool = False
        self.login_start_time: float = 0
        self.last_token_check_time: float = 0
    
    def _get_extraction_config(self) -> TokenExtractionConfig:
        """获取提取配置"""
        configs = {
            "kimi": TokenExtractionConfig(
                login_url="https://www.kimi.com",
                token_sources=[
                    TokenSource("networkHeader", "token", "*://*.kimi.com/*", "^Bearer\\s+(.+)$"),
                    TokenSource("cookie", "kimi-auth"),
                    TokenSource("localStorage", "access_token"),
                    TokenSource("localStorage", "refresh_token"),
                ],
                target_domains=[".kimi.com", "kimi.com"],
                success_url_patterns=["kimi.com"],
                window_title="Kimi Login",
                validate_url="https://kimi.com/api",
                validate_method="bearer",
                config_key="token"
            ),
            "deepseek": TokenExtractionConfig(
                login_url="https://chat.deepseek.com",
                token_sources=[
                    TokenSource("localStorage", "userToken"),
                    TokenSource("networkHeader", "Authorization", "*://*.deepseek.com/*", "^Bearer\\s+(.+)$"),
                ],
                target_domains=[".deepseek.com", "deepseek.com"],
                success_url_patterns=["chat.deepseek.com"],
                window_title="DeepSeek Login",
                validate_url="https://chat.deepseek.com/api/v0/users/current",
                validate_method="bearer",
                config_key="token"
            ),
            "glm": TokenExtractionConfig(
                login_url="https://chatglm.cn",
                token_sources=[
                    TokenSource("cookie", "chatglm_refresh_token"),
                    TokenSource("localStorage", "chatglm_refresh_token"),
                ],
                target_domains=[".chatglm.cn", "chatglm.cn"],
                success_url_patterns=["chatglm.cn"],
                window_title="GLM Login",
                validate_url="https://open.bigmodel.cn/api/paas/v4/models",
                validate_method="bearer",
                config_key="token"
            ),
            "qwen": TokenExtractionConfig(
                login_url="https://www.qianwen.com",
                token_sources=[
                    TokenSource("cookie", "tongyi_sso_ticket"),
                    TokenSource("localStorage", "tongyi_sso_ticket"),
                ],
                target_domains=[".qianwen.com", "qianwen.com"],
                success_url_patterns=["qianwen.com"],
                window_title="Qwen Login",
                validate_url="https://qianwen.com/api",
                validate_method="bearer",
                config_key="token"
            ),
            "minimax": TokenExtractionConfig(
                login_url="https://agent.minimaxi.com",
                token_sources=[
                    TokenSource("localStorage", "_token"),
                    TokenSource("localStorage", "user_detail_agent"),
                ],
                target_domains=[".minimaxi.com", "minimaxi.com"],
                success_url_patterns=["agent.minimaxi.com"],
                window_title="MiniMax Login",
                validate_url="https://agent.minimaxi.com/api",
                validate_method="bearer",
                config_key="token"
            ),
            "yuanbao": TokenExtractionConfig(
                login_url="https://yuanbao.tencent.com/chat/",
                token_sources=[
                    TokenSource("cookie", "x_token"),
                    TokenSource("all_cookies", "all_cookies", format="header_string"),
                ],
                target_domains=[".tencent.com", "yuanbao.tencent.com"],
                success_url_patterns=["yuanbao.tencent.com"],
                window_title="Yuanbao Login",
                validate_url="https://yuanbao.tencent.com/chat/",
                validate_method="cookie",
                config_key="cookie"
            ),
            "doubao": TokenExtractionConfig(
                login_url="https://www.doubao.com/",
                token_sources=[
                    TokenSource("cookie", "__client_id"),
                    TokenSource("cookie", "doubao_session"),
                    TokenSource("all_cookies", "all_cookies", format="header_string"),
                ],
                target_domains=[".doubao.com", "doubao.com"],
                success_url_patterns=["doubao.com"],
                window_title="Doubao Login",
                validate_url="https://www.doubao.com/api",
                validate_method="cookie",
                config_key="cookie"
            ),
            "mimo": TokenExtractionConfig(
                login_url="https://aistudio.xiaomimimo.com/",
                token_sources=[
                    TokenSource("cookie", "serviceToken"),
                    TokenSource("cookie", "userId"),
                    TokenSource("cookie", "xiaomichatbot_ph"),
                    TokenSource("localStorage", "serviceToken"),
                    TokenSource("localStorage", "userId"),
                    TokenSource("localStorage", "xiaomichatbot_ph"),
                ],
                target_domains=[".xiaomimimo.com", "xiaomimimo.com", ".mi.com"],
                success_url_patterns=["aistudio.xiaomimimo.com"],
                window_title="MiMo Login",
                validate_url="https://aistudio.xiaomimimo.com/api",
                validate_method="cookie",
                config_key="cookie"
            ),
        }
        
        return configs.get(self.provider, configs["kimi"])
    
    def _create_extractors(self) -> List[BaseTokenExtractor]:
        """创建提取器"""
        extractors = []
        
        if any(s.type == "networkHeader" for s in self.config.token_sources):
            extractors.append(NetworkHeaderExtractor(self.config))
        if any(s.type == "cookie" for s in self.config.token_sources):
            extractors.append(CookieExtractor(self.config))
        if any(s.type == "localStorage" for s in self.config.token_sources):
            extractors.append(LocalStorageExtractor(self.config))
        if any(s.type == "html" for s in self.config.token_sources):
            extractors.append(HtmlExtractor(self.config))
        if any(s.type == "all_cookies" for s in self.config.token_sources):
            extractors.append(AllCookiesExtractor(self.config))
        
        return extractors
    
    async def run(self) -> Dict[str, str]:
        """运行提取器"""
        self.login_start_time = time.time()
        self.last_token_check_time = 0
        self.found_tokens = {}
        self.is_completed = False
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                # 启动浏览器
                self.browser = await p.chromium.launch(headless=self.headless)
                
                # 创建上下文
                self.context = await self.browser.new_context(
                    viewport={"width": 800, "height": 600},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                
                # 创建页面
                self.page = await self.context.new_page()
                
                # 设置请求拦截
                await self._setup_request_interception()
                
                # 设置Cookie监控
                await self._setup_cookie_monitoring()
                
                # 设置页面加载监控
                await self._setup_page_monitoring()
                
                # 导航到登录页面
                print(f"  [*] 打开登录页面: {self.config.login_url}")
                await self.page.goto(self.config.login_url, wait_until="networkidle")
                
                # 等待用户登录
                print("  [*] 请在浏览器窗口中完成登录...")
                await asyncio.sleep(3)
                
                # 开始监控
                await self._monitor_extraction()
                
                # 最终提取
                await self._final_extraction()
                
                # 验证提取的Token
                validated_tokens = await self._validate_tokens()
                
                return self._format_credentials(validated_tokens)
                
        except Exception as e:
            print(f"  [ERR] 提取失败: {e}")
            logger.error(f"[EnhancedTokenExtractor] Error: {e}")
            return {}
        finally:
            await self._cleanup()
    
    async def _setup_request_interception(self):
        """设置请求拦截"""
        async def handle_request(request: Request):
            for source in self.config.token_sources:
                if source.type == "networkHeader" and source.url_pattern:
                    if re.match(source.url_pattern, request.url):
                        headers = request.headers
                        if source.key in headers:
                            token = headers[source.key]
                            
                            # 应用提取模式
                            if source.extract_pattern:
                                match = re.match(source.extract_pattern, token)
                                if match and match.group(1):
                                    token = match.group(1)
                            
                            if TokenValidator.is_valid_token(token):
                                self.found_tokens[source.key] = ExtractedToken(
                                    key=source.key,
                                    value=token,
                                    source="networkHeader",
                                    timestamp=time.time(),
                                    metadata={"url": request.url}
                                )
                                print(f"  [+] 发现Token ({source.key}): {token[:20]}...")
        
        await self.page.route("**/*", handle_request)
    
    async def _setup_cookie_monitoring(self):
        """设置Cookie监控"""
        def on_cookie_changed(_event, cookie, _cause, removed):
            if self.is_completed or removed:
                return
            
            if not self._has_min_time_passed():
                return
            
            for source in self.config.token_sources:
                if source.type == "cookie" and cookie.name == source.key:
                    if TokenValidator.is_valid_token(cookie.value):
                        self.found_tokens[source.key] = ExtractedToken(
                            key=source.key,
                            value=cookie.value,
                            source="cookie",
                            timestamp=time.time(),
                            metadata={"domain": cookie.domain}
                        )
                        print(f"  [+] 发现Cookie Token ({source.key}): {cookie.value[:20]}...")
        
        self.context.cookies.on('changed', on_cookie_changed)
    
    async def _setup_page_monitoring(self):
        """设置页面监控"""
        self.page.on('load', lambda: self._delayed_token_check())
        
        self.page.on('navigation', lambda: self._delayed_token_check())
    
    def _has_min_time_passed(self) -> bool:
        """检查是否已过最小时间"""
        return time.time() - self.login_start_time >= 5000  # 5秒
    
    async def _delayed_token_check(self):
        """延迟Token检查"""
        now = time.time()
        if now - self.last_token_check_time < 2000:
            return
        
        self.last_token_check_time = now
        await asyncio.sleep(1)
        
        if self.is_completed:
            return
        
        await self._check_for_tokens()
    
    async def _check_for_tokens(self):
        """检查Token"""
        for extractor in self.extractors:
            try:
                tokens = await extractor.extract_tokens(self.page, self.context)
                for key, token in tokens.items():
                    if key not in self.found_tokens:
                        self.found_tokens[key] = token
                        print(f"  [+] 发现Token ({key}): {token.value[:20]}...")
            except Exception as e:
                logger.error(f"[EnhancedTokenExtractor] Error checking tokens: {e}")
    
    async def _monitor_extraction(self):
        """监控提取过程"""
        max_wait_time = 300  # 5分钟
        
        while time.time() - self.login_start_time < max_wait_time and not self.is_completed:
            # 检查是否成功登录
            if await self._check_login_success():
                print("  [+] 检测到登录成功，开始提取Token...")
                break
            
            # 检查是否找到了足够的Token
            if len(self.found_tokens) >= 2:  # 通常需要至少2个token
                print(f"  [+] 已找到 {len(self.found_tokens)} 个Token，完成提取")
                break
            
            await asyncio.sleep(2)
    
    async def _final_extraction(self):
        """最终提取"""
        print("  [*] 进行最终Token提取...")
        await self._check_for_tokens()
    
    async def _check_login_success(self) -> bool:
        """检查是否成功登录"""
        if not self.config.success_url_patterns:
            return False
        
        current_url = self.page.url
        for pattern in self.config.success_url_patterns:
            if pattern in current_url:
                return True
        
        return False
    
    async def _validate_tokens(self) -> Dict[str, ExtractedToken]:
        """验证Token"""
        validated_tokens = {}
        
        for key, token in self.found_tokens.items():
            try:
                if self.config.validate_url and self.config.validate_method:
                    # 验证Token
                    is_valid = await self._validate_token(token.value)
                    if is_valid:
                        validated_tokens[key] = token
                        print(f"  [✓] Token ({key}) 验证成功")
                    else:
                        print(f"  [✗] Token ({key}) 验证失败")
                else:
                    # 没有验证端点，信任长度
                    if len(token.value) >= 20:
                        validated_tokens[key] = token
                        print(f"  [✓] Token ({key}) 长度验证通过")
                    else:
                        print(f"  [✗] Token ({key}) 长度不足")
            except Exception as e:
                print(f"  [✗] Token ({key}) 验证错误: {e}")
        
        return validated_tokens
    
    async def _validate_token(self, token_value: str) -> bool:
        """验证单个Token"""
        try:
            if self.config.validate_method == "bearer":
                headers = {"Authorization": f"Bearer {token_value}"}
            elif self.config.validate_method == "cookie":
                headers = {"Cookie": f"session={token_value}"}
            else:
                return False
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.config.validate_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"[EnhancedTokenExtractor] Token validation error: {e}")
            return False
    
    def _format_credentials(self, tokens: Dict[str, ExtractedToken]) -> Dict[str, str]:
        """格式化凭证"""
        credentials = {}
        
        for key, token in tokens.items():
            # 标准化字段名
            if key == "token" or key == "access_token":
                credentials["token"] = token.value
            elif key == "refresh_token":
                credentials["refresh_token"] = token.value
            elif key == "cookie":
                credentials["cookie"] = token.value
            elif key == "user_id":
                credentials["user_id"] = token.value
            elif key == "serviceToken":
                credentials["service_token"] = token.value
            elif key == "userId":
                credentials["user_id"] = token.value
            elif key == "xiaomichatbot_ph":
                credentials["xiaomichatbot_ph"] = token.value
            else:
                credentials[key] = token.value
        
        return credentials
    
    async def _cleanup(self):
        """清理资源"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()


# 向后兼容的TokenExtractor类
class TokenExtractor(EnhancedTokenExtractor):
    """向后兼容的TokenExtractor类"""
    
    def __init__(self, provider: str, headless: bool = False):
        super().__init__(provider, headless)
    
    async def run(self) -> Dict[str, str]:
        """运行提取器（保持向后兼容）"""
        return await super().run()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python enhanced_token_extractor.py <provider>")
        print("支持的provider: kimi, deepseek, glm, qwen, minimax, yuanbao, doubao, mimo")
        sys.exit(1)
    
    provider = sys.argv[1]
    headless = "--headless" in sys.argv
    
    extractor = EnhancedTokenExtractor(provider, headless)
    credentials = asyncio.run(extractor.run())
    
    if credentials:
        print(f"\n成功提取到凭证:")
        for key, value in credentials.items():
            print(f"  {key}: {value[:20]}..." if len(value) > 20 else f"  {key}: {value}")
    else:
        print("\n未能提取到有效凭证")