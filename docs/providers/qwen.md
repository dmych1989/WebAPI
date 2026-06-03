# Qwen Provider

## 概述

Qwen Provider 是 WebAPI 对接通义千问（Qwen）大语言模型服务的适配器。Qwen 是阿里巴巴达摩院开发的大语言模型系列，包括多个针对不同场景优化的模型。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| qwen-max | Qwen 最大模型 | 128K | 最强性能，支持多模态 |
| qwen-turbo | Qwen 快速模型 | 32K | 速度快，成本低 |
| qwen-plus | Qwen 增强模型 | 32K | 性能与速度平衡 |
| qwen-vl | Qwen 视觉模型 | 32K | 支持图像理解 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  qwen:
    enabled: true
    api_base: "https://dashscope.aliyuncs.com"
    api_key: "${QWEN_API_KEY}"  # 从环境变量读取
    timeout: 30
    max_retries: 3
    use_cookie_auth: true  # 使用 Cookie 认证
```

### 环境变量

```bash
export QWEN_API_KEY="your-qwen-api-key"
```

## 认证方式

Qwen 使用多种认证方式，Provider 主要支持：

### 1. API Key 认证

```http
Authorization: Bearer your-api-key
```

### 2. Cookie 认证（推荐）

```http
Cookie: your-cookie-value
```

## 特殊功能

### 1. 多模态支持

Qwen 支持文本和图像输入：

```python
# 支持图像输入
messages = [
    {"role": "user", "content": [
        {"type": "text", "text": "请描述这张图片"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
    ]}
]

response = await provider.chat_completion(messages)
```

### 2. 工具调用

支持函数调用能力：

```python
# 定义工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名称"}
                }
            }
        }
    }
]

messages = [
    {"role": "user", "content": "北京今天天气怎么样？"}
]

response = await provider.chat_completion(messages, tools=tools)
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

# 获取 Qwen Provider
provider = get_provider("qwen-max")

messages = [
    {"role": "system", "content": "你是一个专业的助手。"},
    {"role": "user", "content": "请解释一下什么是云计算。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 图像理解

```python
# 使用 qwen-vl 模型进行图像理解
provider = get_provider("qwen-vl")

messages = [
    {
        "role": "user", 
        "content": [
            {"type": "text", "text": "请分析这张图片的内容"},
            {
                "type": "image_url", 
                "image_url": {
                    "url": "https://example.com/chart.png"
                }
            }
        ]
    }
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 代码生成

```python
# 使用 qwen-turbo 快速生成代码
provider = get_provider("qwen-turbo")

messages = [
    {"role": "user", "content": """请用 Python 写一个爬虫程序，爬取知乎的热门话题。
要求：
1. 使用 requests 库
2. 处理反爬机制
3. 数据保存到 CSV
4. 添加适当的注释"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 多轮对话

```python
# 多轮对话示例
messages = [
    {"role": "user", "content": "我想学习机器学习，应该从哪里开始？"},
    {"role": "assistant", "content": "机器学习的学习路径可以分为以下几个步骤：1. 数学基础..."},
    {"role": "user", "content": "能详细讲讲线性回归吗？"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

## API 端点映射

| WebAPI 端点 | Qwen 端点 | 说明 |
|------------|----------|------|
| `/v1/chat/completions` | `/api/v1/services/aigc/text-generation/generation` | 聊天完成 |
| `/v1/models` | `/api/v1/model/list` | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 401 | AuthError | API Key 无效或过期 |
| 429 | RateLimitError | 请求频率超限 |
| 400 | ValidationError | 请求参数错误 |
| 500 | ProviderError | 服务器内部错误 |

### 认证错误处理

```python
try:
    response = await provider.chat_completion(messages)
except AuthError as e:
    if "cookie" in str(e):
        print("Cookie 认证失败，尝试重新获取")
        # 可以在这里实现 Cookie 刷新逻辑
    else:
        raise e
```

### 多模态错误处理

```python
try:
    response = await provider.chat_completion(messages)
except ValidationError as e:
    if "image" in str(e):
        print("图像处理失败，检查图像格式和大小")
        # 验证图像格式、大小等
    else:
        raise e
```

## 性能优化

### 1. 模型选择

根据场景选择合适的模型：

```python
def select_model_by_task(task_type):
    """根据任务类型选择模型"""
    if task_type == "code":
        return "qwen-turbo"  # 代码生成使用快速模型
    elif task_type == "analysis":
        return "qwen-plus"   # 分析任务使用增强模型
    elif task_type == "creative":
        return "qwen-max"    # 创意任务使用最大模型
    else:
        return "qwen-turbo"
```

### 2. 批处理请求

```python
async def batch_chat_completion(requests):
    """批量处理多个请求"""
    tasks = []
    for req in requests:
        task = provider.chat_completion(req['messages'], model=req['model'])
        tasks.append(task)
    
    return await asyncio.gather(*tasks)
```

### 3. 缓存机制

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_embedding(text):
    """缓存文本嵌入结果"""
    return provider.create_embedding(text)
```

## 故障排除

### 1. Cookie 认证问题

如果 Cookie 认证失败：

```python
# 重新获取 Cookie
def refresh_qwen_cookie():
    """刷新 Qwen Cookie"""
    # 实现登录逻辑获取新的 Cookie
    pass
```

### 2. 图像处理问题

```python
def validate_image(image_url):
    """验证图像格式和大小"""
    # 检查图像 URL 格式
    # 检查图像大小限制
    # 检查支持的图像格式
    pass
```

### 3. 速率限制

```python
import asyncio
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, max_requests=60, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    async def wait_if_needed(self):
        """如果需要则等待"""
        now = datetime.now()
        # 清理过期的请求记录
        self.requests = [req for req in self.requests if now - req < timedelta(seconds=self.time_window)]
        
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0]).total_seconds()
            await asyncio.sleep(sleep_time)
        
        self.requests.append(now)
```

## 最佳实践

### 1. 会话管理

```python
class QwenSession:
    def __init__(self, model="qwen-max"):
        self.model = model
        self.messages = []
    
    def add_message(self, role, content):
        """添加消息到会话"""
        self.messages.append({"role": role, "content": content})
    
    async def get_response(self):
        """获取回复"""
        response = await provider.chat_completion(self.messages, model=self.model)
        self.add_message("assistant", response['choices'][0]['message']['content'])
        return response
```

### 2. 工具调用管理

```python
class QwenToolManager:
    def __init__(self):
        self.tools = []
    
    def add_tool(self, tool):
        """添加工具"""
        self.tools.append(tool)
    
    async def execute_tool_call(self, tool_call):
        """执行工具调用"""
        tool_name = tool_call['name']
        tool_params = tool_call['parameters']
        
        # 根据工具名称执行相应的函数
        if tool_name == "get_weather":
            return await self.get_weather(tool_params['location'])
        elif tool_name == "calculate":
            return await self.calculate(tool_params)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
```

### 3. 内容安全检查

```python
def check_content_safety(content):
    """检查内容安全性"""
    # 实现内容安全检查逻辑
    sensitive_keywords = ["暴力", "色情", "政治敏感词"]
    
    for keyword in sensitive_keywords:
        if keyword in content:
            return False, f"包含敏感词: {keyword}"
    
    return True, "内容安全"
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 qwen-max, qwen-turbo, qwen-plus, qwen-vl 模型
- 实现 Cookie 认证
- 支持多模态输入

### v1.1.0
- 添加工具调用支持
- 优化性能和错误处理
- 增强内容安全检查

### v1.2.0
- 支持流式响应
- 添加批处理功能
- 实现智能模型选择

## 相关链接

- [Qwen 官方文档](https://qwen.aliyun.com/)
- [通义千问 API 参考](https://help.aliyun.com/zh/dashscope/)
- [达摩院官网](https://damo.alibaba.com/)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)