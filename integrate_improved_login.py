# -*- coding: utf-8 -*-
"""
WebAPI 登录模块集成脚本
将改进版登录功能集成到现有的登录系统中
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.login import TokenExtractor, PROVIDER_CONFIGS
from src.login.improved_login import ImprovedTokenExtractor, TOKEN_EXTRACTION_CONFIGS

def integrate_improved_login():
    """集成改进版登录功能"""
    print("WebAPI 登录模块集成")
    print("=" * 40)
    
    # 检查配置一致性
    print("\n1. 检查配置一致性...")
    
    # 验证所有 Provider 都有改进版配置
    missing_providers = []
    for provider in PROVIDER_CONFIGS:
        if provider not in TOKEN_EXTRACTION_CONFIGS:
            missing_providers.append(provider)
    
    if missing_providers:
        print(f"❌ 缺少配置的 Provider: {missing_providers}")
        return False
    else:
        print("✅ 所有 Provider 都有改进版配置")
    
    # 验证配置兼容性
    print("\n2. 验证配置兼容性...")
    
    compatibility_issues = []
    for provider, old_config in PROVIDER_CONFIGS.items():
        new_config = TOKEN_EXTRACTION_CONFIGS[provider]
        
        # 检查登录 URL 是否一致
        if old_config.get("login_url") != new_config.login_url:
            compatibility_issues.append(f"{provider}: login_url 不匹配")
        
        # 检查 auth_type
        auth_type = old_config.get("auth_type", "token")
        if auth_type == "both":
            # deepseek 需要特殊处理
            continue
        elif auth_type == "token" and new_config.token_sources:
            # 检查是否有 token 类型的提取源
            has_token_source = any(s.type == "networkHeader" for s in new_config.token_sources)
            if not has_token_source:
                compatibility_issues.append(f"{provider}: 缺少 networkHeader 提取源")
    
    if compatibility_issues:
        print("❌ 配置兼容性问题:")
        for issue in compatibility_issues:
            print(f"   - {issue}")
        return False
    else:
        print("✅ 配置兼容性检查通过")
    
    # 创建备份
    print("\n3. 创建备份...")
    backup_path = PROJECT_ROOT / "src" / "login" / "__init__.py.backup"
    original_path = PROJECT_ROOT / "src" / "login" __init__.py
    
    try:
        import shutil
        shutil.copy2(original_path, backup_path)
        print(f"✅ 备份创建成功: {backup_path}")
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return False
    
    # 生成集成代码
    print("\n4. 生成集成代码...")
    
    integration_code = '''# -*- coding: utf-8 -*-
"""
WebAPI 登录模块 - 集成改进版功能
结合原有功能和改进版网络请求拦截
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
import playwright.async_api as playwright
from playwright.async_api import Request, Response

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

# 导入改进版配置
from .improved_login import TOKEN_EXTRACTION_CONFIGS, TokenSource

# 原有配置保持不变
PROVIDER_CONFIGS = {
    "deepseek": {
        "name": "DeepSeek",
        "login_url": "https://chat.deepseek.com/",
        "auth_type": "both",
        "success_url_patterns": ["/cited-chat", "/chat/", "deepseek.com/c"],
        "extractors": [
            # Cookie 用于过 Cloudflare WAF
            {
                "type": "all_cookies",
                "format": "header_string",
                "save_as": "cookie",
            },
            # 从 localStorage 提取 token
            {
                "type": "localStorage",
                "key": "userToken",
                "header_key": "Authorization",
                "header_prefix": "Bearer ",
                "save_as": "token",
            },
            # 从 localStorage 提取 POW token
            {
                "type": "localStorage",
                "key": "powToken",
                "header_key": "pow-token",
                "header_prefix": "",
                "save_as": "powToken",
            },
        ],
        "validate_url": "https://chat.deepseek.com/api/v0/user/info",
        "validate_field": "name",
        "config_key": "cookie",
        "cookie_validate_url": "https://chat.deepseek.com/api/v0/user/info",
        "cookie_validate_check": "name",
        "token_config_key": "token",
        "pow_config_key": "powToken",
    },
    # ... 其他 Provider 配置保持不变
}

class IntegratedTokenExtractor(TokenExtractor):
    """集成版 Token 提取器 - 结合原有功能和改进版网络拦截"""
    
    def __init__(self, provider: str):
        super().__init__(provider)
        self.improved_config = TOKEN_EXTRACTION_CONFIGS.get(provider)
        self.token_monitor = None
        
    async def login(self) -> Optional[dict]:
        """启动登录流程 - 使用改进版功能"""
        print(f"\\n  [*] 启动 {self.provider} 集成版登录...")
        
        # 初始化改进版监控器
        from .improved_login import TokenMonitor
        self.token_monitor = TokenMonitor()
        
        # 设置网络请求监听
        if self.page:
            self.page.on("request", self.token_monitor.capture_request)
            self.page.on("response", self.token_monitor.capture_response)
        
        # 使用原有逻辑，但增加改进版功能
        result = await super().login()
        
        # 处理改进版捕获的 token
        if result and self.token_monitor:
            await self._process_improved_tokens()
        
        return result
    
    async def _process_improved_tokens(self):
        """处理改进版捕获的 token"""
        try:
            # 从队列中获取所有捕获的 token
            while True:
                try:
                    token_data = self.token_monitor.token_queue.get_nowait()
                    await self._handle_improved_token(token_data)
                except asyncio.QueueEmpty:
                    break
        except Exception as e:
            print(f"  [ERROR] 处理改进版 token 失败: {e}")
    
    async def _handle_improved_token(self, token_data: dict):
        """处理单个改进版捕获的 token"""
        token_type = token_data["type"]
        token = token_data["token"]
        
        if token_type == "networkHeader":
            # 从网络请求头获取的 token
            self.extracted_values["token"] = token
            print(f"  [OK]  网络请求头 token ({len(token)} 字符)")
        
        # 可以根据需要处理其他类型的 token
'''
    
    # 写入集成文件
    integration_path = PROJECT_ROOT / "src" / "login" / "integrated_login.py"
    try:
        with open(integration_path, "w", encoding="utf-8") as f:
            f.write(integration_code)
        print(f"✅ 集成代码生成成功: {integration_path}")
    except Exception as e:
        print(f"❌ 集成代码生成失败: {e}")
        return False
    
    print("\n5. 集成完成！")
    print("📝 使用方法:")
    print("   from src.login.integrated_login import IntegratedTokenExtractor")
    print("   extractor = IntegratedTokenExtractor('kimi')")
    print("   result = await extractor.login()")
    
    return True

def main():
    """主函数"""
    if integrate_improved_login():
        print("\n🎉 集成成功！")
        sys.exit(0)
    else:
        print("\n❌ 集成失败！")
        sys.exit(1)

if __name__ == "__main__":
    main()