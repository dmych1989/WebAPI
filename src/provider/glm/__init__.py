# -*- coding: utf-8 -*-
"""
GLM (智谱AI) Provider Adapter — 官方 BigModel OpenAI 兼容 API

官方 API 协议:
- Base URL: https://open.bigmodel.cn/api/paas/v4
- 认证: Authorization: Bearer <api_key>
- 对话: POST /chat/completions（OpenAI 兼容）
- 流式: POST /chat/completions（带 stream=true，SSE 响应）
- 模型: glm-4-plus, glm-4-flash, glm-4-air, glm-z1-air, glm-4-airx, glm-zero-preview

凭证获取:
1. 访问 https://open.bigmodel.cn/ 登录
2. 右上角「API 密钥」→ 「创建新的 API Key」
3. 复制 sk-xxx... 粘贴到 config.yaml 的 providers.glm.accounts[0].token
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport


# 智谱 BigModel 官方 API（OpenAI 兼容）
GLM_API_BASE = "https://open.bigmodel.cn/api/paas/v4"


@ProviderRegistry.register("glm")
class GLMProvider(BaseProvider):
    """智谱 GLM 官方 BigModel OpenAI 兼容 API 适配器"""

    name = "glm"
    display_name = "智谱 GLM"
    auth_type = "token"

    def __init__(self, account: AccountConfig):
        self.account = account
        # 优先 token 字段（API key 形如 sk-xxx），其次 cookie（兼容旧配置）
        self._api_key: Optional[str] = account.token or account.cookie
        self._transport = APIReverseTransport()

    # ---- Auth ----

    async def login(self) -> str:
        """验证 API Key 存在性（实际鉴权在每次请求时由 chatglm.cn 校验）"""
        if not self._api_key:
            raise AuthError(
                "GLM 凭证未配置。请在 config/config.yaml 的 providers.glm.accounts[0].token "
                "填入智谱 API Key（以 sk- 开头），或前往 https://open.bigmodel.cn/ 创建。"
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
        """直接透传模型名（官方 API 接受 glm-* 系列）"""
        model = (request.model or "").strip()
        return model or "glm-4-flash"

    def _build_payload(
        self, request: ChatCompletionRequest, actual_model: str, stream: bool
    ) -> dict[str, Any]:
        """构造 OpenAI 兼容 payload"""
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            content = msg.content
            # 多模态内容（list of parts）原样透传
            messages.append({"role": msg.role, "content": content})

        payload: dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
            "stream": stream,
        }
        # 可选参数透传
        for opt in (
            "temperature",
            "top_p",
            "n",
            "max_tokens",
            "stop",
            "presence_penalty",
            "frequency_penalty",
            "user",
        ):
            v = getattr(request, opt, None)
            if v is not None:
                payload[opt] = v
        return payload

    async def _post_request(
        self, request: ChatCompletionRequest, actual_model: str, stream: bool
    ) -> aiohttp.ClientResponse:
        """发送 POST 请求，返回 aiohttp 响应（调用方负责读取 body）"""
        await self.login()
        url = f"{GLM_API_BASE}/chat/completions"
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
                f"GLM 网络错误: {e}", provider="glm"
            ) from e

        if resp.status == 401:
            await resp.release()
            raise AuthError(
                "GLM 认证失败（HTTP 401）。请检查 API Key 是否正确或已过期。"
            )
        if resp.status == 429:
            body = await resp.text()
            await resp.release()
            raise ProviderError(
                f"GLM 限流（HTTP 429）: {body[:200]}", provider="glm", status_code=429
            )
        if resp.status >= 400:
            body = await resp.text()
            await resp.release()
            raise ProviderError(
                f"GLM API error: HTTP {resp.status} — {body[:300]}",
                provider="glm",
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

        return ProviderResponse(
            status_code=200,
            data=data,  # 官方 API 已经是 OpenAI 格式，直接透传
        )

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

                # OpenAI 格式：choices[].delta
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_delta = delta.get("content") or ""
                reasoning_delta = delta.get("reasoning_content") or ""
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
                    yield StreamChunk(
                        finish_reason=finish_reason, model=actual_model
                    )
        finally:
            await resp.release()

    # ---- Models ----

    async def list_models(self) -> list[str]:
        return [
            "glm-4-plus",
            "glm-4-flash",
            "glm-4-air",
            "glm-4-airx",
            "glm-z1-air",
            "glm-zero-preview",
        ]

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            # 用极简请求验证 API Key 是否有效（/chat/completions 不支持 ping，
            # 改用 /models 端点列出模型，能成功即视为鉴权通过）
            session = await self._transport._get_session()
            async with session.get(
                f"{GLM_API_BASE}/models",
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(f"[GLM] health_check failed: {type(e).__name__}: {e}")
            return False
