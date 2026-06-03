# -*- coding: utf-8 -*-
"""
Qwen (通义千问) Provider Adapter

网页 API 协议:
- Base URL: https://chat2-api.qianwen.com
- 认证: tongyi_sso_ticket Cookie
- 对话: POST /api/v2/assistant/chat（SSE 流）
- Session 管理: POST /api/v1/session/page/list, POST /api/v1/session/delete/batch
- 消息格式: JSON messages 数组
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport


QWEN_CHAT2_BASE = "https://chat2-api.qianwen.com"
QWEN_CHAT_SIDE_BASE = "https://chat-side.qianwen.com"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/event-stream, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": "https://www.qianwen.com",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="145", "Not(A:Brand";v="24", "Google Chrome";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Referer": "https://www.qianwen.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}

MODEL_MAP: dict[str, str] = {
    "Qwen3.6": "Qwen",
    "Qwen3.7-Max": "Qwen3.7-Max",
    "Qwen3.5-Flash": "Qwen3.5-Flash",
    "Qwen3-Max": "Qwen3-Max",
    "Qwen3-Max-Thinking-Preview": "Qwen3-Max-Thinking-Preview",
    "Qwen3-Coder": "Qwen3-Coder",
}


def _short_uuid() -> str:
    return uuid.uuid4().hex[:12]


def _random_nonce() -> str:
    from random import choice
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(choice(chars) for _ in range(12))


@ProviderRegistry.register("qwen")
class QwenProvider(BaseProvider):
    """通义千问 网页 API 适配器"""

    name = "qwen"
    display_name = "通义千问"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._ticket: Optional[str] = account.token
        self._transport = APIReverseTransport()

    def _get_auth_headers(self) -> dict[str, str]:
        """构建带 Cookie 的请求头"""
        return {
            "Cookie": f"tongyi_sso_ticket={self._ticket}",
            "Content-Type": "application/json",
            "X-Platform": "pc_tongyi",
            "X-DeviceId": "5b68c267-cd8e-fd0e-148a-18345bc9a104",
            **DEFAULT_HEADERS,
        }

    def _get_params(self, extra: dict = None) -> dict:
        """构建通用 URL 参数"""
        params = {
            "biz_id": "ai_qwen",
            "chat_client": "h5",
            "device": "pc",
            "fr": "pc",
            "pr": "qwen",
            "ut": "5b68c267-cd8e-fd0e-148a-18345bc9a104",
            "la": "zh_CN",
            "tz": "Asia/Shanghai",
            "wv": "1",
            "ve": "1",
        }
        if extra:
            params.update(extra)
        return params

    def _map_model(self, model: str) -> str:
        return MODEL_MAP.get(model, model)

    # ---- Auth ----

    async def login(self) -> str:
        """验证 ticket 有效性

        重要：404 不等于"认证失败"，可能是端点变更或网络问题。
        - 401 → 凭证失效，提示用户重新登录
        - 403 → 被风控，提示用户检查账号
        - 200 → 凭证有效
        - 其他状态码 → 网络/服务端问题，不当作凭证失效（避免无限重试）
        """
        if not self._ticket:
            raise AuthError(
                "Qwen ticket 未配置。请运行: python -m src.login qwen 自动登录提取。"
            )

        url = f"{QWEN_CHAT2_BASE}/api/v1/user/info"
        session = await self._transport._get_session()

        async with session.get(
            url,
            headers=self._get_auth_headers(),
        ) as resp:
            if resp.status == 401:
                # 凭证失效 → 抛 AuthError（health_check 会标 unhealthy）
                raise AuthError(
                    "Qwen ticket 已失效（HTTP 401）。"
                    "请运行: python -m src.login qwen 重新登录。"
                )
            if resp.status == 403:
                raise AuthError(
                    "Qwen ticket 被拒绝（HTTP 403）。"
                    "请运行: python -m src.login qwen 重新登录。"
                )
            if resp.status == 200:
                logger.info("[Qwen] Ticket verified")
                return self._ticket
            # 其他状态码（404/500/502/...）→ 当作临时网络问题，不抛 AuthError
            # 避免 health_check 误标记账号不健康、触发指数退避冷却
            text = await resp.text()
            logger.warning(
                f"[Qwen] Auth check non-200: HTTP {resp.status} — {text[:150]}。"
                f"将跳过本次验证，假定 ticket 仍有效。"
            )
            return self._ticket

    # ---- Messages ----

    def _messages_to_qwen(self, request: ChatCompletionRequest) -> tuple[str, list[dict]]:
        """OpenAI messages → Qwen 格式"""
        system_prompt = ""
        conversation_parts: list[str] = []

        for msg in request.messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_prompt = msg.content
            elif msg.role == "user":
                c = msg.content
                if isinstance(c, str):
                    conversation_parts.append(c)
                elif isinstance(c, list):
                    txt = "\n".join(
                        p.get("text", "") if isinstance(p, dict) else ""
                        for p in c
                    )
                    conversation_parts.append(txt)
            elif msg.role == "assistant":
                c = msg.content
                if isinstance(c, str) and c:
                    conversation_parts.append(c)
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        func = tc.get("function", {})
                        conversation_parts.append(
                            f"[function_call] {func.get('name')}({func.get('arguments', '')})"
                        )
            elif msg.role == "tool":
                c = msg.content
                conversation_parts.append(
                    f"[function_result] {c if isinstance(c, str) else json.dumps(c)}"
                )

        prompt = "\n\n".join(conversation_parts)

        # 构建 messages 数组 (Qwen 用此格式)
        qwen_messages = []
        for msg in request.messages:
            if msg.role == "system":
                continue
            role = msg.role
            content = ""
            if isinstance(msg.content, str):
                content = msg.content
            elif isinstance(msg.content, list):
                content = "\n".join(
                    p.get("text", "") for p in msg.content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            if content:
                qwen_messages.append({"role": role, "content": content})

        return prompt, qwen_messages

    # ---- Chat Completion ----

    async def chat_completion(self, request: ChatCompletionRequest) -> Any:
        try:
            result_parts: list[str] = []
            async for chunk in self.chat_completion_stream(request):
                if chunk.content:
                    result_parts.append(chunk.content)
            return {"content": "".join(result_parts)}
        except Exception as e:
            logger.error(f"[Qwen] Non-stream error: {e}")
            raise

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话"""
        await self.login()
        session_id = _short_uuid()
        req_id = _short_uuid()

        prompt, _ = self._messages_to_qwen(request)

        # 确定模型
        model_lower = request.model.lower()
        actual_model = self._map_model(request.model)

        enable_thinking = (
            request.reasoning_effort is not None
            or "think" in model_lower
            or "r1" in model_lower
        )
        enable_search = (
            request.web_search
            or "search" in model_lower
        )

        if enable_thinking and actual_model == "Qwen3-Max":
            actual_model = "Qwen3-Max-Thinking-Preview"

        logger.info(
            f"[Qwen] Stream: model={actual_model} search={enable_search} thinking={enable_thinking}"
        )

        # 构建 payload
        payload = {
            "model": actual_model,
            "input": {
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            },
            "parameters": {
                "result_format": "message",
            },
            "session_id": session_id,
            "request_id": req_id,
        }

        if enable_search:
            payload["parameters"]["enable_search"] = True

        http_session = await self._transport._get_session()
        url = f"{QWEN_CHAT2_BASE}/api/v2/assistant/chat"

        is_first = True

        async with http_session.post(
            url,
            json=payload,
            headers=self._get_auth_headers(),
            params=self._get_params({"nonce": _random_nonce(), "timestamp": int(time.time() * 1000)}),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Qwen API error: HTTP {resp.status} — {text[:200]}",
                    provider="qwen",
                )

            async for line_raw in resp.content:
                line = line_raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                if line.startswith("data:"):
                    data_str = line[5:].strip()
                else:
                    data_str = line

                if not data_str or data_str == "[DONE]":
                    continue

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                text = self._extract_output(data)
                if text:
                    if is_first:
                        is_first = False
                    yield StreamChunk(
                        content=text,
                        model="qwen",
                        role="assistant" if is_first else None,
                    )

            logger.debug("[Qwen] Stream done")

    def _extract_output(self, data: dict) -> str:
        """从 Qwen 响应中提取文本"""
        # output.text 格式
        output = data.get("output", {})
        if isinstance(output, dict):
            text = output.get("text")
            if text:
                return text

        # choices[0].delta.content
        choices = data.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            if delta.get("content"):
                return delta["content"]

        # 直接的 text/content 字段
        if "text" in data and isinstance(data["text"], str):
            return data["text"]
        if "content" in data and isinstance(data["content"], str):
            return data["content"]

        return ""

    # ---- Models ----

    async def list_models(self) -> list[str]:
        return self.account.models or [
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "Qwen3-Max",
            "Qwen3.5-Flash",
            "Qwen3-Max-Thinking-Preview",
            "Qwen3-Coder",
        ]

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            return True
        except Exception:
            return False