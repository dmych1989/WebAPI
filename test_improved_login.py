#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试改进版 Token 提取器的网络请求拦截功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.login.improved_login import ImprovedTokenExtractor, TokenMonitor

async def test_network_interception():
    """测试网络请求拦截"""
    print("Testing Network Request Interception...")
    
    # 创建 TokenMonitor
    monitor = TokenMonitor()
    
    # 模拟请求
    test_requests = [
        {
            "url": "https://www.kimi.com/api/chat",
            "headers": {
                "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
                "Content-Type": "application/json"
            }
        },
        {
            "url": "https://www.kimi.com/api/user/info",
            "headers": {
                "Authorization": "Bearer another_token_here",
                "User-Agent": "Mozilla/5.0"
            }
        },
        {
            "url": "https://example.com/some-other-url",
            "headers": {
                "Content-Type": "text/html"
            }
        }
    ]
    
    # 模拟请求捕获
    for i, req in enumerate(test_requests):
        print(f"\nTesting request {i+1}: {req['url']}")
        
        # 检查是否应该捕获
        should_capture = monitor._should_capture_url(req['url'])
        print(f"  Should capture: {should_capture}")
        
        if should_capture:
            # 模拟请求头捕获
            auth_header = req['headers'].get("Authorization", "")
            if auth_header:
                token = monitor._extract_token_from_header(auth_header)
                if token:
                    print(f"  Captured token: {token[:20]}...")
                    monitor.extracted_tokens.add(token)
                    await monitor.token_queue.put({
                        "type": "networkHeader",
                        "token": token,
                        "url": req['url'],
                        "timestamp": asyncio.get_event_loop().time()
                    })
    
    # 检查捕获的 token
    print(f"\nTotal captured tokens: {len(monitor.extracted_tokens)}")
    for i, token in enumerate(monitor.extracted_tokens, 1):
        print(f"  {i}. {token[:20]}...")

async def test_token_extraction():
    """测试 Token 提取配置"""
    print("\n" + "="*50)
    print("Testing Token Extraction Configs")
    print("="*50)
    
    from src.login.improved_login import TOKEN_EXTRACTION_CONFIGS
    
    for provider, config in TOKEN_EXTRACTION_CONFIGS.items():
        print(f"\n{provider.upper()}:")
        print(f"  Login URL: {config.login_url}")
        print(f"  Target Domains: {config.target_domains}")
        print(f"  Success URL Patterns: {config.success_url_patterns}")
        print(f"  Token Sources:")
        
        for i, source in enumerate(config.token_sources, 1):
            print(f"    {i}. {source.type} - {source.key}")
            if source.url_pattern:
                print(f"       URL Pattern: {source.url_pattern}")
            if source.extract_pattern:
                print(f"       Extract Pattern: {source.extract_pattern}")

async def main():
    """主测试函数"""
    print("WebAPI Improved Login - Test Suite")
    print("="*40)
    
    await test_network_interception()
    await test_token_extraction()
    
    print("\n" + "="*40)
    print("Test completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())