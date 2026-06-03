# -*- coding: utf-8 -*-
"""
Doubao (豆包) Provider Adapter — 字节跳动

网页 API 协议:
- Base URL: https://www.doubao.com
- 认证: Cookie（登录后的 session cookie）
- 对话: POST /chat/completion（SSE 流）
- 模型: doubao-pro-32k, doubao-lite-32k

注意：豆包的 API 接口可能会变化，需要从浏览器 DevTools 抓包验证。
参考 AIClient2API 的 doubao 策略模式。
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

DOUBAO_BASE = "https://www.doubao.com"

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.doubao.com",
    "Referer": "https://www.doubao.com/chat/",
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
    "doubao-pro-32k",
    "doubao-pro-128k",
    "doubao-lite-32k",
    "doubao-lite-128k",
]


def _random_hex(length: int) -> str:
    return uuid.uuid4().hex[:length]


@ProviderRegistry.register("doubao")
class DoubaoProvider(BaseProvider):
    """豆包 (Doubao) 网页 API 适配器"""

    name = "doubao"
    display_name = "豆包 (Doubao)"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._cookie: Optional[str] = account.cookie or account.token
        self._transport = APIReverseTransport()
        self._session_validated: float = 0
        self._conversation_id: Optional[str] = None

    # ---- Auth ----

    async def login(self) -> str:
        """验证 Cookie 有效性"""
        if not self._cookie:
            raise AuthError("Doubao Cookie not configured")

        now = time.time()
        # Cookie 验证缓存 10 分钟
        if self._session_validated and (now - self._session_validated) < 600:
            return self._cookie

        logger.info("[Doubao] Validating session...")

        session = await self._transport._get_session()

        async with session.get(
            f"{DOUBAO_BASE}/chat/",
            headers={
                "Cookie": self._cookie,
                **FAKE_HEADERS,
            },
            allow_redirects=False,
        ) as resp:
            if resp.status in (302, 301) and "login" in str(resp.headers.get("Location", "")):
                raise AuthError("Doubao Cookie expired, please re-login")
            if resp.status == 200:
                self._session_validated = now
                logger.info("[Doubao] Session validated")
                return self._cookie
            # 非 200 也不重定向 = 可能仍然有效
            logger.warning(f"[Doubao] Session check returned {resp.status}, proceeding")
            self._session_validated = now
            return self._cookie

    # ---- Messages → Prompt ----

    def _messages_to_prompt(self, request: ChatCompletionRequest) -> str:
        """OpenAI messages → 豆包 prompt 格式"""
        parts: list[str] = []
        for msg in request.messages:
            role = msg.role
            content = self._get_text(msg)

            if role == "system":
                parts.append(f"系统指令: {content}")
            elif role == "user":
                parts.append(f"用户: {content}")
            elif role == "assistant":
                parts.append(f"助手: {content}")
            elif role == "tool":
                parts.append(f"工具结果: {content}")

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
        model_lower = request.model.lower()
        if "pro" in model_lower:
            return "doubao-pro-32k"
        if "lite" in model_lower:
            return "doubao-lite-32k"
        return self.account.models[0] if self.account.models else "doubao-pro-32k"

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """非流式对话"""
        await self.login()
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
            "bot_id": self._get_bot_id(model),
        }

        http_session = await self._transport._get_session()
        url = f"{DOUBAO_BASE}/chat/completion"

        async with http_session.post(
            url,
            json=payload,
            headers={
                "Cookie": self._cookie,
                **FAKE_HEADERS,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Doubao API error: HTTP {resp.status} — {text[:200]}",
                    provider="doubao",
                )

            data = await resp.json()

            # 提取回复内容
            content = data.get("data", {}).get("content", "")
            if not content:
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")

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
        await self.login()
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
            "bot_id": self._get_bot_id(model),
        }

        logger.info(f"[Doubao] Stream: model={model}")

        http_session = await self._transport._get_session()
        url = f"{DOUBAO_BASE}/chat/completion"

        async with http_session.post(
            url,
            json=payload,
            headers={
                "Cookie": self._cookie,
                **FAKE_HEADERS,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Doubao API error: HTTP {resp.status} — {text[:200]}",
                    provider="doubao",
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

            logger.debug(f"[Doubao] Stream done: {len(gathered)} chars")

    def _extract_delta_content(self, parsed: dict) -> str:
        """从 SSE chunk 提取 delta 内容"""
        choices = parsed.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content", "")
        # 备选格式
        if "data" in parsed and isinstance(parsed["data"], dict):
            return parsed["data"].get("content", "")
        if "content" in parsed:
            return str(parsed["content"])
        return ""

    def _get_bot_id(self, model: str) -> str:
        """根据模型获取 bot_id"""
        if "pro" in model.lower():
            return "doubao-pro-bot"
        return "doubao-lite-bot"

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