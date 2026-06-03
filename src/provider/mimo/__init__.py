# -*- coding: utf-8 -*-
"""
MiMo (小米 AI Studio) Provider Adapter

网页 API 协议：
- Base URL: https://aistudio.xiaomimimo.com
- 认证: Cookie（serviceToken, userId, xiaomichatbot_ph）
- 对话: POST /open-apis/bot/chat（SSE 流）
- User-Agent: 从 Chrome 143 复制

配置方式：
1. 通过 Web 管理后台导入 Cookie（推荐）
   - 登录 https://aistudio.xiaomimimo.com
   - 打开 DevTools → Application → Cookies
   - 提取 serviceToken, userId, xiaomichatbot_ph

2. 通过配置文件（config.yaml）
```yaml
providers:
  mimo:
    enabled: true
    accounts:
    - name: account-1
      serviceToken: "your-service-token"
      userId: "your-user-id"
      xiaomichatbot_ph: "your-xiaomichatbot-ph"
```

支持的模型：
- mimo-v2-flash（快速响应）
- mimo-v2-pro（高性能）
- mimo-v2-omni（多模态）
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional, List

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────
MIMO_BASE = "https://aistudio.xiaomimimo.com"
MIMO_CHAT_URL = f"{MIMO_BASE}/open-apis/bot/chat"
MIMO_DELETE_URL = f"{MIMO_BASE}/open-apis/chat/conversation/delete"

# ─────────────────────────────────────────────────────────────
# Default Headers
# ─────────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": MIMO_BASE,
    "Referer": f"{MIMO_BASE}/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    ),
    "X-Timezone": "Asia/Shanghai",
}

DEFAULT_MODELS = [
    "mimo-v2-flash",
    "mimo-v2-pro",
    "mimo-v2-omni",
]

# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────
def _random_hex(length: int = 32) -> str:
    """生成指定长度的十六进制随机字符串"""
    return uuid.uuid4().hex[:length]


def _generate_msg_id() -> str:
    """生成 32 位 UUID 的 hex 格式"""
    return _random_hex(32)


def _generate_conversation_id() -> str:
    """生成 32 位 UUID 的 hex 格式（新的对话）"""
    return ""  # 空字符串表示创建新会话


@ProviderRegistry.register("mimo")
class MiMoProvider(BaseProvider):
    """小米 MiMo AI Studio 网页 API 适配器

    认证要求：
    - serviceToken: 服务凭证（从 Cookie 获取）
    - userId: 用户 ID（从 Cookie 获取）
    - xiaomichatbot_ph: 会话标识（从 Cookie 获取）

    使用方式：
    1. 登录 aistudio.xiaomimimo.com
    2. 打开 DevTools → Application → Cookies
    3. 提取三个 Cookie 值
    4. 在 Web 管理后台或 config.yaml 配置

    注意：
    - serviceToken 有效期约 24 小时
    - 过期后需要重新登录并更新 Cookie
    """

    name = "mimo"
    display_name = "小米 MiMo (Xiaomi MiMo)"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        super().__init__(account)

        # 从 AccountConfig 获取凭证（支持 extra fields 和 token/cookie 字段）
        # AccountConfig 有 token, cookie, user_id 字段 + extra: allow
        # MiMo 需要三个凭证，存储方式：
        #   - token 字段 → serviceToken
        #   - user_id 字段 → userId
        #   - xiaomichatbot_ph 通过 extra field 获取
        self._service_token = (
            account.token
            or getattr(account, "service_token", "")
            or getattr(account, "serviceToken", "")
        )
        self._user_id = (
            account.user_id
            or getattr(account, "userId", "")
        )
        self._xiaomichatbot_ph = (
            getattr(account, "xiaomichatbot_ph", "")
            or getattr(account, "ph_token", "")
            or getattr(account, "phToken", "")
        )

        # 检查必需的凭证
        if not self._service_token or not self._user_id or not self._xiaomichatbot_ph:
            raise AuthError(
                "MiMo provider requires 3 credentials: serviceToken, userId, xiaomichatbot_ph.\n"
                "Please login to https://aistudio.xiaomimimo.com, open DevTools → Application → Cookies,\n"
                "and configure: token=<serviceToken>, user_id=<userId>, xiaomichatbot_ph=<ph value>"
            )

        self._http_session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取 HTTP 会话（单例）"""
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close(self) -> None:
        """关闭 HTTP 会话"""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

    async def list_models(self) -> List[str]:
        """列出可用模型"""
        return DEFAULT_MODELS

    async def health_check(self) -> bool:
        """健康检查：验证 Cookie 有效性"""
        try:
            session = await self._get_session()

            headers = DEFAULT_HEADERS.copy()
            headers["Cookie"] = (
                f"serviceToken={self._service_token}; "
                f"userId={self._user_id}; "
                f"xiaomichatbot_ph={self._xiaomichatbot_ph}"
            )

            # 发送简单的健康检查请求
            async with session.get(
                MIMO_CHAT_URL,
                headers=headers,
                params={"xiaomichatbotbot_ph": self._xiaomichatbot_ph},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200

        except Exception as e:
            logger.error(f"[MiMo] Health check failed: {e}")
            return False

    # ---- Chat Completion ----

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """非流式对话

        实现策略：
        1. 调用 chat_completion_stream 获取流式数据
        2. 收集所有 chunk 并合并
        3. 返回 OpenAI 兼容的 ProviderResponse 格式
        """
        try:
            result_parts: List[str] = []
            async for chunk in self.chat_completion_stream(request):
                if chunk.content:
                    result_parts.append(chunk.content)

            content = "".join(result_parts)

            return ProviderResponse(
                status_code=200,
                data={
                    "id": f"chatcmpl-{_random_hex(12)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request.model or "mimo-v2-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": getattr(chunk, "usage", {}).get("prompt_tokens", 0) if hasattr(chunk, "usage") else 0,
                        "completion_tokens": getattr(chunk, "usage", {}).get("completion_tokens", 0) if hasattr(chunk, "usage") else 0,
                        "total_tokens": getattr(chunk, "usage", {}).get("total_tokens", 0) if hasattr(chunk, "usage") else 0,
                    },
                },
            )

        except Exception as e:
            logger.error(f"[MiMo] Non-stream error: {e}")
            raise

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话

        SSE 流格式：
        data: {"type":"text","content":"Hello"}
        data: {"type":"done"}
        """
        session = await self._get_session()

        # 确定模型
        actual_model = self._map_model(request.model)

        # 构建消息内容
        prompt = self._messages_to_prompt(request)

        # 确定配置
        enable_thinking = request.reasoning_effort in ["high", "medium", "low"]

        # 构建请求 body
        payload = {
            "msgId": _generate_msg_id(),
            "conversationId": _generate_conversation_id(),
            "query": prompt,
            "modelConfig": {
                "enableThinking": enable_thinking,
                "temperature": 0.8,
                "topP": 0.95,
                "webSearchStatus": "disabled",
                "model": actual_model,
            },
            "multiMedias": [],
            "attachments": [],
        }

        headers = DEFAULT_HEADERS.copy()
        headers["Cookie"] = (
            f"serviceToken={self._service_token}; "
            f"userId={self._user_id}; "
            f"xiaomichatbot_ph={self._xiaomichatbot_ph}"
        )

        logger.info(
            f"[MiMo] Stream: model={actual_model} "
            f"thinking={enable_thinking} session={payload['conversationId'][:8] if payload['conversationId'] else 'N/A'}"
        )

        try:
            async with session.post(
                MIMO_CHAT_URL,
                headers=headers,
                params={"xiaomichatbotbot_ph": self._xiaomichatbot_ph},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise ProviderError(
                        f"MiMo API error: HTTP {resp.status} — {text[:200]}",
                        provider="mimo",
                    )

                # 解析 SSE 流
                async for line in resp.content:
                    line_text = line.decode("utf-8", errors="replace").strip()

                    if not line_text.startswith("data:"):
                        continue

                    # 提取 JSON 数据
                    json_str = line_text[5:].strip()

                    try:
                        data = json.loads(json_str)

                        # 只处理 text 类型的数据
                        if data.get("type") == "text":
                            content = data.get("content", "")
                            yield StreamChunk(
                                content=content,
                                model=actual_model,
                            )

                        # 处理 token 用量（如果有）
                        elif data.get("type") == "usage":
                            prompt_tokens = data.get("promptTokens", 0)
                            completion_tokens = data.get("completionTokens", 0)

                            yield StreamChunk(
                                content="",
                                model=actual_model,
                                usage={
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "total_tokens": prompt_tokens + completion_tokens,
                                },
                            )

                    except json.JSONDecodeError as e:
                        logger.warning(f"[MiMo] Failed to parse SSE data: {e} — {json_str[:100]}")
                        continue

        except aiohttp.ClientError as e:
            raise ProviderError(
                f"MiMo network error: {e}",
                provider="mimo",
            )

    # ---- Helper Methods ----

    def _map_model(self, model: str) -> str:
        """映射模型名称"""
        if not model:
            return "mimo-v2-flash"

        model_map = {
            "mimo-v2-flash": "mimo-v2-flash",
            "mimo-v2-pro": "mimo-v2-pro",
            "mimo-v2-omni": "mimo-v2-omni",
        }

        # 支持简写
        short_map = {
            "flash": "mimo-v2-flash",
            "pro": "mimo-v2-pro",
            "omni": "mimo-v2-omni",
        }

        return model_map.get(model, model_map.get(short_map.get(model.lower(), ""), "mimo-v2-flash"))

    def _messages_to_prompt(self, request: ChatCompletionRequest) -> str:
        """将 OpenAI messages 转换为单条 prompt

        Chat2API-main 风格：
        - system prompt 合并到用户消息前
        - 单条用户消息
        """
        # 收集所有消息
        messages = []

        # System prompt
        system_prompt = ""
        for msg in request.messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_prompt = msg.content
                break

        # 收集所有非 system 消息
        for msg in request.messages:
            if msg.role != "system":
                if isinstance(msg.content, str):
                    messages.append(msg.content)
                elif isinstance(msg.content, list):
                    # 多模态消息（暂不支持）
                    messages.append(str(msg.content))

        # 合并 system prompt
        if system_prompt:
            final_message = f"{system_prompt}\n\nUser: {messages[-1] if messages else ''}"
        else:
            final_message = messages[-1] if messages else ""

        return final_message
