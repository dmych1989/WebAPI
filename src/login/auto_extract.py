# -*- coding: utf-8 -*-
"""
自动凭证提取器 - 参考Chat2API的自动提取架构

提供更强大的自动凭证提取功能，包括：
- 网络请求拦截
- 实时Cookie监控
- localStorage监控
- 智能Token验证
- 多种提取策略
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

from playwright.async_api import Browser, BrowserContext, Page, Request
from src.core.logger import logger


@dataclass
class TokenSource:
    """Token来源配置"""
    type: str  # "networkHeader" | "localStorage" | "cookie"
    key: str
    url_pattern: Optional[str] = None
    extract_pattern: Optional[str] = None


@dataclass
class TokenExtractionConfig:
    """Token提取配置"""
    login_url: str
    token_sources: List[TokenSource]
    target_domains: List[str]
    success_url_patterns: Optional[List[str]] = None
    window_title: Optional[str] = None


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
        await page.wait_for_load_state("networkidle")
        
        # 获取所有cookies
        cookies = await context.cookies()
        
        for source in self.config.token_sources:
            if source.type == "cookie":
                for cookie in cookies:
                    if cookie["name"] == source.key:
                        token = cookie["value"]
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


class AutoExtractor:
    """自动凭证提取器"""
    
    def __init__(self, provider: str):
        self.provider = provider
        self.config = self._get_extraction_config()
        self.extractors = self._create_extractors()
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
    
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
                window_title="Kimi Login"
            ),
            "deepseek": TokenExtractionConfig(
                login_url="https://chat.deepseek.com",
                token_sources=[
                    TokenSource("localStorage", "userToken"),
                    TokenSource("networkHeader", "Authorization", "*://*.deepseek.com/*", "^Bearer\\s+(.+)$"),
                ],
                target_domains=[".deepseek.com", "deepseek.com"],
                success_url_patterns=["chat.deepseek.com"],
                window_title="DeepSeek Login"
            ),
            "glm": TokenExtractionConfig(
                login_url="https://chatglm.cn",
                token_sources=[
                    TokenSource("cookie", "chatglm_refresh_token"),
                    TokenSource("localStorage", "chatglm_refresh_token"),
                ],
                target_domains=[".chatglm.cn", "chatglm.cn"],
                success_url_patterns=["chatglm.cn"],
                window_title="GLM Login"
            ),
            "qwen": TokenExtractionConfig(
                login_url="https://www.qianwen.com",
                token_sources=[
                    TokenSource("cookie", "tongyi_sso_ticket"),
                    TokenSource("localStorage", "tongyi_sso_ticket"),
                ],
                target_domains=[".qianwen.com", "qianwen.com"],
                success_url_patterns=["qianwen.com"],
                window_title="Qwen Login"
            ),
            "minimax": TokenExtractionConfig(
                login_url="https://agent.minimaxi.com",
                token_sources=[
                    TokenSource("localStorage", "_token"),
                    TokenSource("localStorage", "user_detail_agent"),
                ],
                target_domains=[".minimaxi.com", "minimaxi.com"],
                success_url_patterns=["agent.minimaxi.com"],
                window_title="MiniMax Login"
            ),
            "yuanbao": TokenExtractionConfig(
                login_url="https://yuanbao.tencent.com/chat/",
                token_sources=[
                    TokenSource("cookie", "x_token"),
                    TokenSource("all_cookies", "all_cookies"),
                ],
                target_domains=[".tencent.com", "yuanbao.tencent.com"],
                success_url_patterns=["yuanbao.tencent.com"],
                window_title="Yuanbao Login"
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
        
        return extractors
    
    async def start(self) -> Dict[str, ExtractedToken]:
        """开始提取"""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                # 启动浏览器
                self.browser = await p.chromium.launch(headless=False)
                
                # 创建上下文
                self.context = await self.browser.new_context(
                    viewport={"width": 800, "height": 600},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                
                # 创建页面
                self.page = await self.context.new_page()
                
                # 导航到登录页面
                logger.info(f"[AutoExtractor] Navigating to {self.config.login_url}")
                await self.page.goto(self.config.login_url, wait_until="networkidle")
                
                # 等待用户登录
                logger.info("[AutoExtractor] Please login in the browser window...")
                await asyncio.sleep(5)
                
                # 开始监控
                all_tokens = await self._monitor_and_extract()
                
                return all_tokens
                
        except Exception as e:
            logger.error(f"[AutoExtractor] Error: {e}")
            return {}
        finally:
            await self._cleanup()
    
    async def _monitor_and_extract(self) -> Dict[str, ExtractedToken]:
        """监控并提取Token"""
        all_tokens = {}
        
        # 监控时间限制
        max_wait_time = 300  # 5分钟
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            # 检查是否成功登录
            if await self._check_login_success():
                logger.info("[AutoExtractor] Login detected, extracting tokens...")
                break
            
            # 定期提取Token
            for extractor in self.extractors:
                try:
                    tokens = await extractor.extract_tokens(self.page, self.context)
                    all_tokens.update(tokens)
                    
                    # 如果找到了足够的Token，停止监控
                    if len(all_tokens) >= 2:  # 通常需要至少2个token
                        logger.info(f"[AutoExtractor] Found {len(all_tokens)} tokens, stopping monitoring")
                        return all_tokens
                        
                except Exception as e:
                    logger.error(f"[AutoExtractor] Error extracting tokens: {e}")
            
            # 等待下一次检查
            await asyncio.sleep(2)
        
        # 最终提取
        for extractor in self.extractors:
            try:
                tokens = await extractor.extract_tokens(self.page, self.context)
                all_tokens.update(tokens)
            except Exception as e:
                logger.error(f"[AutoExtractor] Final extraction error: {e}")
        
        logger.info(f"[AutoExtractor] Extracted {len(all_tokens)} tokens")
        return all_tokens
    
    async def _check_login_success(self) -> bool:
        """检查是否成功登录"""
        if not self.config.success_url_patterns:
            return False
        
        current_url = self.page.url
        for pattern in self.config.success_url_patterns:
            if pattern in current_url:
                return True
        
        return False
    
    async def _cleanup(self):
        """清理资源"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()


async def auto_extract_credentials(provider: str) -> Dict[str, str]:
    """自动提取凭证"""
    extractor = AutoExtractor(provider)
    tokens = await extractor.start()
    
    # 转换为凭证格式
    credentials = {}
    for token in tokens.values():
        if token.key == "token":
            credentials["token"] = token.value
        elif token.key == "cookie":
            credentials["cookie"] = token.value
        elif token.key == "access_token":
            credentials["token"] = token.value
        elif token.key == "refresh_token":
            credentials["refresh_token"] = token.value
        elif token.key == "user_id":
            credentials["user_id"] = token.value
        else:
            credentials[token.key] = token.value
    
    return credentials


# 测试函数
async def test_auto_extract(provider: str):
    """测试自动提取"""
    print(f"开始自动提取 {provider} 的凭证...")
    
    try:
        credentials = await auto_extract_credentials(provider)
        
        if credentials:
            print(f"成功提取到凭证:")
            for key, value in credentials.items():
                print(f"  {key}: {value[:20]}..." if len(value) > 20 else f"  {key}: {value}")
        else:
            print("未能提取到有效凭证")
            
    except Exception as e:
        print(f"提取失败: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python auto_extract.py <provider>")
        print("支持的provider: kimi, deepseek, glm, qwen, minimax, yuanbao")
        sys.exit(1)
    
    provider = sys.argv[1]
    asyncio.run(test_auto_extract(provider))