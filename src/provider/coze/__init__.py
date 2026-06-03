# -*- coding: utf-8 -*-
"""
Coze Provider Adapter — 字节跳动 Coze (扣子) 平台

基于 Coze 官方 API v3，参考 Chat2API 的 Provider 架构模式。

官方 API v3:
- Base URL: https://api.coze.cn (国内·默认) / https://api.coze.com (国际)
- Auth: Bearer <Personal Access Token>
- Chat: POST /v3/chat (SSE streaming)
- 健康检查: GET /v1/user/me
- Bot 列表: GET /v1/space/publish/bots

模型映射策略:
- Coze 以 Bot 为核心，每个 Bot 绑定不同的模型 + 知识库 + 插件
- Bot ID 与模型名之间通过 account.models 或 model_mappings 映射
- 默认映射: coze-chat → 账号配置的第一个 Bot

参考 Chat2API 模式:
- Token 生命周期管理 (PAT 永不过期，无需 refresh)
- SSE 事件驱动流式解析
- 工具调用转换 (Coze plugin → OpenAI function call)
- 对话 ID 管理
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Optional

from src.core.config import AccountConfig
from src.core.models import (
    ChatCompletionRequest,
    ProviderResponse,
    StreamChunk,
    ToolDefinition,
)
from src.core.exceptions import ProviderError, AuthError, RateLimitError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────
COZE_BASE_CN = "https://api.coze.cn"
COZE_BASE_COM = "https://api.coze.com"

# ─────────────────────────────────────────────────────────────
# SSE 事件类型 — Coze API v3 ╱ OpenAI SSE 兼容
# ─────────────────────────────────────────────────────────────
class CozeSSEEvent:
    """Coze SSE 事件名称常量"""
    # 对话生命周期
    CHAT_CREATED = "conversation.chat.created"
    CHAT_IN_PROGRESS = "conversation.chat.in_progress"
    CHAT_COMPLETED = "conversation.chat.completed"
    CHAT_FAILED = "conversation.chat.failed"
    CHAT_REQUIRES_ACTION = "conversation.chat.requires_action"
    # 消息生命周期
    MESSAGE_DELTA = "conversation.message.delta"
    MESSAGE_COMPLETED = "conversation.message.completed"
    # 流结束
    DONE = "done"

# ─────────────────────────────────────────────────────────────
# 默认配置
# ─────────────────────────────────────────────────────────────
FAKE_HEADERS = {
    "Accept": "text/event-stream, application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

DEFAULT_MODELS = ["coze-chat"]

# ─────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────
def _random_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_ts() -> int:
    return int(time.time())


def _parse_sse(content: str) -> Optional[dict]:
    """解析 SSE 字节块 → event + data

    处理格式：
        event: conversation.message.delta
        data: {"id":"...","content":"Hello"}

    或：
        data: [DONE]
    """
    event_type: Optional[str] = None
    data_str: Optional[str] = None

    for line in content.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()

    if data_str and data_str == "[DONE]":
        return {"event": CozeSSEEvent.DONE, "data": None}
    if data_str and event_type:
        try:
            return {"event": event_type, "data": json.loads(data_str)}
        except json.JSONDecodeError:
            # data 可能是多行 JSON 需要拼接
            pass
    return None


def _extract_error(data: Optional[dict]) -> Optional[str]:
    """从 Coze 错误响应提取错误信息"""
    if not data:
        return "Unknown error"

    # API v3 错误格式: {"code": 4000, "msg": "..."}
    code = data.get("code", 0)
    msg = data.get("msg", "") or data.get("message", "") or data.get("detail", "")

    if code == 4000:
        return f"Bad Request: {msg}"
    if code == 4001:
        return f"Unauthorized: {msg or 'Token invalid or expired'}"
    if code == 4002:
        return f"Forbidden: {msg or '无权限访问此 Bot'}"
    if code == 4003:
        return f"Not Found: {msg or 'Bot not found'}"
    if code == 4290:
        return f"Rate Limited: {msg or '请求频率过高，请稍后重试'}"
    if code == 5000:
        return f"Internal Error: {msg or 'Coze 服务内部错误'}"
    return f"API Error ({code}): {msg}"


def _map_error(status: int, body_text: str) -> Exception:
    """映射 HTTP 状态码 → 异常类型"""
    try:
        data = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        data = {}

    err_msg = _extract_error(data) or body_text[:200]

    if status == 401:
        return AuthError(f"Coze: {err_msg}")
    if status == 429:
        return RateLimitError(f"Coze: {err_msg}")
    if status == 400:
        return ProviderError(f"Coze Bad Request: {err_msg}")
    if status >= 500:
        return ProviderError(f"Coze Server Error ({status}): {err_msg}")
    return ProviderError(f"Coze ({status}): {err_msg}")


# ─────────────────────────────────────────────────────────────
# CozeStreamHandler — SSE → OpenAI StreamChunk
# ─────────────────────────────────────────────────────────────
class CozeStreamHandler:
    """Coze SSE 流 → 统一 StreamChunk 转换器

    参考 Chat2API 的 DeepSeekStreamHandler 模式:
    - 事件驱动解析 (conversation.message.delta → content delta)
    - 工具调用检测 (requires_action → function call)
    - 流结束标记 (done)
    """

    def __init__(self, model: str, request_id: str = ""):
        self.model = model
        self.request_id = request_id or f"coze-{_random_id()}"
        self._buffer = ""
        self._content_parts: list[str] = []
        self._tool_calls: list[dict] = []
        self._conversation_id: str = ""
        self._chat_id: str = ""
        self._message_id: str = ""
        self._is_done: bool = False
        self._has_error: bool = False
        self._error_msg: str = ""

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def is_done(self) -> bool:
        return self._is_done

    @property
    def error(self) -> str:
        return self._error_msg

    def feed_bytes(self, chunk: bytes) -> list[StreamChunk]:
        """喂入原始字节 → 返回解析后的 StreamChunk 列表

        处理跨 chunk 的 SSE 行拼接。
        """
        results: list[StreamChunk] = []
        self._buffer += chunk.decode("utf-8", errors="replace")

        # 按双换行分割 SSE 事件
        while "\n\n" in self._buffer:
            event_block, self._buffer = self._buffer.split("\n\n", 1)
            parsed = self._process_event(event_block)
            if parsed:
                results.append(parsed)

        return results

    def flush(self) -> StreamChunk:
        """清空缓冲区 → 返回剩余内容 + finish_reason"""
        # 处理缓冲区中可能残留的数据
        if self._buffer.strip():
            event_block = self._buffer.strip()
            self._buffer = ""
            parsed = self._process_event(event_block)
            if parsed:
                return parsed

        return StreamChunk(
            content="",
            reasoning_content="",
            model=self.model,
            finish_reason="stop",
        )

    def _process_event(self, event_block: str) -> Optional[StreamChunk]:
        """处理单个 SSE 事件块"""
        sse = _parse_sse(event_block)
        if not sse:
            return None

        event_type = sse["event"]
        data = sse.get("data")

        # ── 流结束 ──
        if event_type == CozeSSEEvent.DONE:
            self._is_done = True
            return StreamChunk(
                content="",
                reasoning_content="",
                model=self.model,
                finish_reason="stop",
            )

        # ── 错误 ──
        if event_type == CozeSSEEvent.CHAT_FAILED:
            self._has_error = True
            raw_msg = ""
            if isinstance(data, dict):
                raw_msg = data.get("msg", data.get("message", ""))
            self._error_msg = raw_msg or "Chat failed"
            logger.warning(f"[Coze] Stream error: {self._error_msg}")
            return StreamChunk(
                content="",
                reasoning_content="",
                model=self.model,
                finish_reason="error",
            )

        # ── 对话创建 ──
        if event_type == CozeSSEEvent.CHAT_CREATED and data:
            self._chat_id = data.get("id", "")
            self._conversation_id = data.get("conversation_id", "")
            logger.debug(
                f"[Coze] Chat created: chat_id={self._chat_id}, "
                f"conv_id={self._conversation_id}"
            )
            return None

        # ── 对话进行中 ──
        if event_type == CozeSSEEvent.CHAT_IN_PROGRESS:
            return None  # 元事件，不产生内容

        # ── 消息增量 (核心流内容) ──
        if event_type == CozeSSEEvent.MESSAGE_DELTA and data:
            content = data.get("content", "")
            msg_role = data.get("role", "assistant")
            msg_type = data.get("type", "answer")
            self._message_id = data.get("id", self._message_id)

            if not content:
                return None

            # reasoning / think 类型
            if msg_type in ("reasoning", "think", "verbose"):
                return StreamChunk(
                    content="",
                    reasoning_content=content,
                    model=self.model,
                )

            # 工具调用
            if msg_type == "tool_response" or msg_type == "function_call":
                self._tool_calls.append({
                    "id": data.get("id", f"call_{len(self._tool_calls)}"),
                    "type": "function",
                    "function": {
                        "name": data.get("function_name", data.get("name", "")),
                        "arguments": content,
                    },
                })
                return None

            # 正常文本内容
            self._content_parts.append(content)
            return StreamChunk(
                content=content,
                reasoning_content="",
                model=self.model,
            )

        # ── 消息完成 ──
        if event_type == CozeSSEEvent.MESSAGE_COMPLETED and data:
            logger.debug(
                f"[Coze] Message completed: id={data.get('id', '')}, "
                f"type={data.get('type', '')}"
            )
            return None

        # ── 需要操作 (工具调用) ──
        if event_type == CozeSSEEvent.CHAT_REQUIRES_ACTION and data:
            logger.debug(f"[Coze] Chat requires action")
            return None

        # ── 对话完成 ──
        if event_type == CozeSSEEvent.CHAT_COMPLETED:
            self._is_done = True
            return StreamChunk(
                content="",
                reasoning_content="",
                model=self.model,
                finish_reason="stop",
            )

        return None


# ─────────────────────────────────────────────────────────────
# CozeProvider
# ─────────────────────────────────────────────────────────────
@ProviderRegistry.register("coze")
class CozeProvider(BaseProvider):
    """Coze (扣子) API v3 适配器

    参考 Chat2API 的 Provider 架构:
    - Token 自动注入 (Bearer Auth)
    - SSE 事件驱动解析
    - 对话 ID 生命周期管理
    - 工具调用支持 (Coze Plugin)
    - 多 Bot 支持 (model → bot_id 映射)

    凭证要求:
    - token: Coze Personal Access Token (PAT)
      - 获取: coze.cn → 个人设置 → API → 个人访问令牌
      - 需要权限: Bot 调用 (chat)
    """

    name = "coze"
    display_name = "Coze (扣子)"
    auth_type = "token"

    # ── 构造函数 ──
    def __init__(self, account: AccountConfig):
        self.account = account
        self._token: str = account.token
        self._cookie: str = account.cookie or ""
        self._base_url: str = (
            COZE_BASE_COM if account.user_id == "global" else COZE_BASE_CN
        )
        self._transport = APIReverseTransport()
        self._last_validated: float = 0.0

        # 会话状态
        self._conversation_id: str = ""
        self._bot_ids: dict[str, str] = {}  # model_name → bot_id
        self._cached_bots: list[dict] = []
        self._bots_expire: float = 0.0

    # ── Auth ──
    def _has_token(self) -> bool:
        return bool(self._token and self._token.strip())

    async def _ensure_auth(self) -> str:
        """返回有效的 Bearer Token"""
        if not self._has_token():
            raise AuthError(
                "Coze Personal Access Token (PAT) 未配置。\n"
                "获取方式: coze.cn → 个人设置 → API → 个人访问令牌\n"
                "需要权限: Bot 调用 (chat)"
            )
        return self._token

    async def _get_headers(self) -> dict:
        token = await self._ensure_auth()
        return {
            **FAKE_HEADERS,
            "Authorization": f"Bearer {token}",
        }

    # ── Bot 管理 ──
    async def _resolve_bot_id(self, model: str) -> str:
        """模型名 → Bot ID 解析

        优先级:
        1. account.models 中的配置: "bot_name:bot_id" 格式
        2. model_mappings 中的映射
        3. 缓存中的自动发现列表
        4. 重新请求 Bot 列表
        """
        # 1. 检查 account.models 中的 "bot_name:bot_id" 格式
        for entry in self.account.models:
            if ":" in entry:
                bot_name, bot_id = entry.split(":", 1)
                if bot_name.strip() == model or bot_id.strip() == model:
                    return bot_id.strip()

        # 2. 检查缓存
        if model in self._bot_ids:
            return self._bot_ids[model]

        # 3. 如果 model 本身就是 bot_id (纯数字)
        if model.isdigit() or re.match(r"^\d{10,}$", model):
            return model

        # 4. 拉取 Bot 列表
        bots = await self._fetch_bot_list()
        for bot in bots:
            bot_name = bot.get("name", "")
            bot_id = str(bot.get("bot_id", ""))
            if bot_name.lower() == model.lower() or bot_id == model:
                self._bot_ids[model] = bot_id
                self._bot_ids[bot_name] = bot_id
                return bot_id

        # 5. 模糊匹配
        for bot in bots:
            bot_name = bot.get("name", "").lower()
            if model.lower() in bot_name or bot_name in model.lower():
                bot_id = str(bot.get("bot_id", ""))
                self._bot_ids[model] = bot_id
                logger.info(f"[Coze] Fuzzy matched '{model}' → bot '{bot.get('name')}' ({bot_id})")
                return bot_id

        raise ProviderError(
            f"未找到 Bot: {model}。可用 Bot: "
            + ", ".join(b.get("name", "") for b in bots[:10])
            + "\n提示: 在 account.models 中用 '模型名:bot_id' 格式直接指定 Bot ID"
        )

    async def _fetch_bot_list(self) -> list[dict]:
        """获取已发布的 Bot 列表 (带缓存)"""
        now = time.time()
        if self._cached_bots and (now - self._bots_expire < 300):
            return self._cached_bots

        headers = await self._get_headers()
        try:
            response = await self._transport.get(
                url=f"{self._base_url}/v1/space/publish/bots",
                headers=headers,
                timeout=15,
            )
            if response.status == 200:
                data = await response.json()
                bots_data = data.get("data", {})
                bots = bots_data.get("space_bots", bots_data.get("bots", [])) or []
                self._cached_bots = bots
                self._bots_expire = now
                logger.info(f"[Coze] Fetched {len(bots)} bots")
                return bots
            elif response.status == 401:
                raise AuthError("Coze Token 无效或已过期")
        except AuthError:
            raise
        except Exception as e:
            logger.warning(f"[Coze] Failed to fetch bot list: {e}")

        return self._cached_bots  # 返回过期缓存

    # ── 消息格式转换 ──
    @staticmethod
    def _convert_messages(messages: list) -> list[dict]:
        """OpenAI message format → Coze additional_messages format

        Coze additional_messages 格式:
        [
            {"role": "user", "content": "hello", "content_type": "text"},
            {"role": "assistant", "content": "hi", "content_type": "text"},
        ]

        跳过 system 消息（Coze 不支持 system role，用 Bot 提示代替）。
        """
        result = []
        for msg in messages:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")

            if role == "system":
                continue  # Coze 不支持 system message

            if isinstance(content, list):
                # 多模态消息
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    else:
                        text_parts.append(str(part))
                content = "".join(text_parts)

            result.append({
                "role": role,
                "content": str(content),
                "content_type": "text",
            })

        return result

    # ── 健康检查 ──
    async def health_check(self) -> bool:
        """使用 GET /v1/user/me 验证 Token 有效性"""
        if not self._has_token():
            return False

        try:
            headers = await self._get_headers()
            response = await self._transport.get(
                url=f"{self._base_url}/v1/user/me",
                headers=headers,
                timeout=10,
            )
            self._last_validated = time.time()
            return response.status == 200
        except Exception as e:
            logger.debug(f"[Coze] Health check: {e}")
            return False

    # ── 模型列表 ──
    async def list_models(self) -> list[str]:
        """返回可用模型 (Bot 名称) 列表"""
        models = list(DEFAULT_MODELS)

        # 尝试从 Bot 列表获取更多模型
        try:
            bots = await self._fetch_bot_list()
            for bot in bots:
                name = bot.get("name", "")
                if name and name not in models:
                    models.append(name)
        except Exception:
            pass

        return models

    # ── 非流式对话 ──
    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        """非流式对话 — 收集流内容后返回"""
        try:
            headers = await self._get_headers()
            bot_id = await self._resolve_bot_id(request.model)
            messages = self._convert_messages(request.messages)

            payload = {
                "bot_id": bot_id,
                "user_id": request.user or f"webapi_{_random_id()[:8]}",
                "stream": True,  # 即使是非流式，也走流式收集
                "auto_save_history": True,
                "additional_messages": messages,
                "conversation_id": self._conversation_id or "",
            }

            logger.info(
                f"[Coze] Non-stream request: model={request.model}, "
                f"bot_id={bot_id}, msgs={len(messages)}"
            )

            handler = CozeStreamHandler(request.model)

            async for raw_bytes in self._transport.post_stream_raw(
                url=f"{self._base_url}/v3/chat",
                headers=headers,
                json_data=payload,
                timeout=120,
            ):
                for chunk in handler.feed_bytes(raw_bytes):
                    pass  # 收集内容，等流结束后组装

            final = handler.flush()
            full_content = "".join(handler._content_parts)

            if handler._has_error:
                raise ProviderError(handler._error_msg or "Coze chat failed")

            self._conversation_id = handler.conversation_id or self._conversation_id

            return ProviderResponse(
                status_code=200,
                data={
                    "content": full_content,
                    "conversation_id": self._conversation_id,
                    "model": request.model,
                },
                session_id=self._conversation_id,
                headers={"content-type": "application/json"},
            )

        except (AuthError, ProviderError, RateLimitError):
            raise
        except Exception as e:
            logger.error(f"[Coze] chat_completion failed: {e}")
            raise ProviderError(f"Coze chat failed: {e}")

    # ── 流式对话 ──
    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话 — 实时 SSE 输出"""
        try:
            headers = await self._get_headers()
            bot_id = await self._resolve_bot_id(request.model)
            messages = self._convert_messages(request.messages)

            payload = {
                "bot_id": bot_id,
                "user_id": request.user or f"webapi_{_random_id()[:8]}",
                "stream": True,
                "auto_save_history": True,
                "additional_messages": messages,
                "conversation_id": self._conversation_id or "",
            }

            logger.info(
                f"[Coze] Stream request: model={request.model}, "
                f"bot_id={bot_id}, msgs={len(messages)}"
            )

            handler = CozeStreamHandler(request.model)
            has_content = False

            async for raw_bytes in self._transport.post_stream_raw(
                url=f"{self._base_url}/v3/chat",
                headers=headers,
                json_data=payload,
                timeout=120,
            ):
                for chunk in handler.feed_bytes(raw_bytes):
                    has_content = True
                    yield chunk

            # 流结束
            final = handler.flush()
            if handler._has_error:
                raise ProviderError(handler._error_msg or "Coze stream failed")

            self._conversation_id = handler.conversation_id or self._conversation_id

            # 如果没有任何内容，至少发一个空 chunk
            if not has_content:
                yield StreamChunk(
                    content="",
                    reasoning_content="",
                    model=request.model,
                    finish_reason="stop",
                )
            else:
                yield final

        except (AuthError, ProviderError, RateLimitError):
            raise
        except Exception as e:
            logger.error(f"[Coze] chat_completion_stream failed: {e}")
            yield StreamChunk(
                content="",
                reasoning_content="",
                model=request.model,
                finish_reason="error",
            )

    # ── 会话管理 ──
    async def create_session(self) -> str:
        self._conversation_id = ""
        return f"coze_{_random_id()}"

    async def delete_session(self, session_id: str) -> bool:
        # Coze 不提供删除 conversation 的 API，仅清除本地引用
        self._conversation_id = ""
        return True

    # ── Token 刷新 ──
    async def refresh_token(self) -> bool:
        # PAT 永不过期，无需刷新
        return True

    # ── 登录 ──
    async def login(self) -> str:
        await self._ensure_auth()
        return self._token
