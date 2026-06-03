# -*- coding: utf-8 -*-
"""
Coze Provider Adapter — 字节跳动 Coze 平台

网页 API 协议:
- Base URL: https://www.coze.cn (国内) / https://www.coze.com (国际)
- 认证: API Key (Bearer Token) 或 Cookie（登录后的 session cookie）
- 对话: POST /api/conversation/chat (SSE 流)
- 模型: coze-chat, coze-realtime, coze-embedding

注意：Coze 的 API 接口可能会变化，需要从浏览器 DevTools 抓包验证。
"""

from __future__ import annotations

import asyncio
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

COZE_BASE = "https://www.coze.cn"

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": COZE_BASE,
    "Referer": COZE_BASE + "/",
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
    "coze-chat",
    "coze-chat-pro",
    "coze-realtime",
    "coze-embedding",
]


def _random_hex(length: int = 16) -> str:
    return uuid.uuid4().hex[:length]


@ProviderRegistry.register("coze")
class CozeProvider(BaseProvider):
    """Coze 网页 API 适配器"""

    name = "coze"
    display_name = "Coze (扣子)"
    auth_type = "token"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._token: Optional[str] = account.token
        self._cookie: Optional[str] = account.cookie
        self._transport = APIReverseTransport()
        self._session_validated: float = 0
        self._conversation_id: Optional[str] = None
        self._bot_id: Optional[str] = None

    # ---- Auth ----

    async def login(self) -> str:
        """验证 Token 有效性"""
        if not self._token and not self._cookie:
            raise AuthError("Coze API Key or Cookie not configured")
        return self._token or self._cookie or ""

    async def _ensure_auth(self) -> str:
        """确保登录并返回有效 token/cookie"""
        if self._token:
            return self._token
        if not self._cookie:
            return await self.login()
        return self._cookie

    async def _get_headers(self) -> dict:
        """构建请求头"""
        auth = await self._ensure_auth()
        headers = dict(FAKE_HEADERS)
        if self._token:
            headers["Authorization"] = f"Bearer {auth}"
        else:
            headers["Cookie"] = auth
        return headers

    # ---- 抽象方法实现 ----

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        """非流式对话"""
        try:
            headers = await self._get_headers()
            # 获取最后一条用户消息
            user_content = ""
            for msg in reversed(request.messages):
                if msg.role == "user":
                    user_content = msg.content
                    break

            payload = {
                "bot_id": self._bot_id or "",
                "user": request.user or "webapi_user",
                "query": user_content,
                "stream": False,
                "conversation_id": self._conversation_id or "",
            }

            logger.info(f"[Coze] 非流式请求: model={request.model}")

            response = await self._transport.post(
                url=f"{COZE_BASE}/api/conversation/chat",
                headers=headers,
                json_data=payload,
                timeout=120,
            )

            if response.status_code == 401:
                raise AuthError("Coze Token/Cookie expired")

            if response.status_code != 200:
                raise ProviderError(
                    f"Coze API error: {response.status_code}",
                )

            data = response.data or {}
            content = data.get("data", {}).get("answer", data.get("answer", ""))
            conversation_id = data.get("data", {}).get(
                "conversation_id", data.get("conversation_id", "")
            )

            if conversation_id:
                self._conversation_id = conversation_id

            return ProviderResponse(
                status_code=200,
                data={
                    "content": content,
                    "conversation_id": self._conversation_id,
                    "model": request.model,
                },
                session_id=self._conversation_id,
                headers={"content-type": "application/json"},
            )

        except AuthError:
            raise
        except Exception as e:
            logger.error(f"[Coze] chat_completion failed: {e}")
            raise ProviderError(f"Coze chat failed: {e}")

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话"""
        try:
            headers = await self._get_headers()
            user_content = ""
            for msg in reversed(request.messages):
                if msg.role == "user":
                    user_content = msg.content
                    break

            payload = {
                "bot_id": self._bot_id or "",
                "user": request.user or "webapi_user",
                "query": user_content,
                "stream": True,
                "conversation_id": self._conversation_id or "",
            }

            logger.info(f"[Coze] 流式请求: model={request.model}")

            async for chunk_data in self._transport.post_stream(
                url=f"{COZE_BASE}/api/conversation/chat",
                headers=headers,
                json_data=payload,
                timeout=120,
            ):
                if isinstance(chunk_data, dict) and chunk_data.get("content"):
                    yield StreamChunk(
                        content=chunk_data.get("content", ""),
                        reasoning_content="",
                        model=request.model,
                    )
                elif isinstance(chunk_data, str):
                    yield StreamChunk(
                        content=chunk_data,
                        reasoning_content="",
                        model=request.model,
                    )

            # 发送结束标记
            yield StreamChunk(
                content="",
                reasoning_content="",
                model=request.model,
                finish_reason="stop",
            )

        except AuthError:
            raise
        except Exception as e:
            logger.error(f"[Coze] chat_completion_stream failed: {e}")
            raise ProviderError(f"Coze stream failed: {e}")

    async def list_models(self) -> list[str]:
        """返回此 Provider 支持的模型列表"""
        return DEFAULT_MODELS

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            if not self._token and not self._cookie:
                logger.debug("[Coze] No credentials configured, skip health check")
                return False

            headers = await self._get_headers()
            response = await self._transport.get(
                url=f"{COZE_BASE}/api/me",
                headers=headers,
                timeout=15,
            )
            self._session_validated = time.time()
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"[Coze] Health check failed: {e}")
            return False

    # ---- 可选方法 ----

    async def refresh_token(self) -> bool:
        """尝试刷新 Token"""
        return False  # Coze API Key 不需要刷新

    async def create_session(self) -> str:
        """创建对话会话"""
        self._conversation_id = f"coze_{_random_hex()}"
        return self._conversation_id

    async def delete_session(self, session_id: str) -> bool:
        """删除对话会话"""
        if self._conversation_id == session_id:
            self._conversation_id = None
        return True
