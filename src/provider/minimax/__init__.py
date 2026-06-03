# -*- coding: utf-8 -*-
"""
MiniMax Provider Adapter — 官方 OpenAI 兼容 API

官方 API 协议:
- Base URL: https://api.minimaxi.com/v1
- 认证: Authorization: Bearer <api_key>
- 对话: POST /chat/completions（OpenAI 兼容）
- 流式: POST /chat/completions（带 stream=true，SSE 响应）
- 模型: MiniMax-M3, MiniMax-M2.7, MiniMax-M2.7-highspeed, MiniMax-M2.5,
       MiniMax-M2.5-highspeed, MiniMax-M2.1, MiniMax-M2.1-highspeed, MiniMax-M2

凭证获取:
1. 访问 https://platform.minimaxi.com/user-center/basic-information/interface-key
2. 创建新的 API Key（eyJ... JWT 格式）
3. 粘贴到 config.yaml 的 providers.minimax.accounts[0].token

也支持账号级 api_base 自定义，默认为 https://api.minimaxi.com/v1
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Optional

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport


# 官方 OpenAI 兼容 API base
DEFAULT_API_BASE = "https://api.minimaxi.com/v1"

# 新一代官方模型
DEFAULT_MODELS = [
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
    "MiniMax-M2.1-highspeed",
    "MiniMax-M2",
]


@ProviderRegistry.register("minimax")
class MiniMaxProvider(BaseProvider):
    """MiniMax 官方 OpenAI 兼容 API 适配器"""

    name = "minimax"
    display_name = "MiniMax"
    auth_type = "token"

    def __init__(self, account: AccountConfig):
        self.account = account
        # 优先 token 字段（API Key 形如 eyJ...），其次 cookie（兼容旧配置）
        self._api_key: Optional[str] = account.token or account.cookie
        # 账号可自定义 api_base，否则用官方 base
        self._api_base: str = (
            getattr(account, "api_base", None) or DEFAULT_API_BASE
        ).rstrip("/")
        self._transport = APIReverseTransport()

    # ---- Auth ----

    async def login(self) -> str:
        """验证 API Key 存在性"""
        if not self._api_key:
            raise AuthError(
                "MiniMax 凭证未配置。请在 config/config.yaml 的 providers.minimax.accounts[0].token "
                "填入 API Key（eyJ 开头的 JWT），或前往 https://platform.minimaxi.com/user-center/basic-information/interface-key 创建。"
            )
        return self._api_key

    def _build_headers(self) -> dict[str, str]:
        """构造带 Bearer Token 的请求头"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _resolve_actual_model(self, request: ChatCompletionRequest) -> str:
        """直接透传模型名"""
        model = (request.model or "").strip()
        return model or "MiniMax-M2.7-highspeed"

    def _build_payload(
        self, request: ChatCompletionRequest, actual_model: str, stream: bool
    ) -> dict[str, Any]:
        """构造 OpenAI 兼容 payload"""
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
            "stream": stream,
        }
        # 透传 OpenAI 标准可选参数
        for opt in (
            "temperature",
            "top_p",
            "max_tokens",
            "max_completion_tokens",
            "stop",
            "user",
        ):
            v = getattr(request, opt, None)
            if v is not None:
                payload[opt] = v
        # 透传 tools
        if getattr(request, "tools", None):
            payload["tools"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in request.tools]
        return payload

    async def _post_request(
        self, request: ChatCompletionRequest, actual_model: str, stream: bool
    ) -> aiohttp.ClientResponse:
        """发送 POST 请求"""
        await self.login()
        url = f"{self._api_base}/chat/completions"
        payload = self._build_payload(request, actual_model, stream)
        session = await self._transport._get_session()

        try:
            resp = await session.post(
                url,
                json=payload,
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=120),
            )
        except aiohttp.ClientError as e:
            raise ProviderError(
                f"MiniMax 网络错误: {e}", provider="minimax"
            ) from e

        if resp.status == 401:
            await resp.release()
            raise AuthError(
                "MiniMax 认证失败（HTTP 401）。请检查 API Key 是否正确或已过期。"
            )
        if resp.status == 429:
            body = await resp.text()
            await resp.release()
            raise ProviderError(
                f"MiniMax 限流（HTTP 429）: {body[:200]}",
                provider="minimax",
                status_code=429,
            )
        if resp.status >= 400:
            body = await resp.text()
            await resp.release()
            raise ProviderError(
                f"MiniMax API error: HTTP {resp.status} — {body[:300]}",
                provider="minimax",
                status_code=resp.status,
            )
        return resp

    # ---- Chat: 非流式 ----

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        actual_model = self._resolve_actual_model(request)
        resp = await self._post_request(request, actual_model, stream=False)
        try:
            data = await resp.json()
        finally:
            await resp.release()
        return ProviderResponse(status_code=200, data=data)

    # ---- Chat: 流式 ----

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        actual_model = self._resolve_actual_model(request)
        resp = await self._post_request(request, actual_model, stream=True)

        is_first = True
        try:
            async for line_bytes in resp.content:
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    obj = json.loads(data_str)
                except (json.JSONDecodeError, ValueError):
                    continue

                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_delta = delta.get("content") or ""
                # MiniMax M3 支持 reasoning_details（Interleaved Thinking）
                reasoning_delta = ""
                if isinstance(delta.get("reasoning_details"), list):
                    for detail in delta["reasoning_details"]:
                        if isinstance(detail, dict) and detail.get("text"):
                            reasoning_delta += detail["text"]
                finish_reason = choices[0].get("finish_reason")

                if content_delta or reasoning_delta:
                    if is_first:
                        yield StreamChunk(
                            content=content_delta,
                            reasoning_content=reasoning_delta or None,
                            role="assistant",
                            model=actual_model,
                        )
                        is_first = False
                    else:
                        yield StreamChunk(
                            content=content_delta,
                            reasoning_content=reasoning_delta or None,
                            model=actual_model,
                        )

                if finish_reason:
                    yield StreamChunk(finish_reason=finish_reason, model=actual_model)
        finally:
            await resp.release()

    # ---- Models ----

    async def list_models(self) -> list[str]:
        # 优先使用账号级 models 配置，否则用官方模型列表
        if self.account.models:
            return self.account.models
        return DEFAULT_MODELS

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            session = await self._transport._get_session()
            async with session.get(
                f"{self._api_base}/models",
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(f"[MiniMax] health_check failed: {type(e).__name__}: {e}")
            return False
