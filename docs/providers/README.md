# Providers 文档

本文档详细介绍了 WebAPI 项目支持的各个大语言模型提供商及其配置方法。

## 目录

- [DeepSeek Provider](./deepseek.md) - DeepSeek 大语言模型适配器
- [Kimi Provider](./kimi.md) - Kimi（月之暗面）大语言模型适配器
- [Qwen Provider](./qwen.md) - 通义千问大语言模型适配器
- [Doubao Provider](./doubao.md) - 豆包大语言模型适配器
- [Yuanbao Provider](./yuanbao.md) - 元宝大语言模型适配器
- [MiniMax Provider](./minimax.md) - MiniMax 大语言模型适配器

## 快速开始

### 1. 配置 API 密钥

首先，在配置文件中设置各个提供商的 API 密钥：

```yaml
# config.yaml
providers:
  deepseek:
    enabled: true
    api_key: "${DEEPSEEK_API_KEY}"
  
  kimi:
    enabled: true
    api_key: "${KIMI_API_KEY}"
  
  qwen:
    enabled: true
    api_key: "${QWEN_API_KEY}"
  
  doubao:
    enabled: true
    api_key: "${DOUBAO_API_KEY}"
    secret_key: "${DOUBAO_SECRET_KEY}"
  
  yuanbao:
    enabled: true
    api_key: "${YUANBAO_API_KEY}"
  
  minimax:
    enabled: true
    api_key: "${MINIMAX_API_KEY}"
    group_id: "${MINIMAX_GROUP_ID}"
```

### 2. 设置环境变量

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export KIMI_API_KEY="your-kimi-api-key"
export QWEN_API_KEY="your-qwen-api-key"
export DOUBAO_API_KEY="your-doubao-api-key"
export DOUBAO_SECRET_KEY="your-doubao-secret-key"
export YUANBAO_API_KEY="your-yuanbao-api-key"
export MINIMAX_API_KEY="your-minimax-api-key"
export MINIMAX_GROUP_ID="your-minimax-group-id"
```

### 3. 选择模型

通过 API 调用时，选择合适的模型：

```python
import asyncio
from src.provider.registry import get_provider

async def example():
    # 获取不同提供商的模型
    deepseek_provider = get_provider("deepseek-chat")
    kimi_provider = get_provider("kimi-chat")
    qwen_provider = get_provider("qwen-max")
    
    # 使用模型进行对话
    messages = [{"role": "user", "content": "你好"}]
    
    # DeepSeek 对话
    response = await deepseek_provider.chat_completion(messages)
    
    # Kimi 对话
    response = await kimi_provider.chat_completion(messages)
    
    # Qwen 对话
    response = await qwen_provider.chat_completion(messages)
```

## 支持的模型列表

| 提供商 | 模型名称 | 最大 Token | 特点 |
|--------|----------|-----------|------|
| DeepSeek | deepseek-chat | 32K | 强大的中文理解能力 |
| DeepSeek | deepseek-coder | 32K | 专业的代码生成 |
| Kimi | kimi-chat | 128K | 超长上下文窗口 |
| Kimi | kimi-long | 200K | 专门针对超长文档优化 |
| Qwen | qwen-max | 128K | 最强性能，支持多模态 |
| Qwen | qwen-turbo | 32K | 速度快，成本低 |
| Qwen | qwen-plus | 32K | 性能与速度平衡 |
| Qwen | qwen-vl | 32K | 支持图像理解 |
| Doubao | doubao-pro | 32K | 高质量中文理解 |
| Doubao | doubao-lite | 16K | 快速响应，成本低 |
| Doubao | doubao-turbo | 8K | 最快速度，适合简单任务 |
| Yuanbao | yuanbao-chat | 32K | 创意能力强，对话自然 |
| Yuanbao | yuanbao-creative | 64K | 专门优化创意写作 |
| Yuanbao | yuanbao-code | 16K | 专业的代码生成能力 |
| MiniMax | minimax-abab6 | 128K | 强大的中文理解能力 |
| MiniMax | minimax-abab6-chat | 32K | 专门优化对话场景 |
| MiniMax | minimax-text-01 | 32K | 通用文本处理 |
| MiniMax | minimax-code-01 | 16K | 专业的代码生成 |

## 特色功能

### 1. 统一的 API 接口

所有提供商都使用统一的 OpenAI 兼容接口：

```python
# 统一的聊天接口
response = await provider.chat_completion(messages)

# 统一的流式接口
async for chunk in provider.chat_completion_stream(messages):
    content = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
    print(content, end='', flush=True)

# 统一的模型列表
models = await provider.list_models()
```

### 2. 自动负载均衡

WebAPI 支持多个提供商的负载均衡：

```yaml
load_balance:
  strategy: "round_robin"  # 轮询策略
  providers: ["deepseek", "kimi", "qwen"]  # 可用提供商列表
```

### 3. 故障转移

当某个提供商不可用时，自动切换到备用提供商：

```python
# 自动故障转移
try:
    response = await provider.chat_completion(messages)
except ProviderError:
    # 自动切换到备用提供商
    response = await backup_provider.chat_completion(messages)
```

### 4. 请求统计和监控

内置请求统计和监控功能：

```python
# 获取请求统计
stats = await provider.get_stats()

# 监控请求成功率
success_rate = stats.get('success_rate', 0)
```

## 配置选项

### 全局配置

```yaml
# 全局配置
global:
  timeout: 30
  max_retries: 3
  retry_delay: 1
  rate_limit: 100  # 每分钟请求数
```

### 提供商特定配置

```yaml
providers:
  deepseek:
    enabled: true
    timeout: 30
    max_retries: 3
    pow_challenge: true  # DeepSeek 特有的 PoW 挑战
  
  kimi:
    enabled: true
    timeout: 30
    max_retries: 3
    use_grpc: true  # 使用 gRPC 协议
  
  qwen:
    enabled: true
    timeout: 30
    max_retries: 3
    use_cookie_auth: true  # 使用 Cookie 认证
```

## 错误处理

### 常见错误类型

```python
from src.core.exceptions import (
    AuthError,           # 认证错误
    RateLimitError,      # 速率限制错误
    ValidationError,     # 参数验证错误
    ProviderError,      # 提供商错误
    NetworkError        # 网络错误
)

try:
    response = await provider.chat_completion(messages)
except AuthError as e:
    print(f"认证失败: {e}")
except RateLimitError as e:
    print(f"速率限制: {e}")
except ValidationError as e:
    print(f"参数验证失败: {e}")
except ProviderError as e:
    print(f"提供商错误: {e}")
except NetworkError as e:
    print(f"网络错误: {e}")
```

### 重试机制

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def resilient_chat_completion(messages):
    return await provider.chat_completion(messages)
```

## 性能优化

### 1. 连接池管理

使用连接池减少连接开销：

```python
from src.transport.api_reverse import get_transport

transport = get_transport()
session = await transport._get_session()
```

### 2. 缓存机制

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_response(messages_hash, model):
    """缓存响应结果"""
    pass
```

### 3. 批处理请求

```python
async def batch_chat_completion(requests):
    """批量处理多个请求"""
    tasks = []
    for req in requests:
        task = provider.chat_completion(req['messages'], model=req['model'])
        tasks.append(task)
    
    return await asyncio.gather(*tasks)
```

## 监控和日志

### 1. 请求日志

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def logged_chat_completion(messages):
    logger.info(f"开始处理请求，消息数量: {len(messages)}")
    response = await provider.chat_completion(messages)
    logger.info(f"请求完成，Token 使用: {response['usage']['total_tokens']}")
    return response
```

### 2. 性能监控

```python
import time
from functools import wraps

def monitor_performance(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start_time
            logger.info(f"{func.__name__} 完成，耗时: {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{func.__name__} 失败，耗时: {duration:.2f}s，错误: {e}")
            raise
    return wrapper
```

## 最佳实践

### 1. 模型选择策略

根据任务类型选择合适的模型：

```python
def select_model_by_task(task_type):
    """根据任务类型选择模型"""
    model_mapping = {
        "chat": "deepseek-chat",
        "code": "qwen-turbo",
        "creative": "yuanbao-creative",
        "analysis": "kimi-chat",
        "long_text": "kimi-long"
    }
    return model_mapping.get(task_type, "deepseek-chat")
```

### 2. 会话管理

```python
class ChatSession:
    def __init__(self, provider_name):
        self.provider = get_provider(provider_name)
        self.messages = []
    
    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})
    
    async def get_response(self):
        response = await self.provider.chat_completion(self.messages)
        self.add_message("assistant", response['choices'][0]['message']['content'])
        return response
```

### 3. 错误恢复

```python
async def resilient_chat_with_fallback(messages, providers):
    """带故障转移的聊天"""
    for provider_name in providers:
        try:
            provider = get_provider(provider_name)
            response = await provider.chat_completion(messages)
            return response
        except ProviderError as e:
            logger.warning(f"{provider_name} 请求失败: {e}")
            continue
    
    raise Exception("所有提供商都不可用")
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 6 个主要提供商
- 统一的 OpenAI 兼容接口
- 基本的错误处理和重试机制

### v1.1.0
- 添加负载均衡功能
- 增强监控和日志功能
- 优化性能和缓存机制

### v1.2.0
- 支持流式响应
- 添加批处理功能
- 实现智能模型选择

## 相关链接

- [WebAPI 项目主页](https://github.com/your-repo/webapi)
- [OpenAI API 文档](https://platform.openai.com/docs/api-reference)
- [各提供商官方文档](./README.md#目录)

## 贡献指南

欢迎为 Providers 文档贡献内容！请确保：

1. 文档格式统一
2. 示例代码可运行
3. 错误处理完整
4. 性能建议合理

提交 PR 时，请详细描述您的更改内容。