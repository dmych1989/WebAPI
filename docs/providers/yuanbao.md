# Yuanbao Provider

## 概述

Yuanbao Provider 是 WebAPI 对接元宝（Yuanbao）大语言模型服务的适配器。元宝是由小冰公司开发的大语言模型，专注于创意内容生成和对话交互。

## 支持的模型

| 模型名称 | 描述 | 最大 Token | 特点 |
|---------|------|-----------|------|
| yuanbao-chat | 元宝对话模型 | 32K | 创意能力强，对话自然 |
| yuanbao-creative | 元宝创意模型 | 64K | 专门优化创意写作 |
| yuanbao-code | 元宝代码模型 | 16K | 专业的代码生成能力 |

## 配置

### 在 config.yaml 中配置

```yaml
providers:
  yuanbao:
    enabled: true
    api_base: "https://api.xiaobing.net"
    api_key: "${YUANBAO_API_KEY}"  # 从环境变量读取
    timeout: 30
    max_retries: 3
    use_session_auth: true  # 使用会话认证
```

### 环境变量

```bash
export YUANBAO_API_KEY="your-yuanbao-api-key"
```

## 认证方式

元宝使用会话认证方式，Provider 会自动管理会话状态：

### 1. API Key 认证

```http
Authorization: Bearer your-api-key
```

### 2. 会话管理

Provider 会自动维护会话状态，支持多轮对话：

```python
# 自动会话管理
response = await provider.chat_completion(messages)
```

## 特殊功能

### 1. 创意内容生成

元宝在创意内容生成方面表现优异：

```python
# 创意写作
messages = [
    {"role": "system", "content": "你是一个专业的创意写作助手。"},
    {"role": "user", "content": "请写一个关于人工智能的科幻短篇故事。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 2. 对话风格多样化

支持多种对话风格：

```python
# 不同风格的对话
styles = {
    "professional": "专业正式的对话风格",
    "casual": "轻松随意的对话风格",
    "creative": "富有创意的对话风格",
    "educational": "教育引导的对话风格"
}

messages = [
    {"role": "system", "content": styles["creative"]},
    {"role": "user", "content": "请用有趣的方式解释量子力学。"}
]
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

# 获取元宝 Provider
provider = get_provider("yuanbao-chat")

messages = [
    {"role": "system", "content": "你是一个友好的 AI 助手。"},
    {"role": "user", "content": "你好，请介绍一下你自己。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 创意写作

```python
# 使用 yuanbao-creative 进行创意写作
provider = get_provider("yuanbao-creative")

messages = [
    {"role": "user", "content": """请创作一首关于春天的现代诗，要求：
1. 不少于12行
2. 包含具体的意象
3. 有情感表达
4. 语言优美"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 代码生成

```python
# 使用 yuanbao-code 生成代码
provider = get_provider("yuanbao-code")

messages = [
    {"role": "user", "content": """请用 Python 写一个简单的游戏程序，要求：
1. 实现一个贪吃蛇游戏
2. 使用 Pygame 库
3. 包含基本的游戏逻辑
4. 添加注释说明"""}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

### 多轮创意对话

```python
# 创意多轮对话
messages = [
    {"role": "user", "content": "我想写一个关于时间旅行的故事，有什么好的创意吗？"},
    {"role": "assistant", "content": "时间旅行故事可以从以下几个角度切入：1. 平行宇宙..."},
    {"role": "user", "content": "能详细展开一下平行宇宙这个角度吗？我想写一个温馨的故事。"}
]

response = await provider.chat_completion(messages)
print(response['choices'][0]['message']['content'])
```

## API 端点映射

| WebAPI 端点 | 元宝端点 | 说明 |
|------------|----------|------|
| `/v1/chat/completions` | `/api/v1/chat/completions` | 聊天完成 |
| `/v1/models` | `/api/v1/models` | 模型列表 |

## 错误处理

### 常见错误代码

| HTTP 状态码 | 错错类型 | 说明 |
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

### 创意内容错误

```python
try:
    response = await provider.chat_completion(messages)
except ValidationError as e:
    if "creative" in str(e):
        print("创意内容生成失败，尝试调整提示词")
        # 可以调整提示词或使用不同的模型
    else:
        raise e
```

## 性能优化

### 1. 模型选择策略

```python
def select_yuanbao_model(task_type):
    """根据任务类型选择元宝模型"""
    if task_type == "code":
        return "yuanbao-code"      # 代码任务使用代码模型
    elif task_type == "creative":
        return "yuanbao-creative"   # 创意任务使用创意模型
    else:
        return "yuanbao-chat"       # 其他任务使用对话模型
```

### 2. 会话复用

```python
class YuanbaoSessionManager:
    def __init__(self):
        self.sessions = {}
    
    def get_session(self, user_id, model="yuanbao-chat"):
        """获取用户会话"""
        if user_id not in self.sessions:
            self.sessions[user_id] = {
                'model': model,
                'messages': [],
                'created_at': time.time()
            }
        return self.sessions[user_id]
    
    async def chat(self, user_id, messages):
        """使用会话进行对话"""
        session = self.get_session(user_id)
        session['messages'].extend(messages)
        
        response = await provider.chat_completion(
            session['messages'], 
            model=session['model']
        )
        
        # 更新会话消息
        session['messages'].append({
            'role': 'assistant',
            'content': response['choices'][0]['message']['content']
        })
        
        return response
```

### 3. 缓存机制

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_creative_response(prompt_hash, style):
    """缓存创意响应"""
    # 根据提示词哈希和风格获取缓存
    pass

def hash_prompt_with_style(messages, style):
    """生成带风格的提示词哈希"""
    import hashlib
    prompt_data = {
        'messages': messages,
        'style': style
    }
    prompt_str = json.dumps(prompt_data, sort_keys=True)
    return hashlib.md5(prompt_str.encode()).hexdigest()
```

## 故障排除

### 1. 会话管理问题

```python
def troubleshoot_yuanbao_sessions():
    """排查元宝会话问题"""
    try:
        # 测试会话建立
        test_messages = [{"role": "user", "content": "测试连接"}]
        response = await provider.chat_completion(test_messages)
        print("会话建立成功")
        return True
    except Exception as e:
        print(f"会话建立失败: {e}")
        return False
```

### 2. 创意内容生成问题

```python
def optimize_creative_prompt(prompt, style="default"):
    """优化创意提示词"""
    if style == "story":
        # 故事创作优化
        optimized = f"请创作一个{prompt}，要求情节生动有趣，人物形象鲜明。"
    elif style == "poem":
        # 诗歌创作优化
        optimized = f"请创作一首关于{prompt}的诗歌，要求语言优美，意境深远。"
    else:
        optimized = prompt
    
    return optimized
```

### 3. 速率限制处理

```python
import asyncio
from datetime import datetime, timedelta

class YuanbaoRateLimiter:
    def __init__(self, max_requests=30, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    async def wait_if_needed(self):
        """如果需要则等待"""
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

### 1. 创意内容生成

```python
class CreativeContentGenerator:
    def __init__(self, model="yuanbao-creative"):
        self.model = model
    
    async def generate_story(self, theme, length="medium", style="modern"):
        """生成故事"""
        prompt = self._build_story_prompt(theme, length, style)
        messages = [{"role": "user", "content": prompt}]
        
        response = await provider.chat_completion(messages, model=self.model)
        return response['choices'][0]['message']['content']
    
    def _build_story_prompt(self, theme, length, style):
        """构建故事提示词"""
        length_desc = {
            "short": "短篇故事（500-1000字）",
            "medium": "中篇故事（1000-3000字）",
            "long": "长篇故事（3000字以上）"
        }
        
        style_desc = {
            "modern": "现代风格",
            "fantasy": "奇幻风格",
            "scifi": "科幻风格",
            "romance": "浪漫风格"
        }
        
        return f"""请创作一个{style_desc[style]}的{length_desc[length]}，主题是：{theme}
要求：
1. 情节完整，有起承转合
2. 人物形象鲜明
3. 语言生动有趣
4. 传递积极价值观"""
```

### 2. 对话风格管理

```python
class DialogueStyleManager:
    def __init__(self):
        self.styles = {
            "professional": {
                "system": "你是一个专业的AI助手，回答要专业、准确、有条理。",
                "temperature": 0.3
            },
            "casual": {
                "system": "你是一个友好的AI助手，回答要轻松、自然、亲切。",
                "temperature": 0.8
            },
            "creative": {
                "system": "你是一个富有创意的AI助手，回答要富有想象力、生动有趣。",
                "temperature": 0.9
            }
        }
    
    def get_style_config(self, style_name):
        """获取风格配置"""
        return self.styles.get(style_name, self.styles["professional"])
    
    async def chat_with_style(self, style_name, messages):
        """使用指定风格进行对话"""
        style_config = self.get_style_config(style_name)
        
        # 添加系统提示
        system_message = {"role": "system", "content": style_config["system"]}
        styled_messages = [system_message] + messages
        
        response = await provider.chat_completion(
            styled_messages,
            temperature=style_config["temperature"]
        )
        
        return response
```

### 3. 内容质量评估

```python
def evaluate_content_quality(content, content_type="text"):
    """评估内容质量"""
    quality_metrics = {
        "length": len(content),
        "readability": self._calculate_readability(content),
        "coherence": self._check_coherence(content),
        "creativity": self._assess_creativity(content)
    }
    
    overall_score = sum(quality_metrics.values()) / len(quality_metrics)
    return {
        "score": overall_score,
        "metrics": quality_metrics,
        "feedback": self._generate_feedback(quality_metrics)
    }
    
def _calculate_readability(self, text):
    """计算可读性分数"""
    # 简单的句子长度和复杂度分析
    sentences = text.split('。')
    avg_sentence_length = sum(len(s) for s in sentences) / len(sentences)
    return max(0, 10 - avg_sentence_length / 20)  # 简单的线性评分
```

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 yuanbao-chat, yuanbao-creative, yuanbao-code 模型
- 实现会话认证
- 支持创意内容生成

### v1.1.0
- 添加多种对话风格支持
- 增强会话管理功能
- 实现内容质量评估

### v1.2.0
- 支持流式响应
- 添加创意提示词优化
- 实现智能模型选择

## 相关链接

- [元宝官方文档](https://xiaobing.net/)
- [小冰公司官网](https://www.xiaobing.com/)
- [元宝 API 参考](https://api.xiaobing.net/docs)
- [WebAPI 项目主页](https://github.com/your-repo/webapi)