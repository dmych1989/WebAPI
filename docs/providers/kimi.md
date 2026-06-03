# Kimi Provider

## 概述

Kimi Provider 是 WebAPI 对接 Kimi 大语言模型服务的适配器。Kimi 是由月之暗面（Moonshot AI）开发的大语言模型，以其强大的长文本处理能力而闻名。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| kimi-chat | Kimi 对话模型 | 128K | 超长上下文窗口，擅长处理长文本 |
| kimi-long | Kimi 长文本模型 | 200K | 专门针对超长文档优化 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  kimi:
    enabled: true
    api_base: "https://api.moonshot.cn"
    api_key: "${KIMI_API_KEY}"  # 从环境变量读取
    timeout: 30
    max_retries: 3
    use_grpc: true  # 使用 gRPC-Web 协议
```

### 环境变量

```bash
export KIMI_API_KEY="your-kimi-api-key"
```

## 认证方式

Kimi 使用 Bearer Token 认证方式，需要在请求头中包含：

```http
Authorization: Bearer your-api-key
```

## 特殊功能

### 1. gRPC-Web 协议支持

Kimi 原生支持 gRPC-Web 协议，Provider 会自动使用 gRPC 进行通信：

```python
# 自动使用 gRPC 协议
response = await provider.chat_completion(messages)
```

### 2. 超长上下文

Kimi 支持 128K 甚至 200K 的超长上下文，适合处理长文档：

```python
# 处理长文档
long_context = """在这里放入很长的文档内容..."""
messages = [
    {"role": "user", "content": f"请总结以下文档：\n\n{long_context}"}
]

response = await provider.chat_completion(messages)
```

### 3. 流式响应

支持 OpenAI 兼容的流式响应格式：

```python
# 流式对话
async for chunk in provider.chat_completion_stream(messages):
    content = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
    print(content, end='', flush=True)
```

## 使用示例

### 基本对话

```python
from src.provider.registry import get_provider

# 获取 Kimi Provider
provider = get_provider("kimi-chat")

messages = [
    {"role": "system", "content": "你是一个专业的助手。"},
    {"role": "user", "content": "请解释一下什么是区块链技术。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 长文档处理

```python
# 使用 kimi-long 模型处理长文档
provider = get_provider("kimi-long")

# 假设我们有一个很长的PDF文档内容
pdf_content = """...这里是很长的PDF文档内容..."""

messages = [
    {"role": "user", "content": f"""请分析以下PDF文档的主要内容：
    
{pdf_content}

请提供：
1. 文档主题
2. 主要观点
3. 关键数据
4. 结论建议
"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 代码分析与优化

```python
# 分析代码质量
code_snippet = """
def calculate_sum(numbers):
    total = 0
    for num in numbers:
        total += num
    return total
"""

messages = [
    {"role": "user", "content": f"""请分析以下代码的质量和可能的改进：

{code_snippet}

请从以下方面分析：
1. 代码可读性
2. 性能考虑
3. 潜在问题
4. 改进建议
"""}
]

response = await provider.chat_completion(messages)
```

## API 端点映射

| WebAPI 端点 | Kimi 端点 | 说明 |
|------------|----------|------|
| `/v1/chat/completions` | `/v1/chat/completions` | 聊天完成 |
| `/v1/models` | `/v1/models` | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 401 | AuthError | API Key 无效或过期 |
| 429 | RateLimitError | 请求频率超限 |
| 400 | ValidationError | 请求参数错误 |
| 500 | ProviderError | 服务器内部错误 |

### gRPC 错误处理

```python
try:
    response = await provider.chat_completion(messages)
except ProviderError as e:
    if "grpc" in str(e):
        print("gRPC 连接失败，尝试降级到 HTTP")
        # 可以在这里实现降级逻辑
    else:
        raise e
```

## 性能优化

### 1. gRPC 连接池

使用 gRPC 连接池提高性能：

```yaml
providers:
  kimi:
    use_grpc: true
    grpc_pool_size: 5
    grpc_timeout: 30
```

### 2. 批处理请求

对于多个请求，可以考虑批处理：

```python
# 批处理多个请求
requests = [
    {"messages": [...], "model": "kimi-chat"},
    {"messages": [...], "model": "kimi-chat"},
]

# 可以实现批处理逻辑
```

### 3. 缓存机制

对于重复的请求，可以实现缓存：

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_chat_completion(messages_hash, model):
    return provider.chat_completion(messages)
```

## 故障排除

### 1. gRPC 连接问题

如果 gRPC 连接失败，可以降级到 HTTP：

```yaml
providers:
  kimi:
    use_grpc: false  # 禁用 gRPC，使用 HTTP
```

### 2. 长文本处理问题

如果处理超长文本时出现问题：

- 检查 token 计数是否正确
- 考虑使用滑动窗口策略
- 实现分块处理

### 3. 速率限制

Kimi 对长文本请求有特殊限制：

```python
# 实现请求间隔控制
import asyncio
import time

async def rate_limited_request(messages):
    await asyncio.sleep(1)  # 请求间隔1秒
    return await provider.chat_completion(messages)
```

## 最佳实践

### 1. 上下文管理

对于长文档，合理管理上下文：

```python
def split_long_text(text, max_chunk_size=10000):
    """分割长文本为多个块"""
    chunks = []
    current_chunk = ""
    
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += '\n' + line if current_chunk else line
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks
```

### 2. 错误重试

实现智能重试机制：

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def resilient_chat_completion(messages):
    return await provider.chat_completion(messages)
```

### 3. 监控和日志

添加详细的监控和日志：

```python
import logging

logger = logging.getLogger(__name__)

async def monitored_chat_completion(messages):
    start_time = time.time()
    try:
        response = await provider.chat_completion(messages)
        duration = time.time() - start_time
        logger.info(f"Chat completion completed in {duration:.2f}s")
        return response
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Chat completion failed after {duration:.2f}s: {e}")
        raise
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 kimi-chat 和 kimi-long 模型
- 实现 gRPC-Web 协议支持
- 支持超长上下文处理

### v1.1.0
- 添加 HTTP 降级支持
- 优化长文本处理性能
- 增强错误处理机制

## 相关链接

- [Kimi 官方文档](https://platform.moonshot.cn/)
- [Kimi API 参考](https://api-docs.moonshot.cn/)
- [Moonshot AI 官网](https://www.moonshot.cn/)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)