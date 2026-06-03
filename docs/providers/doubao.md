# Doubao Provider

## 概述

Doubao Provider 是 WebAPI 对接豆包（Doubao）大语言模型服务的适配器。豆包是百度开发的大语言模型，专注于中文理解和生成，在中文场景下表现优异。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| doubao-pro | 豆包专业版 | 32K | 高质量中文理解 |
| doubao-lite | 豆包轻量版 | 16K | 快速响应，成本低 |
| doubao-turbo | 豆包极速版 | 8K | 最快速度，适合简单任务 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  doubao:
    enabled: true
    api_base: "https://aip.baidubce.com"
    api_key: "${DOUBAO_API_KEY}"  # 从环境变量读取
    secret_key: "${DOUBAO_SECRET_KEY}"  # 百度 API Secret
    timeout: 30
    max_retries: 3
    access_token_auto_refresh: true  # 自动刷新访问令牌
```

### 环境变量

```bash
export DOUBAO_API_KEY="your-doubao-api-key"
export DOUBAO_SECRET_KEY="your-doubao-secret-key"
```

## 认证方式

豆包使用百度云 API 认证方式，需要获取 Access Token：

### 1. API Key + Secret Key 认证

```python
# 获取 Access Token
access_token = await doubao_provider.get_access_token()
```

### 2. Access Token 直接使用

```http
Authorization: Bearer your-access-token
```

## 特殊功能

### 1. 自动令牌刷新

Provider 会自动管理 Access Token 的生命周期：

```python
# 自动处理令牌刷新
response = await provider.chat_completion(messages)
```

### 2. 中文优化

针对中文场景进行了特别优化：

```python
# 中文理解增强
messages = [
    {"role": "system", "content": "你是一个专业的中文助手。"},
    {"role": "user", "content": "请用中文解释一下什么是元宇宙。"}
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

# 获取豆包 Provider
provider = get_provider("doubao-pro")

messages = [
    {"role": "system", "content": "你是一个专业的中文助手。"},
    {"role": "user", "content": "请介绍一下中国的传统文化。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 中文写作辅助

```python
# 使用 doubao-pro 进行中文写作
provider = get_provider("doubao-pro")

messages = [
    {"role": "user", "content": """请帮我写一篇关于人工智能的短文，要求：
1. 800字左右
2. 通俗易懂
3. 包含实际应用案例
4. 结尾要有个人观点"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 代码生成

```python
# 使用 doubao-turbo 快速生成代码
provider = get_provider("doubao-turbo")

messages = [
    {"role": "user", "content": """请用 Python 写一个简单的爬虫程序，爬取豆瓣电影 Top250 的电影名称和评分。
要求：
1. 使用 requests 库
2. 处理分页
3. 数据保存到 JSON 文件
4. 添加详细注释"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 多轮对话

```python
# 中文多轮对话
messages = [
    {"role": "user", "content": "我想学习Python编程，应该从哪里开始？"},
    {"role": "assistant", "content": "学习Python编程可以从以下几个方面入手：1. 基础语法..."},
    {"role": "user", "content": "能推荐一些适合初学者的Python项目吗？"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

## API 端点映射

| WebAPI 端点 | 豆包端点 | 说明 |
|------------|----------|------|
| `/v1/chat/completions` | `/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions` | 聊天完成 |
| `/v1/models` | 自定义实现 | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 401 | AuthError | Access Token 无效或过期 |
| 429 | RateLimitError | 请求频率超限 |
| 400 | ValidationError | 请求参数错误 |
| 500 | ProviderError | 服务器内部错误 |

### 令牌错误处理

```python
try:
    response = await provider.chat_completion(messages)
except AuthError as e:
    if "token" in str(e):
        print("Access Token 过期，正在自动刷新...")
        # Provider 会自动处理令牌刷新
        response = await provider.chat_completion(messages)
    else:
        raise e
```

### 百度云 API 错误

```python
try:
    response = await provider.chat_completion(messages)
except ProviderError as e:
    if "baidu" in str(e):
        print("百度云 API 错误，请检查 API Key 和 Secret Key")
        # 检查配置
    else:
        raise e
```

## 性能优化

### 1. 模型选择策略

```python
def select_doubao_model(task_complexity):
    """根据任务复杂度选择模型"""
    if task_complexity == "simple":
        return "doubao-turbo"  # 简单任务使用极速版
    elif task_complexity == "medium":
        return "doubao-lite"   # 中等任务使用轻量版
    else:
        return "doubao-pro"    # 复杂任务使用专业版
```

### 2. 请求批处理

```python
async def batch_doubao_requests(requests):
    """批量处理豆包请求"""
    results = []
    for req in requests:
        response = await provider.chat_completion(
            req['messages'], 
            model=req.get('model', 'doubao-pro')
        )
        results.append(response)
    return results
```

### 3. 缓存机制

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=500)
def cached_doubao_response(messages_hash, model):
    """缓存豆包响应"""
    # 解析 messages_hash 获取原始消息
    messages = parse_messages_hash(messages_hash)
    return provider.chat_completion(messages, model=model)

def hash_messages(messages):
    """生成消息哈希"""
    messages_str = json.dumps(messages, sort_keys=True)
    return hashlib.md5(messages_str.encode()).hexdigest()
```

## 故障排除

### 1. Access Token 问题

```python
def troubleshoot_doubao_auth():
    """排查豆包认证问题"""
    try:
        # 测试获取 Access Token
        token = await provider.get_access_token()
        print(f"Access Token 获取成功: {token[:20]}...")
        return True
    except Exception as e:
        print(f"Access Token 获取失败: {e}")
        return False
```

### 2. 网络连接问题

```python
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def doubao_request_with_retry(messages):
    """带重试的豆包请求"""
    try:
        return await provider.chat_completion(messages)
    except aiohttp.ClientError as e:
        print(f"网络连接失败: {e}")
        raise
```

### 3. 速率限制处理

```python
class DoubaoRateLimiter:
    def __init__(self, max_requests=60, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    async def wait_if_needed(self):
        """如果需要则等待"""
        import datetime
        now = datetime.datetime.now()
        
        # 清理过期的请求记录
        self.requests = [
            req_time for req_time in self.requests 
            if (now - req_time).total_seconds() < self.time_window
        ]
        
        # 如果达到限制，等待
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0]).total_seconds()
            await asyncio.sleep(sleep_time)
        
        self.requests.append(now)
```

## 最佳实践

### 1. 中文内容优化

```python
def optimize_chinese_content(content, style="formal"):
    """优化中文内容风格"""
    if style == "formal":
        # 正式风格优化
        optimized = content.replace("啥", "什么")
        optimized = optimized.replace("咋", "怎么")
    elif style == "casual":
        # 休闲风格优化
        optimized = content.replace("什么", "啥")
        optimized = optimized.replace("怎么", "咋")
    else:
        optimized = content
    
    return optimized
```

### 2. 会话管理

```python
class DoubaoSession:
    def __init__(self, model="doubao-pro"):
        self.model = model
        self.messages = []
        self.max_history = 20  # 最大历史消息数
    
    def add_message(self, role, content):
        """添加消息到会话"""
        self.messages.append({"role": role, "content": content})
        
        # 限制历史消息数量
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    async def get_response(self, system_content=None):
        """获取回复"""
        messages = self.messages.copy()
        if system_content:
            messages.insert(0, {"role": "system", "content": system_content})
        
        response = await provider.chat_completion(messages, model=self.model)
        self.add_message("assistant", response['choices'][0]['message']['content'])
        return response
```

### 3. 内容安全检查

```python
def check_doubao_content_safety(content):
    """检查豆包内容安全性"""
    # 中文敏感词列表
    sensitive_keywords = [
        "暴力", "色情", "赌博", "毒品", "政治敏感词",
        "违法", "犯罪", "恐怖", "极端"
    ]
    
    content_lower = content.lower()
    for keyword in sensitive_keywords:
        if keyword in content_lower:
            return False, f"包含敏感词: {keyword}"
    
    return True, "内容安全"
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 doubao-pro, doubao-lite, doubao-turbo 模型
- 实现百度云 API 认证
- 支持自动令牌刷新

### v1.1.0
- 添加中文优化特性
- 增强错误处理机制
- 实现智能模型选择

### v1.2.0
- 支持流式响应
- 添加批处理功能
- 实现内容安全检查

## 相关链接

- [豆包官方文档](https://cloud.baidu.com/product/wenxinworkshop)
- [百度千帆大模型平台](https://cloud.baidu.com/product/qianfan)
- [百度云 API 文档](https://cloud.baidu.com/doc/WENXINWORKSHOP/s/6ltmwyh8r)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)