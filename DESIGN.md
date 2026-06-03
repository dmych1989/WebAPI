# WebAPI — 网页版大模型对话转本地 API 调用

> 开发设计文档 v1.0 | 2026-06-01

---

## 一、项目概述

### 1.1 项目目标

将各大 AI 厂商的**网页版对话服务**（Web UI）转换为**本地 OpenAI 兼容 API**，使任何支持 OpenAI API 的客户端工具（Cherry Studio、NextChat、Cline、Roo Code 等）都能免费调用这些模型。

### 1.2 核心理念

> 不依赖官方 API Key，而是模拟用户在浏览器中的操作，将网页版对话能力暴露为标准 API。

### 1.3 参考项目

本项目借鉴了两个成熟项目的架构设计：

| 项目               | 技术栈                         | 核心特征                                             |
| ---------------- | --------------------------- | ------------------------------------------------ |
| **Chat2API**     | Electron + React + Koa + TS | 桌面端，Provider Adapter 模式，多账号负载均衡，Prompt 工程实现工具调用  |
| **AIClient2API** | Node.js + Express + Docker  | 服务端，协议转换（OpenAI/Claude/Gemini），账号池+健康检查，TLS 指纹绕过 |

本项目取其精华，采用 **Python** 生态构建，发挥 Python 在 Web 自动化、HTTP 抓取、流式处理方面的优势。

---

## 二、技术选型

### 2.1 语言与运行时

| 选项                 | 优势                                                                             | 劣势                   |
| ------------------ | ------------------------------------------------------------------------------ | -------------------- |
| **Python 3.11+ ✅** | 最强的 Web 自动化生态（Playwright/DrissionPage）；异步 I/O 成熟（asyncio/aiohttp）；AI/LLM 工具链丰富 | GIL 限制多线程（可用多进程绕过）   |
| Node.js            | 两个参考项目都用它；事件驱动天然适合流式代理                                                         | 浏览器自动化不如 Python 生态丰富 |
| Go                 | 性能最好；TLS sidecar 专用                                                            | 生态贫瘠，不适合快速迭代         |

**选择：Python 3.11+**，理由：

- Playwright/DrissionPage（浏览器操控）→ Python 一等公民
- aiohttp + asyncio → 高并发代理服务器
- sse-starlette → SSE 流式输出
- litellm/openai SDK → 标准协议转换

### 2.2 核心依赖

| 依赖                | 版本     | 用途                     |
| ----------------- | ------ | ---------------------- |
| **playwright**    | 1.48+  | 浏览器自动化，驱动网页版对话         |
| **aiohttp**       | 3.10+  | 异步 HTTP 客户端（反向 API 模式） |
| **fastapi**       | 0.115+ | 高性能异步 HTTP 服务器         |
| **uvicorn**       | 0.30+  | ASGI 服务器               |
| **pydantic**      | 2.9+   | 数据模型/配置验证              |
| **sse-starlette** | 2.0+   | 服务端 SSE 流式响应           |
| **httpx**         | 0.27+  | 异步 HTTP 客户端（支持 HTTP/2） |
| **redis** (可选)    | 7+     | 会话缓存、账号池状态共享           |
| **loguru**        | 0.7+   | 结构化日志                  |

### 2.3 Python 版本

```
Python >= 3.11（利用 asyncio 最新特性、更好的错误信息）
```

---

## 三、项目架构

### 3.1 总体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenAI Compatible API                     │
│              /v1/chat/completions  /v1/models                │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    Proxy Server (FastAPI)                     │
│  • API Key 鉴权                                               │
│  • 请求路由 & 模型映射                                        │
│  • 流式/非流式响应统一封装                                     │
│  • 请求日志 & 统计                                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                  Provider Dispatcher                          │
│  • Provider 匹配（按模型名）                                   │
│  • 账号池轮询 / 负载均衡                                      │
│  • 健康检查 & 故障转移                                        │
│  • Fallback 链路                                             │
└───────┬──────────────┬──────────────┬────────────────────────┘
        │              │              │
┌───────▼───┐  ┌───────▼───┐  ┌──────▼────┐
│ DeepSeek  │  │  Kimi     │  │  Qwen     │  ...
│ Provider  │  │ Provider  │  │ Provider  │
└───────┬───┘  └───────┬───┘  └──────┬────┘
        │              │              │
┌───────▼──────────────▼──────────────▼────────────────────────┐
│                    Transport Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ API Reverse  │  │  Browser     │  │  Custom Protocol │    │
│  │ (aiohttp)    │  │  (Playwright)│  │  (Provider-Spec) │    │
│  └──────────────┘  └──────────────┘  └──────────────────┘    │
│  • 抓取 Web UI 的 HTTP API                                    │
│  • 使用用户 Token/Cookie 重放请求                               │
│  • SSE 流式响应解析                                            │
│  • 浏览器自动化操控 Web UI                                      │
│  • Playwright 拦截 API 调用                                    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
WebAPI/
├── DESIGN.md                     # 本设计文档
├── README.md                     # 项目说明
├── pyproject.toml                # Python 项目配置
├── requirements.txt              # 依赖清单
├── config/
│   ├── config.yaml               # 主配置文件
│   ├── providers.yaml            # Provider 定义
│   └── accounts.yaml             # 账号池配置（敏感信息）
├── src/
│   ├── __init__.py
│   ├── main.py                   # 入口
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py                # FastAPI 应用
│   │   ├── middleware.py         # 中间件（鉴权、日志、CORS）
│   │   ├── routes.py             # OpenAI 兼容路由
│   │   └── admin.py              # 管理 API（健康检查、配置热更新）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py             # 配置管理
│   │   ├── models.py             # 数据模型定义
│   │   ├── exceptions.py         # 自定义异常
│   │   └── logger.py             # 日志
│   ├── provider/
│   │   ├── __init__.py
│   │   ├── base.py               # Provider 抽象基类
│   │   ├── registry.py           # Provider 注册中心
│   │   ├── dispatcher.py         # Provider 调度器
│   │   ├── deepseek/             # DeepSeek
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py        # API 适配器
│   │   │   ├── stream_handler.py # 流式处理器
│   │   │   └── auth.py           # 认证（Token 提取/刷新）
│   │   ├── qwen/                 # 通义千问
│   │   ├── kimi/                 # Kimi
│   │   ├── glm/                  # 智谱清言
│   │   ├── minimax/              # MiniMax
│   │   ├── doubao/               # 豆包（字节）
│   │   ├── yuanbao/              # 腾讯元宝
│   │   └── coze/                 # Coze
│   ├── transport/
│   │   ├── __init__.py
│   │   ├── api_reverse.py        # API 反向代理（aiohttp）
│   │   ├── browser_driver.py     # Playwright 浏览器驱动
│   │   └── session_pool.py       # 会话池管理
│   ├── stream/
│   │   ├── __init__.py
│   │   ├── parser.py             # 通用 SSE 解析器
│   │   └── converter.py          # SSE → OpenAI 格式转换
│   ├── pool/
│   │   ├── __init__.py
│   │   ├── account_pool.py       # 账号池
│   │   ├── health_checker.py     # 健康检查
│   │   └── load_balancer.py      # 负载均衡策略
│   └── utils/
│       ├── __init__.py
│       ├── token_utils.py        # Token 计数
│       ├── http_utils.py         # HTTP 工具
│       └── crypto.py             # 加密凭证存储
├── tests/
│   ├── __init__.py
│   ├── test_deepseek.py
│   ├── test_kimi.py
│   └── test_proxy.py
├── docs/
│   ├── providers/
│   │   ├── deepseek.md
│   │   ├── qwen.md
│   │   └── kimi.md
│   └── api.md
├── scripts/
│   ├── capture_tokens.py         # Token 抓取工具
│   ├── start.bat                 # Windows 启动脚本
│   └── start.sh                  # Linux/macOS 启动脚本
└── examples/
    ├── chat_completion.py        # Python 调用示例
    └── openai_sdk.py             # OpenAI SDK 调用示例
```

### 3.3 模块职责

| 模块          | 职责                                  |
| ----------- | ----------------------------------- |
| `server`    | FastAPI 应用、OpenAI 兼容路由、鉴权中间件、管理 API |
| `core`      | 配置管理、数据模型（Pydantic）、异常定义、日志         |
| `provider`  | Provider 适配器基类、注册中心、调度器             |
| `transport` | 底层传输：HTTP 反向代理 + Playwright 浏览器驱动   |
| `stream`    | SSE 流式解析 + OpenAI 格式转换              |
| `pool`      | 账号池、健康检查、负载均衡                       |
| `utils`     | Token 计数、HTTP 工具、加密存储               |

---

## 四、核心设计

### 4.1 Provider Adapter 模式（最重要）

参考 Chat2API 和 AIClient2API 的 Adapter 模式，每个 Provider 实现统一接口：

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from src.core.models import ChatCompletionRequest, ChatCompletionResponse, StreamChunk


class BaseProvider(ABC):
    """Provider 抽象基类 — 所有 Provider 必须实现"""

    # Provider 元信息
    name: str                          # 如 "deepseek"、"kimi"
    display_name: str                  # 如 "DeepSeek"、"Kimi"
    auth_type: str                     # "token" | "cookie" | "oauth" | "jwt"

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        stream: bool = False
    ) -> ChatCompletionResponse:
        """非流式对话"""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式对话"""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """列出可用模型"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        ...

    # 可选实现
    async def refresh_token(self) -> bool:
        """刷新 Token（默认不实现）"""
        return False

    async def create_session(self) -> str:
        """创建对话会话（有状态 Provider 需要）"""
        return ""

    async def delete_session(self, session_id: str) -> bool:
        """删除对话会话"""
        return False
```

#### 4.1.1 Provider 注册中心

```python
class ProviderRegistry:
    """Provider 注册中心 — 管理所有 Provider"""

    _providers: dict[str, type[BaseProvider]] = {}

    @classmethod
    def register(cls, name: str):
        """装饰器：注册 Provider"""
        def wrapper(provider_cls):
            cls._providers[name] = provider_cls
            return provider_cls
        return wrapper

    @classmethod
    def create(cls, name: str, account: AccountConfig) -> BaseProvider:
        """工厂方法：根据名称 + 账号配置创建 Provider 实例"""
        ...
```

#### 4.1.2 Provider 调度器

参考 Chat2API 的 `ProviderForwarder` 列表模式：

```python
class ProviderDispatcher:
    """根据请求的 model 找到对应的 Provider + 账号"""

    def __init__(self, model_mapper, load_balancer):
        self.model_mapper = model_mapper    # 模型名 → Provider Type 映射
        self.load_balancer = load_balancer   # Provider Type → 具体账号选择

    async def dispatch(
        self,
        request: ChatCompletionRequest
    ) -> tuple[BaseProvider, str]:
        """返回 (provider_instance, actual_model)"""
        ...
```

### 4.2 两种工作模式

业界两个参考项目揭示了两种核心技术路线：

#### 模式 A：API Reverse（推荐，优先实现）

**原理**：网页版 LLM 本质上也是调用内部 HTTP API。从浏览器 DevTools 抓包获取认证 Token，直接重放 API 请求。

```
用户浏览器 ←→ LLM Web UI  ←HTTP/SSE→ 内部 API
                                    ↑
                              WebAPI 代理（重放）
```

**步骤：**

1. 用户在浏览器中登录 LLM（如 chat.deepseek.com）
2. 从 DevTools → Application → LocalStorage 提取 `userToken`
3. 将 Token 填入 WebAPI 账号配置
4. WebAPI 用 Token 直接调用内部 API（绕过 Web UI 层）

**优点：**

- 无需启动浏览器，轻量高效
- 支持高并发
- 参考 Chat2API 的全部 Provider 实现

**缺点：**

- 需要手动抓取 Token
- Token 可能过期（需要刷新机制）
- 某些平台 API 有反爬/签名验证

#### 模式 B：Browser Drive（复杂场景备选）

**原理**：通过 Playwright 启动无头浏览器，自动化操作网页版对话 UI，拦截 API 调用。

```
WebAPI → Playwright → Chromium → 网页版 LLM
                ↕
              拦截 API 请求/响应
```

**适用场景：**

- API Reverse 遇到反爬/Cloudflare 保护
- 网页 WebSocket 通信（无法直接用 HTTP 重放）
- 需要浏览器指纹模拟的极端场景

**参考**：AIClient2API 的 TLS Sidecar + Grok Cookie 模式

#### 两种模式对比

| 维度         | API Reverse | Browser Drive |
| ---------- | ----------- | ------------- |
| 性能         | ⭐⭐⭐⭐⭐ 轻量    | ⭐⭐ 重（需启动浏览器）  |
| 并发         | ⭐⭐⭐⭐⭐       | ⭐⭐            |
| 实现复杂度      | ⭐⭐⭐ 中等      | ⭐⭐⭐⭐⭐ 高       |
| 反爬对抗       | ⭐⭐ 弱        | ⭐⭐⭐⭐ 强        |
| Token 生命周期 | 需手动刷新       | 浏览器自动维护       |

**本项目策略：API Reverse 优先，Browser Drive 作为兜底。**

### 4.3 Provider 实现示例（DeepSeek）

以 DeepSeek 为例，说明 Provider 的完整生命周期：

```
┌──────────┐     ┌─────────────┐     ┌─────────────────┐
│ 用户请求  │────▶│  FastAPI     │────▶│ ProviderDispatcher│
│ /v1/chat │     │  /v1/chat   │     │ dispatch(model)  │
└──────────┘     └─────────────┘     └────────┬────────┘
                                              │
                                    ┌─────────▼─────────┐
                                    │  DeepSeekProvider   │
                                    │                     │
                                    │  1. 从账号池选账号   │
                                    │  2. 获取 userToken   │
                                    │  3. 创建对话 session  │
                                    └─────────┬───────────┘
                                              │
                                    ┌─────────▼───────────┐
                                    │  POST deepseek API  │
                                    │  /chat/completion   │
                                    │  Authorization:     │
                                    │  Bearer <userToken> │
                                    └─────────┬───────────┘
                                              │
                                    ┌─────────▼───────────┐
                                    │ DeepSeekStreamHandler│
                                    │                     │
                                    │  SSE → OpenAI Chunk │
                                    │  解析 thinking       │
                                    │  解析 web_search     │
                                    └─────────┬───────────┘
                                              │
                                    ┌─────────▼───────────┐
                                    │  返回 OpenAI SSE     │
                                    │  data: {...}\n\n    │
                                    └─────────────────────┘
```

**关键类：**

```python
class DeepSeekProvider(BaseProvider):
    name = "deepseek"
    display_name = "DeepSeek"
    auth_type = "token"

    def __init__(self, account: AccountConfig):
        self.account = account
        self.base_url = "https://chat.deepseek.com/api/v0"

    async def chat_completion(self, request, stream=False):
        # 1. 创建 session
        session_id = await self._create_chat_session()

        # 2. 构造内部 API 请求体
        body = self._build_request(request)

        # 3. 发送请求
        response = await self._http_post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.account.token}"}
        )

        # 4. 非流式：SSE 收集 → JSON
        if not stream:
            result = await DeepSeekStreamHandler.collect(response)
            # 5. 清理 session
            await self._delete_session(session_id)
            return result

        # 6. 流式：生成 AsyncGenerator
        return DeepSeekStreamHandler.stream(response)
```

### 4.4 SSE 流式处理

统一了所有 Provider 的流式处理——这是参考 Chat2API 的核心模式：

```python
class BaseStreamHandler(ABC):
    """流式处理基类 — 每个 Provider 各有一个子类"""

    actual_model: str    # 实际模型名

    @abstractmethod
    async def handle_stream(
        self,
        raw_stream: AsyncIterator[bytes]
    ) -> AsyncGenerator[str, None]:
        """处理原始 SSE 流 → OpenAI 兼容 SSE 格式"""
        ...

    @abstractmethod
    async def handle_non_stream(
        self,
        raw_stream: AsyncIterator[bytes]
    ) -> dict:
        """收集原始 SSE 流 → 完整的 ChatCompletion JSON"""
        ...
```

**DeepSeek 示例：**

```python
class DeepSeekStreamHandler(BaseStreamHandler):
    """DeepSeek 特有的 SSE 格式解析"""

    SEPARATOR = b'\n\n'

    async def handle_stream(self, raw_stream):
        async for line in self._iter_lines(raw_stream):
            if not line.startswith("data:"):
                continue
            data = json.loads(line[5:])

            # DeepSeek 的 SSE 格式 → OpenAI Delta 格式
            chunk = {
                "id": f"chatcmpl-{uuid4()}",
                "object": "chat.completion.chunk",
                "model": self.actual_model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "content": data.get("choices", [{}])[0]
                                   .get("delta", {}).get("content", "")
                    }
                }]
            }
            yield f"data: {json.dumps(chunk)}\n\n"

        yield "data: [DONE]\n\n"
```

### 4.5 账号池与负载均衡

参考 AIClient2API 的账号池设计：

```python
class AccountPool:
    """账号池 — 管理多个账号 + 健康状态"""

    accounts: dict[str, list[AccountState]]
    # {"deepseek": [AccountState(...), AccountState(...)]}

    async def select(
        self,
        provider_type: str,
        model: str,
        strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN
    ) -> AccountState:
        """选择一个健康账号"""
        ...

    async def mark_unhealthy(self, account_id: str, reason: str):
        """标记账号不健康 + 自动冷却恢复"""
        ...

    async def health_check_all(self):
        """定时健康检查所有账号"""
        ...


class LoadBalanceStrategy(Enum):
    ROUND_ROBIN = "round_robin"        # 轮询（默认）
    FILL_FIRST = "fill_first"         # 填满优先
    FAILOVER = "failover"              # 故障转移
    WEIGHTED = "weighted"              # 加权轮询
```

**冷却恢复机制（参考 AIClient2API 的 RATE_LIMIT_COOLDOWN）：**

```
账号被限流(429) → 标记 unhealthy → 冷却 N 秒 → 自动恢复 healthy → 重新加入轮询
```

### 4.6 Fallback 降级链

当某一 Provider 的所有账号都不可用时，自动切换到备用 Provider：

```python
# config.yaml
provider_fallback:
  deepseek:
    - deepseek_custom    # 自定义 Endpoint
    - openrouter_deepseek  # 第三方中转
  kimi:
    - moonshot_api       # Moonshot 官方 API
```

### 4.7 OpenAI 兼容 API 路由

```python
# src/server/routes.py

@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI 兼容 Chat Completions API
    同时支持流式和非流式
    """
    provider, actual_model = await dispatcher.dispatch(request)

    if request.stream:
        return StreamingResponse(
            provider.chat_completion_stream(request),
            media_type="text/event-stream"
        )
    else:
        result = await provider.chat_completion(request)
        return result


@router.get("/v1/models")
async def list_models():
    """列出所有可用模型"""
    ...


@router.get("/health")
async def health():
    """健康检查"""
    ...


@router.get("/stats")
async def stats():
    """请求统计"""
    ...
```

### 4.8 配置管理

```yaml
# config/config.yaml
server:
  host: "127.0.0.1"
  port: 8080
  api_key_enabled: false
  api_keys: []

proxy:
  timeout: 120
  retry_count: 3
  retry_delay: 5  # 秒

load_balance:
  default_strategy: "round_robin"
  rate_limit_cooldown: 60  # 429 后冷却 60 秒

providers:
  deepseek:
    enabled: true
    accounts:
      - name: "account-1"
        token: "your-user-token"
        models: ["deepseek-v4-flash", "deepseek-v4-pro"]
        max_concurrent: 5
        health_check_interval: 60
      - name: "account-2"
        token: "your-user-token-2"
        models: ["deepseek-v4-flash"]

  kimi:
    enabled: true
    accounts:
      - name: "account-1"
        token: "your-jwt-token"
        models: ["Kimi-K2.6"]

model_mappings:
  # 通配符映射
  "*deepseek*":
    provider: "deepseek"
  "*kimi*":
    provider: "kimi"
  # 精确映射
  "gpt-4":
    provider: "deepseek"
    actual_model: "deepseek-v4-pro"

context_management:
  enabled: false
  max_messages: 50
  max_tokens: 128000
  strategy: "sliding_window"  # "sliding_window" | "summarize" | "trim"

tool_calling:
  enabled: true
  mode: "prompt_engineering"  # 通过 Prompt 注入实现（参考 Chat2API）

logging:
  level: "INFO"
  file: "logs/webapi.log"
  max_size: "10MB"
  retention: "7 days"
```

---

## 五、Provider 实现指南

### 5.1 添加新 Provider 的步骤

参考 Chat2API 的 Provider 扩展模式：

1. **创建 Provider 目录**：`src/provider/<name>/`
2. **分析网页 API**：用浏览器 DevTools 抓包，记录：
   - 认证方式（Token 在哪？LocalStorage / Cookie / Header）
   - Chat API 端点 URL
   - 请求体格式（参数映射）
   - SSE 响应格式（data 字段结构）
3. **实现认证模块**：`auth.py`
   - Token 提取 / 刷新逻辑
4. **实现适配器**：`adapter.py`
   - `chat_completion()` 和 `chat_completion_stream()`
5. **实现流式处理器**：`stream_handler.py`
   - 解析 Provider 特有的 SSE 格式
   - 转为 OpenAI Delta 格式
6. **注册 Provider**：在 `registry.py` 注册
7. **编写测试**：`tests/test_<name>.py`
8. **添加文档**：`docs/providers/<name>.md`

### 5.2 Provider 接口契约

每个 `adapter.py` 必须返回：

```python
@dataclass
class ProviderResponse:
    """Adapter 返回的标准格式"""
    status_code: int
    data: Optional[dict] = None         # 非流式的 JSON 响应
    raw_stream: Optional[AsyncIterator] = None  # 流式的原始数据
    session_id: Optional[str] = None    # 提供商对话 session ID
    headers: dict = field(default_factory=dict)
```

### 5.3 首批支持的 Provider

| Provider       | 网页地址                | 认证方式                     | 优先级 | 参考来源                 |
| -------------- | ------------------- | ------------------------ | --- | -------------------- |
| DeepSeek       | chat.deepseek.com   | UserToken (LocalStorage) | P0  | Chat2API deepseek.ts |
| 通义千问 (Qwen CN) | tongyi.aliyun.com   | SSO Ticket               | P0  | Chat2API qwen.ts     |
| Kimi           | kimi.moonshot.cn    | JWT Token                | P0  | Chat2API kimi.ts     |
| 智谱清言 (GLM)     | chatglm.cn          | Refresh Token            | P0  | Chat2API glm.ts      |
| MiniMax        | hailuoai.com        | JWT Token                | P1  | Chat2API minimax.ts  |
| 豆包 (字节)        | doubao.com          | Cookie                   | P1  | -                    |
| 腾讯元宝           | yuanbao.tencent.com | Cookie                   | P2  | -                    |
| Coze (国际版)     | coze.com            | Cookie                   | P2  | AIClient2API         |

---

## 六、关键问题与解决方案

### 6.1 Token 过期处理

| 方案                         | 实现                                      |
| -------------------------- | --------------------------------------- |
| **被动刷新**：请求返回 401 时自动刷新    | `adapter.py` 中捕获 401，调用 refresh_token() |
| **主动刷新**：定时任务检测 Token 过期时间 | 后台 asyncio Task，每分钟检查                   |
| **通知用户**：刷新失败时推送通知         | FastAPI Webhook / 日志告警                  |

### 6.2 并发控制

- 单账号最大并发：`max_concurrent` 配置
- 账号池自动分配：超过并发等待队列
- 支持全局并发上限

### 6.3 反爬对抗

| 问题            | 方案                                       |
| ------------- | ---------------------------------------- |
| Cloudflare 保护 | 使用 `curl_cffi` 模拟浏览器 TLS 指纹              |
| 签名验证          | 逆向 JS 签名逻辑，或降级到 Playwright 模式            |
| User-Agent 检测 | 使用真实浏览器 UA，参考 Chat2API 的 `signatures.ts` |

### 6.4 上下文窗口管理

参考 Chat2API 的 `contextManagementService`：

- **滑动窗口**：只保留最近 N 条消息
- **Token 裁剪**：超过 `max_tokens` 时从最早消息裁剪
- **摘要模式**：超量消息由模型自身总结 → 注入 system prompt

### 6.5 工具调用 (Tool Calling)

参考 Chat2API 的 `ToolCallingEngine`（Prompt 工程方式）：

- 不支持原生 function calling 的模型 → 在 system prompt 中注入工具定义
- 在响应中解析工具调用 JSON
- 支持 Cherry Studio / Cline 等客户端

---

## 七、开发计划

### Phase 1：核心框架（预计 3-5 天）

- [ ] 项目脚手架搭建（pyproject.toml、目录结构）
- [ ] FastAPI 服务器 + OpenAI 兼容路由
- [ ] Provider 抽象基类 + 注册中心
- [ ] 配置管理系统（YAML → Pydantic）
- [ ] 日志系统
- [ ] 单元测试框架

### Phase 2：首批 Provider（预计 5-7 天）

- [ ] DeepSeek Provider（参考 Chat2API）
- [ ] Kimi Provider
- [ ] 通义千问 Provider
- [ ] Flow Handler 通用基类
- [ ] 集成测试

### Phase 3：高级功能（预计 3-5 天）

- [ ] 账号池 + 负载均衡
- [ ] 健康检查 + 自动故障转移
- [ ] Fallback 降级链
- [ ] API Key 鉴权
- [ ] 请求统计 Dashboard

### Phase 4：完善（预计 3-5 天）

- [ ] 更多 Provider（MiniMax、豆包、元宝）
- [ ] 上下文窗口管理
- [ ] 工具调用 (Prompt Engineering)
- [ ] 管理 UI（Web 控制台）

---

## 八、关键参考源码

### Chat2API 核心文件

| 文件                                  | 作用                     |
| ----------------------------------- | ---------------------- |
| `src/main/proxy/server.ts`          | Koa HTTP 服务器           |
| `src/main/proxy/forwarder.ts`       | Provider 转发核心（~1000 行） |
| `src/main/proxy/stream.ts`          | SSE 流式处理               |
| `src/main/proxy/loadbalancer.ts`    | 负载均衡                   |
| `src/main/proxy/modelMapper.ts`     | 模型映射                   |
| `src/main/proxy/prompt/deepseek.ts` | DeepSeek 适配器           |
| `src/main/proxy/prompt/kimi.ts`     | Kimi 适配器               |
| `src/main/proxy/toolCalling/`       | 工具调用引擎                 |
| `src/main/proxy/sessionManager.ts`  | 会话管理                   |

### AIClient2API 核心文件

| 文件                                        | 作用                         |
| ----------------------------------------- | -------------------------- |
| `src/providers/adapter.js`                | Adapter 抽象基类 + 注册表         |
| `src/providers/provider-pool-manager.js`  | 账号池 + 健康检查                 |
| `src/core/master.js`                      | Master-Worker 进程管理         |
| `src/services/api-server.js`              | HTTP 服务器                   |
| `src/handlers/request-handler.js`         | 请求路由分发                     |
| `src/convert/convert.js`                  | 协议转换（OpenAI↔Claude↔Gemini） |
| `src/providers/gemini/gemini-strategy.js` | Provider 策略模式              |
| `src/utils/provider-strategies.js`        | Provider Strategy 注册       |

---

## 九、命名约定

| 概念        | 本项目命名                     | Chat2API 对应                    | AIClient2API 对应         |
| --------- | ------------------------- | ------------------------------ | ----------------------- |
| AI 厂商接口封装 | `Provider`                | `ProviderPlugin` / `Forwarder` | `ApiServiceAdapter`     |
| HTTP 反向代理 | `API Reverse Transport`   | `Axios HTTP Client`            | `Provider Core Service` |
| 浏览器操控     | `Browser Drive Transport` | 无                              | 无（TLS Sidecar 近似）       |
| 流式解析器     | `StreamHandler`           | `StreamHandler` (同名!)          | `convertStreamChunk()`  |
| 多账号管理     | `AccountPool`             | `LoadBalancer`                 | `ProviderPoolManager`   |
| 模型名映射     | `ModelMapper`             | `ModelMapper` (同名!)            | `getProtocolPrefix()`   |
| 负载策略      | `LoadBalanceStrategy`     | `LoadBalancerStrategy`         | `Pool Selection`        |
| 故障转移      | `FallbackChain`           | 无                              | `providerFallbackChain` |

---

## 十、开发环境

```bash
# 1. 克隆项目
git clone <repo-url> WebAPI
cd WebAPI

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 Playwright 浏览器（可选，Browser Drive 模式需要）
playwright install chromium

# 5. 配置
cp config/config.yaml.example config/config.yaml
# 编辑 config.yaml 填入你的 Provider Token

# 6. 启动
python src/main.py

# 7. 测试
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

---

> 📌 **设计原则总结：**
> 
> 1. **Adapter 模式**：Provider 接口统一、实现隔离（取自两个参考项目）
> 2. **API Reverse 优先**：轻量高效，Browser Drive 兜底
> 3. **Python 生态**：发挥 Playwright + asyncio 优势
> 4. **渐进开发**：先核心框架（Phase 1-2），再高级功能（Phase 3-4）
> 5. **兼容 OpenAI**：所有 Provider 统一输出标准格式
