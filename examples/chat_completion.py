#!/usr/bin/env python3
"""
WebAPI Chat Completion Example

这个示例展示了如何使用 WebAPI 的 chat completion 接口，
与多个 LLM 提供商（DeepSeek, Kimi, Qwen, Doubao, Yuanbao, MiniMax）进行对话。
"""

import asyncio
import json
import sys
from typing import Optional

import aiohttp

# WebAPI 配置
WEBAPI_BASE_URL = "http://localhost:8000"  # 根据实际情况修改
API_KEY = "your-api-key-here"  # 替换为实际的 API key


async def chat_completion_example():
    """聊天完成示例"""
    print("🚀 WebAPI Chat Completion Example")
    print("=" * 50)
    
    # 请求消息
    messages = [
        {"role": "system", "content": "你是一个有用的 AI 助手。"},
        {"role": "user", "content": "你好，请介绍一下 WebAPI 项目。"}
    ]
    
    # 请求体
    payload = {
        "model": "deepseek-chat",  # 可以替换为其他模型，如 kimi-chat, qwen-max 等
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    # 请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # 发送请求
            async with session.post(
                f"{WEBAPI_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    # 打印响应
                    print(f"✅ 请求成功")
                    print(f"📝 模型: {result['model']}")
                    print(f"🎯 Token 使用: {result['usage']['total_tokens']}")
                    print(f"💬 回复:")
                    print(result['choices'][0]['message']['content'])
                    
                else:
                    error_text = await response.text()
                    print(f"❌ 请求失败: {response.status}")
                    print(f"📄 错误信息: {error_text}")
                    
    except Exception as e:
        print(f"❌ 异常: {str(e)}")


async def streaming_chat_example():
    """流式聊天完成示例"""
    print("\n🌊 Streaming Chat Completion Example")
    print("=" * 50)
    
    messages = [
        {"role": "system", "content": "你是一个简洁的 AI 助手。"},
        {"role": "user", "content": "请解释一下什么是机器学习，用简单的语言。"}
    ]
    
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.7,
        "stream": True
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WEBAPI_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    print("🎬 流式响应:")
                    print("-" * 30)
                    
                    async for chunk in response.content:
                        if chunk:
                            # 解析 SSE 格式的响应
                            line = chunk.decode('utf-8').strip()
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                
                                try:
                                    data = json.loads(data_str)
                                    if 'choices' in data and len(data['choices']) > 0:
                                        delta = data['choices'][0].get('delta', {})
                                        content = delta.get('content', '')
                                        if content:
                                            print(content, end='', flush=True)
                                except json.JSONDecodeError:
                                    pass
                    
                    print("\n" + "-" * 30)
                    print("✅ 流式响应完成")
                    
                else:
                    error_text = await response.text()
                    print(f"❌ 请求失败: {response.status}")
                    print(f"📄 错误信息: {error_text}")
                    
    except Exception as e:
        print(f"❌ 异常: {str(e)}")


async def list_models_example():
    """列出可用模型示例"""
    print("\n📋 List Models Example")
    print("=" * 50)
    
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{WEBAPI_BASE_URL}/v1/models",
                headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    print("🎯 可用模型列表:")
                    print("-" * 40)
                    
                    for model in result['data']:
                        print(f"📝 {model['id']}")
                        if 'provider' in model:
                            print(f"   🏢 提供商: {model['provider']}")
                        if 'max_tokens' in model:
                            print(f"   📏 最大 Token: {model['max_tokens']}")
                        print()
                        
                else:
                    error_text = await response.text()
                    print(f"❌ 请求失败: {response.status}")
                    print(f"📄 错误信息: {error_text}")
                    
    except Exception as e:
        print(f"❌ 异常: {str(e)}")


async def health_check_example():
    """健康检查示例"""
    print("\n🏥 Health Check Example")
    print("=" * 50)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WEBAPI_BASE_URL}/health") as response:
                if response.status == 200:
                    result = await response.json()
                    
                    print("✅ 服务状态: 健康")
                    print(f"📊 统计信息:")
                    for key, value in result.items():
                        print(f"   {key}: {value}")
                        
                else:
                    print(f"❌ 服务状态异常: {response.status}")
                    
    except Exception as e:
        print(f"❌ 连接失败: {str(e)}")


async def main():
    """主函数"""
    print("WebAPI 示例程序")
    print("=" * 60)
    print("注意: 请确保 WebAPI 服务正在运行，并修改 API_KEY 为有效值")
    print("=" * 60)
    
    # 检查 API_KEY 是否已设置
    if API_KEY == "your-api-key-here":
        print("⚠️  请修改代码中的 API_KEY 为实际值")
        return
    
    # 运行各个示例
    await health_check_example()
    await list_models_example()
    await chat_completion_example()
    await streaming_chat_example()


if __name__ == "__main__":
    asyncio.run(main())