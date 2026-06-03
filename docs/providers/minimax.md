# MiniMax Provider

## 概述

MiniMax Provider 是 WebAPI 对接 MiniMax 大语言模型服务的适配器。MiniMax 是一家专注于大语言模型研发的中国 AI 公司，提供多个针对不同场景优化的模型。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| minimax-abab6 | MiniMax 对话模型 | 128K | 强大的中文理解能力 |
| minimax-abab6-chat | MiniMax 聊天模型 | 32K | 专门优化对话场景 |
| minimax-text-01 | MiniMax 文本模型 | 32K | 通用文本处理 |
| minimab-code-01 | MiniMax 代码模型 | 16K | 专业的代码生成 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  minimax:
    enabled: true
    api_key: "${MINIMAX_API_KEY}"  # 从环境变量读取
    group_id: "${MINIMAX_GROUP_ID}"  # MiniMax Group ID
    api_base: "https://api.minimax.chat"
    timeout: 30
    max_retries: 3
    use_signature_auth: true  # 使用签名认证
```

### 环境变量

```bash
export MINIMAX_API_KEY="your-minimax-api-key"
export MINIMAX_GROUP_ID="your-minimax-group-id"
```

## 认证方式

MiniMax 使用 API Key + Group ID 的认证方式，Provider 会自动生成请求签名：

### 1. API Key + Group ID 认证

```python
# 自动生成签名
response = await provider.chat_completion(messages)
```

### 2. 请求签名

Provider 会自动生成请求签名，确保请求的安全性：

```http
Authorization: Bearer your-api-key
X-GroupId: your-group-id
X-Timestamp: timestamp
X-Signature: generated-signature
```

## 特殊功能

### 1. 多轮对话优化

MiniMax 针对多轮对话进行了特别优化：

```python
# 多轮对话
messages = [
    {"role": "system", "content": "你是一个专业的助手。"},
    {"role": "user", "content": "我想学习机器学习。"},
    {"role": "assistant", "content": "机器学习是人工智能的一个重要分支..."},
    {"role": "user", "content": "能推荐一些入门书籍吗？"}
]

response = await provider.chat_completion(messages)
```

### 2. 上下文管理

Provider 自动管理对话上下文，避免上下文溢出：

```python
# 自动上下文管理
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

# 获取 MiniMax Provider
provider = get_provider("minimax-abab6")

messages = [
    {"role": "system", "content": "你是一个专业的助手。"},
    {"role": "user", "content": "请介绍一下人工智能的发展历史。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 代码生成

```python
# 使用 minimax-code-01 生成代码
provider = get_provider("minimax-code-01")

messages = [
    {"role": "user", "content": """请用 Python 写一个简单的 Web 应用，要求：
1. 使用 Flask 框架
2. 实现用户注册和登录
3. 包含基本的 CRUD 操作
4. 添加详细的注释"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 创意写作

```python
# 使用 minimax-text-01 进行创意写作
provider = get_provider("minimax-text-01")

messages = [
    {"role": "user", "content": """请写一个关于未来城市的科幻故事，要求：
1. 不少于2000字
2. 包含科技元素和人文关怀
3. 有完整的情节发展
4. 结尾发人深省"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 多轮技术问答

```python
# 技术多轮对话
messages = [
    {"role": "user", "content": "什么是深度学习？"},
    {"role": "assistant", "content": "深度学习是机器学习的一个分支，使用神经网络..."},
    {"role": "user", "content": "能详细解释一下神经网络的结构吗？"},
    {"role": "assistant", "content": "神经网络由输入层、隐藏层和输出层组成..."},
    {"role": "user", "content": "反向传播算法是如何工作的？"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

## API 端点映射

| WebAPI 端点 | MiniMax 端点 | 说明 |
|------------|-------------|------|
| `/v1/chat/completions` | `/v1/text/chatcompletion` | 聊天完成 |
| `/v1/models` | `/v1/models` | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 401 | AuthError | API Key 或 Group ID 无效 |
| 429 | RateLimitError | 请求频率超限 |
| 400 | ValidationError | 请求参数错误 |
| 500 | ProviderError | 服务器内部错误 |

### 签名错误处理

```python
try:
    response = await provider.chat_completion(messages)
except AuthError as e:
    if "signature" in str(e):
        print("请求签名失败，正在重新生成签名...")
        # Provider 会自动重新生成签名
        response = await provider.chat_completion(messages)
    else:
        raise e
```

### 上下文溢出错误

```python
try:
    response = await provider.chat_completion(messages)
except ValidationError as e:
    if "context" in str(e):
        print("上下文溢出，正在截断历史消息...")
        # Provider 会自动处理上下文截断
        response = await provider.chat_completion(messages)
    else:
        raise e
```

## 性能优化

### 1. 模型选择策略

```python
def select_minimax_model(task_type, complexity="medium"):
    """根据任务类型和复杂度选择模型"""
    model_mapping = {
        "chat": {
            "simple": "minimax-abab6-chat",
            "medium": "minimax-abab6-chat",
            "complex": "minimax-abab6"
        },
        "code": {
            "simple": "minimax-code-01",
            "medium": "minimax-code-01",
            "complex": "minimax-code-01"
        },
        "text": {
            "simple": "minimax-text-01",
            "medium": "minimax-text-01",
            "complex": "minimax-text-01"
        }
    }
    
    return model_mapping.get(task_type, {}).get(complexity, "minimax-abab6")
```

### 2. 上下文压缩

```python
class ContextManager:
    def __init__(self, max_tokens=32000):
        self.max_tokens = max_tokens
        self.compression_threshold = int(max_tokens * 0.8)
    
    def compress_context(self, messages):
        """压缩上下文以避免溢出"""
        total_tokens = self._count_tokens(messages)
        
        if total_tokens > self.compression_threshold:
            # 实现上下文压缩逻辑
            compressed_messages = self._compress_messages(messages)
            return compressed_messages
        
        return messages
    
    def _count_tokens(self, messages):
        """计算消息的 token 数量"""
        # 简单的 token 计算逻辑
        return sum(len(msg.get('content', '')) for msg in messages)
    
    def _compress_messages(self, messages):
        """压缩消息历史"""
        # 保留最近的对话，压缩早期的对话
        if len(messages) <= 10:
            return messages
        
        # 保留最后 5 条对话
        recent_messages = messages[-5:]
        
        # 压缩更早的对话为摘要
        earlier_messages = messages[:-5]
        summary = self._summarize_messages(earlier_messages)
        
        return [summary] + recent_messages
    
    def _summarize_messages(self, messages):
        """消息摘要"""
        # 实现消息摘要逻辑
        return {
            "role": "system",
            "content": f"之前的对话摘要：{len(messages)}条消息"
        }
```

### 3. 批处理请求

```python
async def batch_minimax_requests(requests):
    """批量处理 MiniMax 请求"""
    results = []
    
    for req in requests:
        try:
            response = await provider.chat_completion(
                req['messages'],
                model=req.get('model', 'minimax-abab6'),
                temperature=req.get('temperature', 0.7)
            )
            results.append(response)
        except Exception as e:
            print(f"请求失败: {e}")
            results.append(None)
    
    return results
```

## 故障排除

### 1. 签名认证问题

```python
def troubleshoot_minimax_auth():
    """排查 MiniMax 认证问题"""
    try:
        # 测试基本请求
        test_messages = [{"role": "user", "content": "测试连接"}]
        response = await provider.chat_completion(test_messages)
        print("认证成功")
        return True
    except Exception as e:
        print(f"认证失败: {e}")
        return False
```

### 2. 上下文管理问题

```python
def optimize_context_management(messages, max_tokens=32000):
    """优化上下文管理"""
    context_manager = ContextManager(max_tokens)
    
    # 检查上下文长度
    if context_manager._count_tokens(messages) > max_tokens:
        print("上下文过长，正在压缩...")
        compressed_messages = context_manager.compress_context(messages)
        return compressed_messages
    
    return messages
```

### 3. 速率限制处理

```python
import asyncio
from datetime import datetime, timedelta

class MiniMaxRateLimiter:
    def __init__(self, max_requests=60, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self.lock = asyncio.Lock()
    
    async def wait_if_needed(self):
        """如果需要则等待"""
        async with self.lock:
            now = datetime.now()
            
            # 清理过期的请求记录
            self.requests = [
                req_time for req_time in self.requests 
                if (now - req_time).total_seconds() < self.time_window
            ]
            
            # 如果达到限制，等待
            if len(self.requests) >= self.max_requests:
                oldest_request = self.requests[0]
                sleep_time = self.time_window - (now - oldest_request).total_seconds()
                await asyncio.sleep(sleep_time)
            
            self.requests.append(now)
```

## 最佳实践

### 1. 会话管理

```python
class MiniMaxSession:
    def __init__(self, model="minimax-abab6", max_history=20):
        self.model = model
        self.max_history = max_history
        self.messages = []
        self.context_manager = ContextManager()
    
    def add_message(self, role, content):
        """添加消息到会话"""
        self.messages.append({"role": role, "content": content})
        
        # 限制历史消息数量
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
        
        # 检查上下文长度
        if self.context_manager._count_tokens(self.messages) > self.context_manager.max_tokens:
            self.messages = self.context_manager.compress_context(self.messages)
    
    async def get_response(self, system_content=None):
        """获取回复"""
        messages = self.messages.copy()
        if system_content:
            messages.insert(0, {"role": "system", "content": system_content})
        
        response = await provider.chat_completion(messages, model=self.model)
        self.add_message("assistant", response['choices'][0]['message']['content'])
        return response
```

### 2. 工具调用管理

```python
class MiniMaxToolManager:
    def __init__(self):
        self.tools = {}
    
    def register_tool(self, name, func, description):
        """注册工具"""
        self.tools[name] = {
            'function': func,
            'description': description
        }
    
    async def execute_tool_call(self, tool_name, parameters):
        """执行工具调用"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        tool_info = self.tools[tool_name]
        return await tool_info['function'](**parameters)
    
    def get_tools_schema(self):
        """获取工具模式定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info['description'],
                    "parameters": self._get_function_parameters(info['function'])
                }
            }
            for name, info in self.tools.items()
        ]
    
    def _get_function_parameters(self, func):
        """获取函数参数定义"""
        import inspect
        sig = inspect.signature(func)
        parameters = {}
        
        for name, param in sig.parameters.items():
            if param.default == inspect.Parameter.empty:
                parameters[name] = {"type": "string", "required": True}
            else:
                parameters[name] = {"type": "string", "required": False}
        
        return parameters
```

### 3. 内容质量检查

```python
def check_minimax_content_quality(content):
    """检查 MiniMax 内容质量"""
    quality_metrics = {
        "length": len(content),
        "coherence": self._check_coherence(content),
        "relevance": self._check_relevance(content),
        "completeness": self._check_completeness(content)
    }
    
    overall_score = sum(quality_metrics.values()) / len(quality_metrics)
    
    return {
        "quality_score": overall_score,
        "metrics": quality_metrics,
        "feedback": self._generate_quality_feedback(quality_metrics)
    }
    
def _check_coherence(self, content):
    """检查内容连贯性"""
    # 简单的连贯性检查
    sentences = content.split('。')
    if len(sentences) < 2:
        return 0.5
    
    # 检查句子之间的逻辑连接
    coherence_score = 0.7  # 简化的评分
    return min(1.0, coherence_score)
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 minimax-abab6, minimax-abab6-chat, minimax-text-01, minimax-code-01 模型
- 实现签名认证
- 支持多轮对话优化

### v1.1.0
- 添加上下文管理功能
- 增强错误处理机制
- 实现智能模型选择

### v1.2.0
- 支持流式响应
- 添加批处理功能
- 实现内容质量检查

## 相关链接

- [MiniMax 官方文档](https://api.minimax.chat/)
- [MiniMax 开发者平台](https://platform.minimax.chat/)
- [MiniMax API 参考](https://platform.minimax.chat/api-docs)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)