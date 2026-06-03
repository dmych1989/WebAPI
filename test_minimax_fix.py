#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 MiniMax Provider 修复后的功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path.cwd()))

from src.core.config import AccountConfig
from src.provider.minimax import MiniMaxProvider

async def test_minimax_fix():
    """测试 MiniMax 修复"""
    print("MiniMax Provider 修复测试")
    print("=" * 40)
    
    # 创建测试配置
    account_config = AccountConfig(
        name="test-account",
        token="test-token",
        api_base="https://api.minimax.chat",
        models=["MiniMax-Text-01"]
    )
    
    # 创建 Provider 实例
    provider = MiniMaxProvider(account_config)
    
    print(f"API Base URL: {provider._api_base}")
    print(f"Token: {provider._token[:20]}...")
    print(f"Models: {provider.account.models}")
    
    # 测试健康检查
    print("\n1. 测试健康检查...")
    try:
        is_healthy = await provider.health_check()
        print(f"健康状态: {'OK' if is_healthy else 'Failed'}")
    except Exception as e:
        print(f"健康检查失败: {e}")
    
    # 测试模型列表
    print("\n2. 测试模型列表...")
    try:
        models = await provider.list_models()
        print(f"可用模型: {models}")
    except Exception as e:
        print(f"模型列表获取失败: {e}")
    
    # 测试简单对话（不发送实际请求）
    print("\n3. 测试消息转换...")
    try:
        from src.core.models import ChatCompletionRequest, ChatMessage
        
        request = ChatCompletionRequest(
            model="MiniMax-Text-01",
            messages=[
                ChatMessage(role="user", content="你好，这是一个测试消息。")
            ]
        )
        
        prompt = provider._messages_to_prompt(request)
        print(f"转换后的提示: {prompt[:100]}...")
        print("消息转换成功")
    except Exception as e:
        print(f"消息转换失败: {e}")
    
    print("\n测试完成！")

if __name__ == "__main__":
    asyncio.run(test_minimax_fix())