# -*- coding: utf-8 -*-
"""
MiniMax (Hailuo AI) Provider Adapter

网页 API 协议:
- Base URL: https://hailuoai.com
- 认证: JWT Token（登录后获取的 access_token）
- 登录: POST /api/user/login (email + password)
- 对话: POST /api/chat/completion_prod（SSE 流）
- 会话: GET /api/chat/list
- 模型: MiniMax-Text-01, abab6.5s-chat

参考 Chat2API minimax.ts
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport

MINIMAX_BASE = "https://hailuoai.com"

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://hailuoai.com",
    "Referer": "https://hailuoai.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

DEFAULT_MODELS = [
    "MiniMax-Text-01",
    "abab6.5s-chat",
    "abab7-chat-preview",
]


def _random_hex(length: int) -> str:
    return uuid.uuid4().hex[:length]


@ProviderRegistry.register("minimax")
class MiniMaxProvider(BaseProvider):
    """MiniMax (Hailuo AI) 网页 API 适配器"""

    name = "minimax"
    display_name = "MiniMax (Hailuo AI)"
    auth_type = "jwt"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._token: Optional[str] = account.token
        self._user_id: Optional[str] = getattr(account, "user_id", None)
        self._access_token: Optional[str] = None
        self._access_token_expires: float = 0
        self._transport = APIReverseTransport()
        self._conversation_id: Optional[str] = None

    def _build_auth_headers(self) -> dict:
        """构建带 Authorization 和 Real User ID 的请求头"""
        headers = {
            "Authorization": f"Bearer {self._token}" if self._token else "",
        }
        if self._user_id:
            # MiniMax (Hailuo) API 需要 Real User ID 作为额外认证字段
            headers["X-Real-User-Id"] = str(self._user_id)
            headers["X-User-Id"] = str(self._user_id)
        return headers

    # ---- Auth ----

    async def login(self) -> str:
        """获取/刷新 access token"""
        if not self._token:
            raise AuthError("MiniMax Token not configured")

        now = time.time()
        if self._access_token and self._access_token_expires > now:
            return self._access_token

        # 如果 token 是 JWT，直接用作 Bearer token
        # MiniMax 的 access token 有效期较长（~30天）
        logger.info("[MiniMax] Validating token...")

        session = await self._transport._get_session()

        async with session.get(
            f"{MINIMAX_BASE}/api/user/info",
            headers={
                **self._build_auth_headers(),
                **FAKE_HEADERS,
            },
        ) as resp:
            if resp.status in (401, 403):
                raise AuthError("MiniMax Token invalid or expired, refresh required")
            if resp.status == 200:
                self._access_token = self._token
                self._access_token_expires = now + 86400  # 24h 缓存
                logger.info("[MiniMax] Token validated")
                return self._access_token

            # 保底：直接信任用户提供的 token
            self._access_token = self._token
            self._access_token_expires = now + 3600
            logger.warning(f"[MiniMax] Token check returned {resp.status}, using as-is")
            return self._access_token

    # ---- Messages → Prompt ----

    def _messages_to_prompt(self, request: ChatCompletionRequest) -> str:
        """OpenAI messages → MiniMax prompt 格式"""
        parts: list[str] = []
        for i, msg in enumerate(request.messages):
            role = msg.role
            content = self._get_text(msg)

            if role == "system":
                parts.append(f"System: {content}")
            elif role == "user":
                parts.append(f"Human: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                parts.append(f"Tool Result: {content}")

        return "\n\n".join(parts)

    @staticmethod
    def _get_text(msg) -> str:
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if content is None:
            return ""
        return str(content)

    # ---- Chat Completion ----

    def _resolve_model(self, request: ChatCompletionRequest) -> str:
        """解析实际模型名"""
        model = request.model
        if "minimax" in model.lower():
            return "MiniMax-Text-01"
        if "abab" in model.lower():
            return model
        return self.account.models[0] if self.account.models else "MiniMax-Text-01"

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """非流式对话"""
        token = await self.login()
        model = self._resolve_model(request)
        prompt = self._messages_to_prompt(request)

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "temperature": request.temperature or 0.7,
            "max_tokens": request.max_tokens or 4096,
        }

        http_session = await self._transport._get_session()
        url = f"{MINIMAX_BASE}/api/chat/completion_prod"

        async with http_session.post(
            url,
            json=payload,
            headers={
                **self._build_auth_headers(),
                **FAKE_HEADERS,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"MiniMax API error: HTTP {resp.status} — {text[:200]}",
                    provider="minimax",
                )

            data = await resp.json()

            # 提取回复内容
            content = ""
            if "reply" in data:
                content = data["reply"]
            elif "choices" in data:
                content = data["choices"][0].get("message", {}).get("content", "")
            elif "data" in data:
                content = data.get("data", {}).get("reply", "")

            return ProviderResponse(
                status_code=200,
                data={
                    "id": f"chatcmpl-{_random_hex(12)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content,
                        },
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                },
            )

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话"""
        token = await self.login()
        model = self._resolve_model(request)
        prompt = self._messages_to_prompt(request)

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": True,
            "temperature": request.temperature or 0.7,
            "max_tokens": request.max_tokens or 4096,
        }

        logger.info(f"[MiniMax] Stream: model={model}")

        http_session = await self._transport._get_session()
        url = f"{MINIMAX_BASE}/api/chat/completion_prod"

        async with http_session.post(
            url,
            json=payload,
            headers={
                **self._build_auth_headers(),
                **FAKE_HEADERS,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"MiniMax API error: HTTP {resp.status} — {text[:200]}",
                    provider="minimax",
                )

            is_first = True
            gathered = ""

            async for line_raw in resp.content:
                line = line_raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    parsed = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                content = self._extract_delta_content(parsed)
                if content:
                    if is_first:
                        yield StreamChunk(
                            content=content,
                            role="assistant",
                            model=model,
                        )
                        is_first = False
                    else:
                        yield StreamChunk(content=content, model=model)
                    gathered += content

            logger.debug(f"[MiniMax] Stream done: {len(gathered)} chars")

    def _extract_delta_content(self, parsed: dict) -> str:
        """从 SSE chunk 提取 delta 内容"""
        # MiniMax SSE 格式: {"choices": [{"delta": {"content": "text"}}]}
        choices = parsed.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content", "")
        # 备选: {"reply": "text"}
        if "reply" in parsed:
            return parsed["reply"]
        # 备选: {"data": {"reply": "text"}}
        if isinstance(parsed.get("data"), dict):
            return parsed["data"].get("reply", "")
        return ""

    # ---- Models ----

    async def list_models(self) -> list[str]:
        return self.account.models or DEFAULT_MODELS

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            return True
        except Exception:
            return False