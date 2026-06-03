# -*- coding: utf-8 -*-
"""
WebAPI 改进版 Token 提取器 - 参考 Chat2API OAuth 架构
支持网络请求拦截、实时 token 捕获、配置化提取规则
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from urllib.parse import urlparse

import yaml
import playwright.async_api as playwright
from playwright.async_api import Request, Response

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

@dataclass
class TokenSource:
    """Token 提取源配置"""
    type: str  # 'networkHeader' | 'localStorage' | 'cookie'
    key: str
    url_pattern: Optional[str] = None
    extract_pattern: Optional[str] = None

@dataclass
class TokenExtractionConfig:
    """Provider 提取配置"""
    login_url: str
    token_sources: List[TokenSource]
    target_domains: List[str]
    success_url_patterns: Optional[List[str]] = None

TOKEN_EXTRACTION_CONFIGS = {
    "deepseek": TokenExtractionConfig(
        login_url="https://chat.deepseek.com/",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.deepseek.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="localStorage",
                key="userToken"
            )
        ],
        target_domains=[".deepseek.com", "deepseek.com"],
        success_url_patterns=["/cited-chat", "/chat/", "deepseek.com/c"]
    ),
    "kimi": TokenExtractionConfig(
        login_url="https://www.kimi.com/",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.kimi.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="localStorage",
                key="access_token"
            ),
            TokenSource(
                type="localStorage",
                key="refresh_token"
            )
        ],
        target_domains=[".kimi.com", "kimi.com"],
        success_url_patterns=["kimi.com", ".kimi."]
    ),
    "qwen": TokenExtractionConfig(
        login_url="https://www.qianwen.com/",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.qianwen.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="cookie",
                key="tongyi_sso_ticket"
            )
        ],
        target_domains=[".qianwen.com", "qianwen.com"],
        success_url_patterns=["qianwen.com", "qwen.", "converse"]
    ),
    "minimax": TokenExtractionConfig(
        login_url="https://agent.minimaxi.com/",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.minimaxi.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="localStorage",
                key="_token"
            ),
            TokenSource(
                type="localStorage",
                key="user_detail_agent"
            )
        ],
        target_domains=[".minimaxi.com", "minimaxi.com"],
        success_url_patterns=["minimaxi.com", "minimax.", "agent"]
    ),
    "doubao": TokenExtractionConfig(
        login_url="https://www.doubao.com/chat/",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.doubao.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="cookie",
                key="doubao_token"
            )
        ],
        target_domains=[".doubao.com", "doubao.com"],
        success_url_patterns=["doubao.com/chat", "doubao.com/conversation"]
    ),
    "glm": TokenExtractionConfig(
        login_url="https://bigmodel.cn/login",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.bigmodel.cn/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="cookie",
                key="chatglm_refresh_token"
            )
        ],
        target_domains=[".bigmodel.cn", "bigmodel.cn"],
        success_url_patterns=["bigmodel.cn", "chatglm.", "model/chat"]
    ),
    "yuanbao": TokenExtractionConfig(
        login_url="https://yuanbao.tencent.com/chat/",
        token_sources=[
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.yuanbao.tencent.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            TokenSource(
                type="cookie",
                key="yuanbao_token"
            )
        ],
        target_domains=[".yuanbao.tencent.com", "yuanbao.tencent.com"],
        success_url_patterns=["yuanbao.tencent.com/chat", "yuanbao.tencent.com/conversation", "tencent.com/robot"]
    )
}

class TokenMonitor:
    """实时 Token 监控器"""
    def __init__(self):
        self.token_queue = asyncio.Queue()
        self.active_requests = {}
        self.extracted_tokens = set()
    
    async def capture_request(self, request: Request):
        """捕获网络请求中的 token"""
        try:
            # 检查 URL 是否匹配目标域名
            url = request.url
            if not self._should_capture_url(url):
                return
            
            # 检查请求头
            headers = request.headers
            auth_header = headers.get("Authorization", "")
            
            if auth_header:
                token = self._extract_token_from_header(auth_header)
                if token and token not in self.extracted_tokens:
                    self.extracted_tokens.add(token)
                    await self.token_queue.put({
                        "type": "networkHeader",
                        "token": token,
                        "url": url,
                        "timestamp": time.time()
                    })
                    print(f"[CAPTURE] Network header token from {url}")
            
        except Exception as e:
            print(f"[ERROR] Failed to capture request: {e}")
    
    async def capture_response(self, response: Response):
        """捕获响应中的 token"""
        try:
            # 可以从响应内容或响应头中提取 token
            pass
        except Exception as e:
            print(f"[ERROR] Failed to capture response: {e}")
    
    def _should_capture_url(self, url: str) -> bool:
        """检查是否应该捕获该 URL 的请求"""
        parsed = urlparse(url)
        hostname = parsed.hostname
        
        if not hostname:
            return False
        
        # 检查是否匹配目标域名
        for config in TOKEN_EXTRACTION_CONFIGS.values():
            for domain in config.target_domains:
                if domain.startswith('.'):
                    if hostname.endswith(domain[1:]):
                        return True
                else:
                    if hostname == domain:
                        return True
        
        return False
    
    def _extract_token_from_header(self, header: str) -> Optional[str]:
        """从 Authorization 头中提取 token"""
        if header.startswith('Bearer '):
            return header[7:].strip()
        return None

class ImprovedTokenExtractor:
    """改进版 Token 提取器"""
    def __init__(self, provider: str):
        self.provider = provider
        self.config = TOKEN_EXTRACTION_CONFIGS.get(provider)
        if not self.config:
            raise ValueError(f"Unsupported provider: {provider}")
        
        self.monitor = TokenMonitor()
        self.extracted_values = {}
        self.page = None
        self.context = None
        self.browser = None
        
        # 导航相关
        self._login_start_time = time.time()
        self._last_token_check = 0.0
    
    async def login(self) -> Optional[Dict[str, Any]]:
        """启动登录流程"""
        print(f"\n  [*] 启动 {self.provider} 自动登录...")
        print(f"     登录页面: {self.config.login_url}")
        
        # 初始化浏览器
        self.browser = await playwright.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        
        # 创建上下文
        storage_path = PROJECT_ROOT / "storage" / f"{self.provider}_state.json"
        storage_state = {}
        if storage_path.exists():
            with open(storage_path, "r", encoding="utf-8") as f:
                storage_state = json.load(f)
        
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            storage_state=storage_state,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        
        # 设置页面
        self.page = await self.context.new_page()
        
        # 监听网络请求
        self.page.on("request", self.monitor.capture_request)
        self.page.on("response", self.monitor.capture_response)
        
        # 导航到登录页面
        await self._navigate_login()
        
        # 等待 token 提取
        result = await self._wait_and_extract()
        
        # 清理
        await self.browser.close()
        return result
    
    async def _navigate_login(self):
        """导航到登录页面"""
        print("  [...] 打开登录页面...")
        await self.page.goto(self.config.login_url, wait_until="domcontentloaded")
        
        # 检查是否已经登录
        current_url = self.page.url
        if current_url != self.config.login_url:
            print("  [i]  检测到可能已登录状态")
        
        # 监听导航事件
        self.page.on("framenavigated", self._on_navigated)
        
        print("  [i]  请在浏览器中完成登录...")
        print(f"     登录页面: {self.config.login_url}")
    
    def _on_navigated(self, frame):
        """页面导航回调"""
        if frame != self.page.main_frame:
            return
        
        # 重置 token 检查计时器
        self._last_token_check = 0.0
        print(f"  [NAV] 页面导航到: {frame.url}")
    
    async def _wait_and_extract(self) -> Optional[Dict[str, Any]]:
        """等待并提取 token"""
        start = time.time()
        max_wait_seconds = 600  # 10分钟
        poll_interval = 1.5
        login_detected = False
        
        while True:
            # 检查超时
            if time.time() - start > max_wait_seconds:
                print(f"\n  [WARN]  超时 ({max_wait_seconds}s)")
                return None
            
            # 检查是否登录成功
            current_url = self.page.url
            if self._is_success_url(current_url):
                if not login_detected:
                    print("  [OK]  检测到登录成功")
                    login_detected = True
            
            # 检查 token 队列
            try:
                while True:
                    token_data = self.monitor.token_queue.get_nowait()
                    await self._process_token_data(token_data)
            except asyncio.QueueEmpty:
                pass
            
            # 定期检查 localStorage
            if time.time() - self._last_token_check >= poll_interval:
                await self._check_local_storage()
                self._last_token_check = time.time()
            
            # 检查是否获得足够信息
            if self._has_valid_credentials():
                print(f"\n  [OK]  获取到凭证")
                return self.extracted_values
            
            await asyncio.sleep(poll_interval)
    
    async def _process_token_data(self, token_data: Dict[str, Any]):
        """处理捕获的 token 数据"""
        token_type = token_data["type"]
        token = token_data["token"]
        
        if token_type == "networkHeader":
            # 从网络请求头中获取的 token
            self.extracted_values["token"] = token
            print(f"  [OK]  网络请求头 token ({len(token)} 字符)")
    
    async def _check_local_storage(self):
        """检查 localStorage"""
        try:
            storage = await self.page.evaluate("() => ({...localStorage})")
            
            for source in self.config.token_sources:
                if source.type == "localStorage":
                    key = source.key
                    value = storage.get(key)
                    
                    if value and len(value) > 20:
                        self.extracted_values[key] = value
                        print(f"  [OK]  localStorage.{key} ({len(value)} 字符)")
                        
                        # 处理 user_detail_agent
                        if key == "user_detail_agent":
                            await self._process_user_detail_agent(value)
        
        except Exception as e:
            print(f"  [ERROR] 检查 localStorage 失败: {e}")
    
    async def _process_user_detail_agent(self, value: str):
        """处理 user_detail_agent"""
        try:
            user_detail = json.loads(value)
            if user_detail.get("realUserID"):
                self.extracted_values["user_id"] = str(user_detail["realUserID"])
                print(f"       user_id (realUserID): {user_detail['realUserID']}")
        except Exception:
            pass
    
    def _is_success_url(self, url: str) -> bool:
        """检查是否为成功登录的 URL"""
        if url == self.config.login_url:
            return False
        
        if self.config.success_url_patterns:
            for pattern in self.config.success_url_patterns:
                if pattern in url:
                    return True
        
        return False
    
    def _has_valid_credentials(self) -> bool:
        """检查是否获取到有效凭证"""
        # 检查是否有 token 或其他凭证
        return bool(self.extracted_values.get("token") or 
                   self.extracted_values.get("user_id"))

async def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("用法: python improved_login.py <provider>")
        print("支持的 provider:", list(TOKEN_EXTRACTION_CONFIGS.keys()))
        sys.exit(1)
    
    provider = sys.argv[1]
    if provider not in TOKEN_EXTRACTION_CONFIGS:
        print(f"不支持的 provider: {provider}")
        print("支持的 provider:", list(TOKEN_EXTRACTION_CONFIGS.keys()))
        sys.exit(1)
    
    extractor = ImprovedTokenExtractor(provider)
    result = await extractor.login()
    
    if result:
        print("\n  [SUCCESS] 登录成功！")
        print("  提取的凭证:", {k: f"{v[:20]}..." if len(str(v)) > 20 else v 
                          for k, v in result.items()})
    else:
        print("\n  [FAILED] 登录失败")

if __name__ == "__main__":
    asyncio.run(main())