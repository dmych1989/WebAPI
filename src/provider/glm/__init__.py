# -*- coding: utf-8 -*-
"""
GLM (智谱AI) Provider Adapter

网页 API 协议:
- Base URL: https://bigmodel.cn
- 认证: Cookie（登录后的 session cookie）
- 对话: POST /api/bigmodel/chat (智谱 BigModel API)
- 模型: glm-4-plus, glm-4-flash, glm-4-air, glm-z1-air

注：此 Provider 是为智谱 AI 网页版大模型对话服务设计的基础实现。
由于智谱官网 API 协议可能经常更新，需要从浏览器 DevTools 抓包验证。
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


GLM_BASE = "https://bigmodel.cn"

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": GLM_BASE,
    "Referer": GLM_BASE + "/",
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
    "glm-4-plus",
    "glm-4-flash",
    "glm-4-air",
    "glm-4-airx",
    "glm-z1-air",
    "glm-zero-preview",
]


@ProviderRegistry.register("glm")
class GLMProvider(BaseProvider):
    """智谱 AI (GLM) 网页 API 适配器"""

    name = "glm"
    display_name = "智谱 GLM"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._cookie: Optional[str] = account.cookie or account.token
        self._transport = APIReverseTransport()
        self._session_validated: float = 0
        self._session_ttl: int = 300
        self._conversation_id: Optional[str] = None

    # ---- Auth ----

    async def login(self) -> str:
        """验证 Cookie / Token 有效性

        Returns:
            有效的凭证字符串

        Raises:
            AuthError: 当凭证无效或未配置时
        """
        if not self._cookie:
            raise AuthError(
                "GLM 凭证未配置。请编辑 config/config.yaml 中的 providers.glm.accounts[0].cookie "
                "（或 token），或运行 python -m src.login glm 自动登录提取。"
            )

        # 命中本地缓存（避免频繁验证）
        now = time.time()
        if self._session_validated and (now - self._session_validated) < self._session_ttl:
            return self._cookie

        # 调用 /api/user 验证 Cookie
        http_session = await self._transport._get_session()
        try:
            async with http_session.get(
                f"{GLM_BASE}/api/user",
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    self._session_validated = 0
                    raise AuthError(
                        "GLM Cookie/Token 已失效（HTTP 401）。"
                        "请运行 python -m src.login glm 重新登录。"
                    )
                if resp.status != 200:
                    self._session_validated = 0
                    raise AuthError(
                        f"GLM 凭证验证失败: HTTP {resp.status}。"
                        "请运行 python -m src.login glm 重新登录。"
                    )
                # 验证通过
                self._session_validated = now
                logger.info("[GLM] Cookie validated via /api/user (200 OK)")
                return self._cookie
        except aiohttp.ClientError as e:
            raise ProviderError(
                f"GLM 网络错误: {e}", provider="glm"
            ) from e

    def _build_headers(self) -> dict[str, str]:
        """构造带 Cookie 的请求头"""
        headers = dict(FAKE_HEADERS)
        headers["Cookie"] = self._cookie or ""
        return headers

    # ---- Chat ----

    async def _call_chat(
        self,
        request: ChatCompletionRequest,
        actual_model: str,
    ) -> dict[str, Any]:
        """调用智谱对话 API（核心方法）"""
        await self.login()
        if not self._conversation_id:
            self._conversation_id = uuid.uuid4().hex

        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant", "system")
        ]
        if not messages:
            raise ProviderError("No valid messages in request", provider="glm")

        payload = {
            "conversation_id": self._conversation_id,
            "model": actual_model,
            "messages": messages,
            "stream": request.stream,
        }

        http_session = await self._transport._get_session()
        try:
            async with http_session.post(
                f"{GLM_BASE}/api/bigmodel/chat",
                json=payload,
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 401:
                    self._session_validated = 0
                    raise AuthError(
                        "GLM 认证失败（HTTP 401）。请重新登录。"
                    )
                if resp.status == 429:
                    raise ProviderError(
                        "GLM 限流（HTTP 429）", provider="glm", status_code=429
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise ProviderError(
                        f"GLM API error: HTTP {resp.status} — {body[:200]}",
                        provider="glm",
                        status_code=resp.status,
                    )
                return {"response": resp, "session": http_session}
        except aiohttp.ClientError as e:
            raise ProviderError(
                f"GLM 网络错误: {e}", provider="glm"
            ) from e

    async def _parse_sse_text(self, raw: str) -> str:
        """解析智谱 SSE 流，提取所有 content 字段拼接"""
        parts: list[str] = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                continue
            # 智谱格式: {"data": {"choices": [{"delta": {"content": "..."}}]}}
            choices = (
                obj.get("data", {}).get("choices")
                or obj.get("choices")
                or []
            )
            for c in choices:
                delta = c.get("delta", {}) or {}
                content = delta.get("content", "")
                if content:
                    parts.append(content)
                # 兼容非流式字段
                if not content:
                    content = c.get("message", {}).get("content", "")
                    if content:
                        parts.append(content)
        return "".join(parts)

    def _resolve_actual_model(self, request: ChatCompletionRequest) -> str:
        """从 request.model 推断实际模型名（GLM 端点接受 GLM 模型名）"""
        model = (request.model or "").strip()
        if not model:
            return self.account.models[0] if self.account.models else DEFAULT_MODELS[0]
        return model

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        """非流式对话"""
        actual_model = self._resolve_actual_model(request)
        result = await self._call_chat(request, actual_model)
        resp = result["response"]
        try:
            raw = await resp.text()
        finally:
            await resp.release()
        content = await self._parse_sse_text(raw)
        if not content:
            try:
                obj = json.loads(raw)
                content = (
                    obj.get("data", {}).get("content")
                    or obj.get("content")
                    or ""
                )
            except (json.JSONDecodeError, ValueError):
                pass
        return ProviderResponse(
            status_code=200,
            data={
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": actual_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
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
        actual_model = self._resolve_actual_model(request)
        result = await self._call_chat(request, actual_model)
        resp = result["response"]
        try:
            async for line_bytes in resp.content:
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue
                choices = (
                    obj.get("data", {}).get("choices")
                    or obj.get("choices")
                    or []
                )
                for c in choices:
                    delta = c.get("delta", {}) or {}
                    content = delta.get("content", "")
                    if not content:
                        content = c.get("message", {}).get("content", "")
                    if content:
                        yield StreamChunk(
                            content=content, finish_reason=None, model=actual_model
                        )
        finally:
            await resp.release()

    # ---- Models ----

    async def list_models(self) -> list[str]:
        return self.account.models or DEFAULT_MODELS

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            return True
        except Exception as e:
            logger.debug(f"[GLM] health_check failed: {type(e).__name__}: {e}")
            return False
