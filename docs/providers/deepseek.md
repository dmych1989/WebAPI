# DeepSeek Provider

## 概述

DeepSeek Provider 是 WebAPI 对接 DeepSeek 大语言模型服务的适配器。DeepSeek 是一家专注于大语言模型研发的中国 AI 公司，提供多个高质量的对话模型。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| deepseek-chat | DeepSeek 对话模型 | 32K | 强大的中文理解能力，支持长上下文 |
| deepseek-coder | DeepSeek 代码模型 | 32K | 专业的代码生成和理解 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  deepseek:
    enabled: true
    api_base: "https://api.deepseek.com"
    api_key: "${DEEPSEEK_API_KEY}"  # 从环境变量读取
    timeout: 30
    max_retries: 3
    pow_challenge: true  # 启用 PoW 挑战验证
```

### 环境变量

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
```

## 认证方式

DeepSeek 使用 Bearer Token 认证方式，需要在请求头中包含：

```http
Authorization: Bearer your-api-key
```

## 特殊功能

### 1. PoW 挑战验证

DeepSeek 有时会要求进行 Proof of Work (PoW) 验证以防止滥用。Provider 会自动处理 PoW 挑战：

```python
# 自动处理 PoW 挑战
response = await provider.chat_completion(messages)
```

### 2. 流式响应

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

# 获取 DeepSeek Provider
provider = get_provider("deepseek-chat")

messages = [
    {"role": "system", "content": "你是一个专业的助手。"},
    {"role": "user", "content": "请解释一下什么是机器学习。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 代码生成

```python
# 使用 deepseek-coder 模型生成代码
provider = get_provider("deepseek-coder")

messages = [
    {"role": "user", "content": "用 Python 写一个快速排序算法"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

## API 端点映射

| WebAPI 端点 | DeepSeek 端点 | 说明 |
|------------|--------------|------|
| `/v1/chat/completions` | `/chat/completions` | 聊天完成 |
| `/v1/models` | `/models` | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 401 | AuthError | API Key 无效或过期 |
| 429 | RateLimitError | 请求频率超限 |
| 500 | ProviderError | 服务器内部错误 |

### PoW 挑战错误

当遇到 PoW 挑战时，Provider 会自动处理，但如果失败会抛出异常：

```python
try:
    response = await provider.chat_completion(messages)
except ProviderError as e:
    if "pow_challenge" in str(e):
        print("PoW 挑战失败，请检查网络连接")
    else:
        raise e
```

## 性能优化

### 1. 连接池

使用单例模式的 `aiohttp.ClientSession`，避免重复建立连接：

```python
# 获取传输层实例
transport = get_transport()
session = await transport._get_session()
```

### 2. 超时配置

合理设置超时时间，避免长时间等待：

```yaml
providers:
  deepseek:
    timeout: 30  # 30秒超时
    connect_timeout: 10  # 连接超时
```

## 故障排除

### 1. 连接问题

确保网络可以访问 DeepSeek API：

```bash
curl -X GET "https://api.deepseek.com/models" -H "Authorization: Bearer your-api-key"
```

### 2. PoW 挑战问题

如果频繁遇到 PoW 挑战，可能需要：

- 检查 IP 是否被列入黑名单
- 降低请求频率
- 使用代理或更换 IP

### 3. 速率限制

DeepSeek 有请求频率限制，建议：

- 实现请求队列
- 添加重试机制
- 监控使用情况

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 deepseek-chat 和 deepseek-coder 模型
- 实现 PoW 挑战验证
- 支持流式响应

## 相关链接

- [DeepSeek 官方文档](https://platform.deepseek.com/)
- [DeepSeek API 参考](https://api-docs.deepseek.com/)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)