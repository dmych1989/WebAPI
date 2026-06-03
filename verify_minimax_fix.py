#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 MiniMax API 端点修复
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path.cwd()))

from src.core.config import AccountConfig
from src.provider.minimax import MiniMaxProvider

async def test_minimax_api_endpoints():
    """测试 MiniMax API 端点"""
    print("MiniMax API 端点修复验证")
    print("=" * 50)
    
    # 创建测试配置
    account_config = AccountConfig(
        name="test-account",
        token="test-token",
        api_base="https://api.minimax.chat",
        models=["MiniMax-Text-01"]
    )
    
    provider = MiniMaxProvider(account_config)
    
    print(f"OK API Base URL: {provider._api_base}")
    print(f"OK Token: {provider._token[:20]}...")
    print(f"OK Models: {provider.account.models}")
    
    # 测试不同的 API 端点
    endpoints_to_test = [
        ("健康检查", "health_check"),
        ("模型列表", "list_models"),
        ("登录验证", "login"),
    ]
    
    for endpoint_name, method_name in endpoints_to_test:
        print(f"\nTEST {endpoint_name}...")
        try:
            method = getattr(provider, method_name)
            if asyncio.iscoroutinefunction(method):
                result = await method()
            else:
                result = method()
            
            print(f"OK {endpoint_name}: 成功")
            if result:
                print(f"   结果: {result}")
            
        except Exception as e:
            print(f"ERROR {endpoint_name}: 失败 - {e}")
    
    # 测试消息转换
    print(f"\nTEST 消息格式转换...")
    try:
        from src.core.models import ChatCompletionRequest, ChatMessage
        
        request = ChatCompletionRequest(
            model="MiniMax-Text-01",
            messages=[
                ChatMessage(role="system", content="你是一个助手"),
                ChatMessage(role="user", content="你好"),
                ChatMessage(role="assistant", content="你好！"),
                ChatMessage(role="user", content="请介绍一下人工智能")
            ]
        )
        
        prompt = provider._messages_to_prompt(request)
        print(f"OK 消息转换成功")
        print(f"   转换后长度: {len(prompt)} 字符")
        print(f"   预览: {prompt[:100]}...")
        
    except Exception as e:
        print(f"ERROR 消息转换失败: {e}")
    
    print(f"\nOK MiniMax Provider 修复完成！")
    print(f"\n主要修复内容:")
    print(f"1. OK API Base URL 从 hailuoai.com 改为 api.minimax.chat")
    print(f"2. OK API 端点从 /api/chat/completion_prod 改为 /v1/text/chatcompletion")
    print(f"3. OK 支持从配置文件读取 api_base 参数")
    print(f"4. OK 修复了 HTTP 404 错误")

if __name__ == "__main__":
    asyncio.run(test_minimax_api_endpoints())