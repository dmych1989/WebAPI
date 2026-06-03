#!/usr/bin/env python3
"""
WebAPI OpenAI SDK 兼容示例

这个示例展示了如何使用 OpenAI SDK 兼容的方式调用 WebAPI，
让现有使用 OpenAI API 的代码可以无缝迁移到 WebAPI。
"""

import asyncio
import json
import sys
from typing import Optional, Dict, Any, List, Union

import aiohttp


class WebAPIAsyncClient:
    """
    WebAPI Async Client - OpenAI SDK 兼容接口
    
    这个类提供了与 OpenAI SDK 类似的接口，让现有代码可以无缝迁移。
    """
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = "your-api-key-here"):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送 HTTP 请求"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        headers.update(kwargs.pop('headers', {}))
        
        async with self.session.request(method, url, headers=headers, **kwargs) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                raise Exception(f"HTTP {response.status}: {error_text}")
    
    async def chat.completions.create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[Dict[str, Any], AsyncIterator[Dict[str, Any]]]:
        """
        创建聊天完成
        
        Args:
            model: 模型名称，如 "deepseek-chat", "kimi-chat" 等
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            stream: 是否流式输出
            **kwargs: 其他参数
            
        Returns:
            响应数据或流式响应迭代器
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
            
        # 添加其他参数
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        
        if stream:
            return self._stream_chat_completions(payload)
        else:
            return await self._request("POST", "/v1/chat/completions", json=payload)
    
    async def _stream_chat_completions(self, payload: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """流式聊天完成"""
        async with self.session.post(
            f"{self.base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json=payload
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"HTTP {response.status}: {error_text}")
            
            async for chunk in response.content:
                if chunk:
                    line = chunk.decode('utf-8').strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            yield data
                        except json.JSONDecodeError:
                            pass
    
    async def models.list(self) -> Dict[str, Any]:
        """列出可用模型"""
        return await self._request("GET", "/v1/models")
    
    async def models.retrieve(self, model_id: str) -> Dict[str, Any]:
        """获取模型信息"""
        return await self._request("GET", f"/v1/models/{model_id}")


# OpenAI SDK 兼容的别名
ChatCompletion = WebAPIAsyncClient
ChatCompletionStream = WebAPIAsyncClient


async def basic_usage_example():
    """基本使用示例"""
    print("🚀 OpenAI SDK 兼容 - 基本使用")
    print("=" * 50)
    
    # 使用方式与 OpenAI SDK 类似
    async with WebAPIAsyncClient(
        base_url="http://localhost:8000",
        api_key="your-api-key-here"  # 替换为实际 API key
    ) as client:
        
        messages = [
            {"role": "system", "content": "你是一个专业的编程助手。"},
            {"role": "user", "content": "请用 Python 写一个快速排序算法。"}
        ]
        
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            
            print("✅ 聊天完成:")
            print(response['choices'][0]['message']['content'])
            print(f"📊 Token 使用: {response['usage']['total_tokens']}")
            
        except Exception as e:
            print(f"❌ 错误: {str(e)}")


async def streaming_example():
    """流式响应示例"""
    print("\n🌊 流式响应示例")
    print("=" * 50)
    
    async with WebAPIAsyncClient(
        base_url="http://localhost:8000",
        api_key="your-api-key-here"
    ) as client:
        
        messages = [
            {"role": "user", "content": "请简单介绍一下人工智能的发展历史。"}
        ]
        
        try:
            print("🎬 流式响应:")
            print("-" * 30)
            
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                stream=True,
                temperature=0.7
            )
            
            async for chunk in response:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    delta = chunk['choices'][0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        print(content, end='', flush=True)
            
            print("\n" + "-" * 30)
            print("✅ 流式响应完成")
            
        except Exception as e:
            print(f"❌ 错误: {str(e)}")


async def models_example():
    """模型管理示例"""
    print("\n📋 模型管理示例")
    print("=" * 50)
    
    async with WebAPIAsyncClient(
        base_url="http://localhost:8000",
        api_key="your-api-key-here"
    ) as client:
        
        try:
            # 列出所有模型
            models_response = await client.models.list()
            
            print("🎯 可用模型:")
            print("-" * 40)
            
            for model in models_response['data']:
                print(f"📝 {model['id']}")
                if 'provider' in model:
                    print(f"   🏢 提供商: {model['provider']}")
                if 'max_tokens' in model:
                    print(f"   📏 最大 Token: {model['max_tokens']}")
                print()
            
            # 获取特定模型信息（如果有）
            if models_response['data']:
                model_id = models_response['data'][0]['id']
                model_info = await client.models.retrieve(model_id)
                print(f"📊 {model_id} 详细信息:")
                print(json.dumps(model_info, indent=2, ensure_ascii=False))
                
        except Exception as e:
            print(f"❌ 错误: {str(e)}")


async def different_providers_example():
    """不同提供商示例"""
    print("\n🔄 不同提供商示例")
    print("=" * 50)
    
    providers = [
        ("deepseek-chat", "DeepSeek"),
        ("kimi-chat", "Kimi"),
        ("qwen-max", "Qwen"),
        ("yuanbao-chat", "Yuanbao"),
    ]
    
    async with WebAPIAsyncClient(
        base_url="http://localhost:8000",
        api_key="your-api-key-here"
    ) as client:
        
        messages = [
            {"role": "system", "content": "请用一句话介绍你自己。"},
            {"role": "user", "content": "你是谁？"}
        ]
        
        for model, provider in providers:
            try:
                print(f"\n🏢 {provider} ({model}):")
                print("-" * 30)
                
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.5,
                    max_tokens=100
                )
                
                print(response['choices'][0]['message']['content'])
                
            except Exception as e:
                print(f"❌ {provider} 错误: {str(e)}")


async def main():
    """主函数"""
    print("WebAPI OpenAI SDK 兼容示例")
    print("=" * 60)
    print("注意: 请确保 WebAPI 服务正在运行，并修改 api_key 为有效值")
    print("=" * 60)
    
    # 检查 API key
    if "your-api-key-here" in [WebAPIAsyncClient(api_key="your-api-key-here").api_key]:
        print("⚠️  请修改代码中的 api_key 为实际值")
        return
    
    # 运行示例
    await basic_usage_example()
    await streaming_example()
    await models_example()
    await different_providers_example()


if __name__ == "__main__":
    asyncio.run(main())