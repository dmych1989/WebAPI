# Coze Provider

## 概述

Coze Provider 是 WebAPI 对接 Coze 大语言模型服务的适配器。Coze 是字节跳动推出的 AI 对话平台，提供多个高质量的对话模型，支持自定义 Bot 和对话管理。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| coze-chat | Coze 对话模型 | 2000 | 流畅的对话体验 |
| coze-embedding | Coze 嵌入模型 | 1000 | 文本向量生成 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  coze:
    enabled: true
    api_base: "https://api.coze.cn"
    api_key: "${COZE_API_KEY}"  # 从环境变量读取
    bot_id: "${COZE_BOT_ID}"    # 从环境变量读取
    user_id: "webapi_user"      # 用户 ID
    timeout: 30
    max_retries: 3
    conversation_ttl: 3600      # 对话过期时间（秒）
```

### 环境变量

```bash
export COZE_API_KEY="your-coze-api-key"
export COZE_BOT_ID="your-bot-id"
```

## 认证方式

Coze 使用 Bearer Token 认证方式，需要在请求头中包含：

```http
Authorization: Bearer your-api-key
```

## 特殊功能

### 1. 对话会话管理

Coze Provider 自动管理对话会话，支持多轮对话：

```python
# 自动会话管理
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

### 3. 自定义 Bot

支持使用自定义的 Bot ID 进行对话：

```python
# 使用自定义 Bot
provider = get_provider("coze-chat")
response = await provider.chat_completion(
    messages,
    bot_id="your-custom-bot-id"
)
```

## 使用示例

### 基本对话

```python
from src.provider.registry import get_provider

# 获取 Coze Provider
provider = get_provider("coze-chat")

messages = [
    {"role": "system", "content": "你是一个专业的助手。"},
    {"role": "user", "content": "请介绍一下人工智能的发展历史。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 流式对话

```python
# 使用流式响应
async for chunk in provider.chat_completion_stream(messages):
    content = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
    print(content, end='', flush=True)
```

### 多轮对话

```python
# 多轮对话保持上下文
messages = [
    {"role": "user", "content": "我想学习机器学习，应该从哪里开始？"},
    {"role": "assistant", "content": "机器学习是人工智能的一个重要分支..."},
    {"role": "user", "content": "能推荐一些入门书籍吗？"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 自定义 Bot 对话

```python
# 使用自定义 Bot
provider = CozeProvider({
    "api_key": "your-api-key",
    "bot_id": "your-custom-bot-id"
})

messages = [
    {"role": "user", "content": "请介绍一下你的功能。"}
]

response = await provider.chat_completion(messages)
```

## API 端点映射

| WebAPI 端点 | Coze 端点 | 说明 |
|------------|----------|------|
| `/v1/chat/completions` | `/v3/chat/chat` | 聊天完成 |
| `/v1/models` | 自定义实现 | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 401 | AuthError | API Key 无效或过期 |
| 429 | RateLimitError | 请求频率超限 |
| 400 | ValidationError | 请求参数错误 |
| 500 | ProviderError | 服务器内部错误 |

### 会话错误处理

```python
try:
    response = await provider.chat_completion(messages)
except AuthError as e:
    if "session" in str(e):
        print("会话过期，正在重新建立会话...")
        # Provider 会自动处理会话重建
        response = await provider.chat_completion(messages)
    else:
        raise e
```

### Bot 配置错误

```python
try:
    response = await provider.chat_completion(messages)
    ProviderError as e:
    if "bot" in str(e):
        print("Bot 配置错误，请检查 Bot ID")
        # 检查 Bot ID 是否正确
    else:
        raise e
```

## 性能优化

### 1. 会话复用

```python
class CozeSessionManager:
    def __init__(self):
        self.sessions = {}
    
    async def get_response(self, user_id, messages):
        # 获取或创建用户会话
        if user_id not in self.sessions:
            self.sessions[user_id] = await provider._create_conversation()
        
        response = await provider.chat_completion(
            messages,
            conversation_id=self.sessions[user_id]
        )
        return response
```

### 2. 请求批处理

```python
async def batch_coze_requests(requests):
    """批量处理 Coze 请求"""
    results = []
    for req in requests:
        response = await provider.chat_completion(
            req['messages'],
            model=req.get('model', 'coze-chat')
        )
        results.append(response)
    return results
```

### 3. 缓存机制

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_coze_response(messages_hash, model):
    """缓存 Coze 响应"""
    # 解析 messages_hash 获取原始消息
    messages = parse_messages_hash(messages_hash)
    return provider.chat_completion(messages, model=model)
```

## 故障排除

### 1. API Key 问题

```python
def troubleshoot_coze_auth():
    """排查 Coze 认证问题"""
    try:
        # 测试 API Key 有效性
        response = await provider.health_check()
        if response['healthy']:
            print("API Key 有效")
            return True
        else:
            print(f"认证失败: {response['error']}")
            return False
    except Exception as e:
        print(f"认证检查失败: {e}")
        return False
```

### 2. Bot ID 配置问题

```python
def validate_bot_configuration():
    """验证 Bot 配置"""
    try:
        # 检查 Bot ID 是否正确
        if not provider.bot_id:
            print("Bot ID 未配置")
            return False
        
        # 测试 Bot 是否可用
        response = await provider.chat_completion(
            [{"role": "user", "content": "test"}]
        )
        print("Bot 配置正确")
        return True
    except Exception as e:
        print(f"Bot 配置错误: {e}")
        return False
```

### 3. 会话管理问题

```python
def troubleshoot_conversation_management():
    """排查会话管理问题"""
    try:
        # 检查会话数量
        session_count = len(provider.conversations)
        print(f"当前会话数量: {session_count}")
        
        # 清理过期会话
        current_time = time.time()
        expired_sessions = [
            cid for cid, session in provider.conversations.items()
            if current_time - session['created_at'] > provider.conversation_ttl
        ]
        
        for session_id in expired_sessions:
            del provider.conversations[session_id]
            print(f"清理过期会话: {session_id}")
        
        return True
    except Exception as e:
        print(f"会话管理错误: {e}")
        return False
```

## 最佳实践

### 1. 会话管理

```python
class CozeConversationManager:
    def __init__(self, provider, max_sessions=100):
        self.provider = provider
        self.max_sessions = max_sessions
        self.user_sessions = {}
    
    async def get_or_create_session(self, user_id):
        """获取或创建用户会话"""
        if user_id not in self.user_sessions:
            # 创建新会话
            conversation_id = await self.provider._create_conversation()
            self.user_sessions[user_id] = conversation_id
            
            # 检查会话数量限制
            if len(self.user_sessions) > self.max_sessions:
                # 删除最旧的会话
                oldest_user = min(self.user_sessions.keys(), 
                                key=lambda k: self.provider.conversations[self.user_sessions[k]]['created_at'])
                del self.user_sessions[oldest_user]
        
        return self.user_sessions[user_id]
    
    async def chat(self, user_id, messages):
        """使用用户会话进行对话"""
        conversation_id = await self.get_or_create_session(user_id)
        response = await self.provider.chat_completion(
            messages,
            conversation_id=conversation_id
        )
        return response
```

### 2. 错误重试

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def resilient_coze_chat(messages, **kwargs):
    """带重试的 Coze 聊天"""
    return await provider.chat_completion(messages, **kwargs)
```

### 3. 内容安全检查

```python
def check_coze_content_safety(content):
    """检查 Coze 内容安全性"""
    # Coze 有内置的内容安全机制
    # 这里可以添加额外的安全检查
    sensitive_keywords = ["暴力", "色情", "违法", "犯罪"]
    
    content_lower = content.lower()
    for keyword in sensitive_keywords:
        if keyword in content_lower:
            return False, f"包含敏感词: {keyword}"
    
    return True, "内容安全"
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 coze-chat 和 coze-embedding 模型
- 实现对话会话管理
- 支持流式响应
- 添加健康检查功能

## 相关链接

- [Coze 官方文档](https://www.coze.cn/)
- [Coze 开发者平台](https://www.coze.cn/docs)
- [Coze API 参考](https://www.coze.cn/docs/api)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)