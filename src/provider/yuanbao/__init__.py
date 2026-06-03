# -*- coding: utf-8 -*-
"""
Yuanbao (腾讯元宝) Provider Adapter

网页 API 协议:
- Base URL: https://yuanbao.tencent.com
- 认证: Cookie（登录后的 session cookie）
- 对话: POST /api/chat（SSE 流）
- 模型: hunyuan-pro, hunyuan-turbo, hunyuan-lite

注意：腾讯元宝使用了较强的反爬机制，可能需要 Browser Drive 模式。
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

YUANBAO_BASE = "https://yuanbao.tencent.com"
YUANBAO_CHAT_URL = f"{YUANBAO_BASE}/api/chat/send"

FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://yuanbao.tencent.com",
    "Referer": "https://yuanbao.tencent.com/chat/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

DEFAULT_MODELS = [
    "hunyuan-pro",
    "hunyuan-turbo",
    "hunyuan-lite",
    "hunyuan-t1",
]


def _random_hex(length: int) -> str:
    return uuid.uuid4().hex[:length]


@ProviderRegistry.register("yuanbao")
class YuanbaoProvider(BaseProvider):
    """腾讯元宝 (Yuanbao) 网页 API 适配器"""

    name = "yuanbao"
    display_name = "腾讯元宝 (Yuanbao)"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._cookie: Optional[str] = account.cookie or account.token
        self._transport = APIReverseTransport()
        self._session_validated: float = 0
        self._x_id: Optional[str] = None
        self._x_token: Optional[str] = None

    # ---- Auth ----

    async def login(self) -> str:
        """验证 Cookie 并提取认证 headers

        注意：旧 /api/chat 端点已废弃，现仅以 cookie 的 redirect 行为作为轻量探活。
        - 200 → cookie 有效
        - 302/301 重定向到 login → cookie 失效
        - 其他 → 网络问题，假定有效
        """
        if not self._cookie:
            raise AuthError(
                "Yuanbao Cookie 未配置。"
                "请运行: python -m src.login yuanbao 重新登录获取 Cookie。"
            )

        # 防御：检查 cookie 是否还是未解密的密文
        if isinstance(self._cookie, str) and self._cookie.startswith("enc:v1:"):
            raise AuthError(
                "Yuanbao Cookie 是加密密文，但密钥不匹配（无法解密）。"
                "请运行: python -m src.login yuanbao 重新登录。"
            )

        now = time.time()
        if self._session_validated and self._x_token and (now - self._session_validated) < 600:
            return self._cookie

        logger.info("[Yuanbao] Validating session + extracting tokens...")

        session = await self._transport._get_session()

        # 1. 访问首页获取 X-ID / X-Token（轻量探活）
        async with session.get(
            f"{YUANBAO_BASE}/chat/",
            headers={
                "Cookie": self._cookie,
                **{k: v for k, v in FAKE_HEADERS.items() if k != "Content-Type"},
            },
            allow_redirects=False,
        ) as resp:
            if resp.status in (302, 301):
                location = resp.headers.get("Location", "")
                if "login" in location.lower():
                    raise AuthError(
                        "Yuanbao Cookie 已失效（重定向到登录页）。"
                        "请运行: python -m src.login yuanbao 重新登录。"
                    )

            if resp.status == 200:
                # 尝试从页面中提取 X-ID / X-Token
                text = await resp.text()
                import re
                x_id_match = re.search(r'"x_id"\s*:\s*"([^"]+)"', text)
                x_token_match = re.search(r'"x_token"\s*:\s*"([^"]+)"', text)
                if x_id_match:
                    self._x_id = x_id_match.group(1)
                if x_token_match:
                    self._x_token = x_token_match.group(1)

                # 也检查 cookies 中是否有 hy_token
                for cookie_str in resp.headers.getall("Set-Cookie") or []:
                    if "hy_token" in cookie_str:
                        m = re.search(r"hy_token=([^;]+)", cookie_str)
                        if m:
                            self._x_token = m.group(1)
            else:
                # 200 之外的首页响应 — 网络/服务端问题，不当作凭证失效
                logger.warning(
                    f"[Yuanbao] Home page returned HTTP {resp.status}, "
                    f"treating as transient issue."
                )

        self._session_validated = now
        logger.info(
            f"[Yuanbao] Session validated "
            f"(x_id={'✓' if self._x_id else '✗'} x_token={'✓' if self._x_token else '✗'})"
        )
        return self._cookie

    def _auth_headers(self) -> dict:
        """构建认证 headers"""
        headers = {"Cookie": self._cookie}
        if self._x_id:
            headers["X-ID"] = self._x_id
        if self._x_token:
            headers["X-Token"] = self._x_token
        return headers

    # ---- Messages → Prompt ----

    def _messages_to_prompt(self, request: ChatCompletionRequest) -> str:
        """OpenAI messages → 元宝 prompt 格式"""
        parts: list[str] = []
        for msg in request.messages:
            role = msg.role
            content = self._get_text(msg)

            if role == "system":
                parts.append(f"系统: {content}")
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(content)
            elif role == "tool":
                parts.append(f"[工具返回] {content}")

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
            return "hunyuan-pro"
        if "turbo" in model_lower:
            return "hunyuan-turbo"
        if "t1" in model_lower:
            return "hunyuan-t1"
        if "lite" in model_lower:
            return "hunyuan-lite"
        return self.account.models[0] if self.account.models else "hunyuan-pro"

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """非流式对话"""
        await self.login()
        model = self._resolve_model(request)
        prompt = self._messages_to_prompt(request)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "temperature": request.temperature or 0.8,
            "max_tokens": request.max_tokens or 4096,
            "chat_id": _random_hex(16),
            "plugin": "Adaptive",
        }

        http_session = await self._transport._get_session()

        async with http_session.post(
            YUANBAO_CHAT_URL,
            json=payload,
            headers={
                **FAKE_HEADERS,
                **self._auth_headers(),
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Yuanbao API error: HTTP {resp.status} — {text[:200]}",
                    provider="yuanbao",
                )

            data = await resp.json()

            # 提取回复内容
            content = ""
            if "data" in data:
                d = data["data"]
                if isinstance(d, dict):
                    content = d.get("message", "") or d.get("reply", "") or d.get("content", "")
                elif isinstance(d, str):
                    content = d
            elif "reply" in data:
                content = data["reply"]
            elif "choices" in data:
                content = data["choices"][0].get("message", {}).get("content", "")

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
            "prompt": prompt,
            "stream": True,
            "temperature": request.temperature or 0.8,
            "max_tokens": request.max_tokens or 4096,
            "chat_id": _random_hex(16),
            "plugin": "Adaptive",
        }

        logger.info(f"[Yuanbao] Stream: model={model}")

        http_session = await self._transport._get_session()

        async with http_session.post(
            YUANBAO_CHAT_URL,
            json=payload,
            headers={
                **FAKE_HEADERS,
                **self._auth_headers(),
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Yuanbao API error: HTTP {resp.status} — {text[:200]}",
                    provider="yuanbao",
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

            logger.debug(f"[Yuanbao] Stream done: {len(gathered)} chars")

    def _extract_delta_content(self, parsed: dict) -> str:
        """从 SSE chunk 提取 delta 内容"""
        # 腾讯元宝的 SSE 可能是多种格式
        if "data" in parsed:
            d = parsed["data"]
            if isinstance(d, dict):
                return d.get("message", "") or d.get("content", "")
            if isinstance(d, str):
                return d
        if "choices" in parsed:
            delta = parsed["choices"][0].get("delta", {})
            return delta.get("content", "")
        if "message" in parsed:
            return str(parsed["message"])
        if "content" in parsed:
            return str(parsed["content"])
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