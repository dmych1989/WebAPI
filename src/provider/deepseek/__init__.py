# -*- coding: utf-8 -*-
"""
DeepSeek Provider Adapter

网页 API 协议:
- Base URL: https://chat.deepseek.com/api
- 认证: UserToken → accessToken（Bearer）
- 会话: POST /v0/chat_session/create
- POW: POST /v0/chat/create_pow_challenge → DeepSeekHashV1
- 对话: POST /v0/chat/completion（SSE 流）
- 消息格式: 特殊 prompt 格式（非 JSON messages）
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional
from urllib.parse import urljoin

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport
from src.provider.deepseek.pow import solve_pow, build_pow_header


DEEPSEEK_BASE = "https://chat.deepseek.com/api"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://chat.deepseek.com",
    "Referer": "https://chat.deepseek.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "X-App-Version": "2.0.0",
    "X-Client-Locale": "zh_CN",
    "X-Client-Platform": "web",
    "X-Client-Version": "2.0.0",
}


def _random_hex(length: int) -> str:
    return uuid.uuid4().hex[:length]


@ProviderRegistry.register("deepseek")
class DeepSeekProvider(BaseProvider):
    """DeepSeek 网页 API 适配器"""

    name = "deepseek"
    display_name = "DeepSeek"
    auth_type = "token"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._token: Optional[str] = account.token
        self._access_token: Optional[str] = None
        self._access_token_expires: float = 0
        self._transport = APIReverseTransport()
        self._session_id: Optional[str] = None
        self._session_cache_time: float = 0
        # Cookie 用于过 Cloudflare WAF
        self._cookie: Optional[str] = getattr(account, 'cookie', None)

    def _get_headers(self, extra: dict = None) -> dict:
        """构建请求头，包含 Cookie"""
        headers = {**FAKE_HEADERS}
        if self._cookie:
            headers["Cookie"] = self._cookie
        if extra:
            headers.update(extra)
        return headers

    # ---- Auth ----

    async def login(self) -> str:
        """获取 access token
        
        尝试顺序:
        1. 有 userToken → 用 Bearer token 换取 access_token
        2. 只有 Cookie → 用 Cookie 鉴权调 /v0/users/current
        """
        now = time.time()
        if self._access_token and self._access_token_expires > now:
            return self._access_token

        if not self._token and not self._cookie:
            raise AuthError("DeepSeek: no token or cookie configured")

        # 检测无效的 token（localStorage 返回的空 JSON 包装）
        if self._token:
            try:
                obj = json.loads(self._token)
                if isinstance(obj, dict) and obj.get("value") is None:
                    raise AuthError(
                        "DeepSeek userToken is invalid (null JSON wrapper). "
                        "Please run: python -m src.login deepseek"
                    )
            except (json.JSONDecodeError, TypeError):
                pass  # 非 JSON，可能是纯 token 字符串

        logger.info("[DeepSeek] Acquiring access token via /v0/users/current...")
        url = f"{DEEPSEEK_BASE}/v0/users/current"
        session = await self._transport._get_session()

        # 构建请求头
        req_headers = self._get_headers()
        if self._token:
            req_headers["Authorization"] = f"Bearer {self._token}"

        async with session.get(url, headers=req_headers) as resp:
            if resp.status in (401, 403):
                raise AuthError("DeepSeek authentication failed — cookie/token may have expired")
            if resp.status != 200:
                raise AuthError(f"DeepSeek token check failed: HTTP {resp.status}")

            data = await resp.json()
            biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data", {})

            access_token = biz_data.get("token")
            if not access_token:
                raise AuthError(f"Failed to acquire access_token: {data.get('msg', json.dumps(data)[:200])}")

            self._access_token = access_token
            self._access_token_expires = now + 3500  # ~1h
            logger.info(f"[DeepSeek] Access token acquired ({len(access_token)} chars)")
            return self._access_token

    # ---- Session ----

    async def _ensure_session(self) -> str:
        """确保有有效的 chat session"""
        now = time.time()
        if self._session_id and (now - self._session_cache_time) < 300:
            return self._session_id

        token = await self.login()
        url = f"{DEEPSEEK_BASE}/v0/chat_session/create"
        session = await self._transport._get_session()

        async with session.post(
            url,
            json={},
            headers=self._get_headers({"Authorization": f"Bearer {token}"}),
        ) as resp:
            data = await resp.json()
            biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data", {})

            if resp.status != 200:
                raise ProviderError(
                    f"DeepSeek session create failed: HTTP {resp.status}", provider="deepseek"
                )

            self._session_id = biz_data.get("chat_session", {}).get("id")
            self._session_cache_time = now
            logger.debug(f"[DeepSeek] Session created: {self._session_id}")
            return self._session_id

    # ---- POW Challenge ----

    async def _solve_challenge(self) -> str:
        """计算 POW challenge answer（在线程池中运行，不阻塞事件循环）

        使用 DeepSeekHashV1 (修改版 SHA3-256, Keccak 23轮) 算法：
        1. 从服务器获取 challenge
        2. 在 [0, difficulty) 范围内暴力搜索满足条件的 nonce
        3. 构建 base64 编码的 JSON header
        """
        import asyncio as _asyncio

        token = self._access_token or await self.login()
        url = f"{DEEPSEEK_BASE}/v0/chat/create_pow_challenge"
        session = await self._transport._get_session()

        async with session.post(
            url,
            json={"target_path": "/api/v0/chat/completion"},
            headers=self._get_headers({"Authorization": f"Bearer {token}"}),
        ) as resp:
            data = await resp.json()
            biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data", {})
            challenge = biz_data.get("challenge")

            if not challenge:
                raise ProviderError(
                    f"Failed to get challenge: {data.get('msg', resp.status)}",
                    provider="deepseek",
                )

            algorithm = challenge.get("algorithm", "DeepSeekHashV1")
            if algorithm != "DeepSeekHashV1":
                raise ProviderError(f"Unsupported challenge algorithm: {algorithm}", provider="deepseek")

            difficulty = challenge["difficulty"]
            if not difficulty:
                difficulty = 144000
            logger.info(f"[DeepSeek] POW difficulty={difficulty}, computing in thread pool...")
            t0 = time.time()

            # 在线程池中执行 CPU 密集型 POW 计算，不阻塞 asyncio 事件循环
            try:
                answer = await _asyncio.get_event_loop().run_in_executor(
                    None,
                    solve_pow,
                    challenge["challenge"],
                    challenge["salt"],
                    challenge["expire_at"],
                    difficulty,
                )
            except ValueError as e:
                raise ProviderError(str(e), provider="deepseek")

            elapsed = time.time() - t0
            logger.info(f"[DeepSeek] POW solved: answer={answer}, elapsed={elapsed:.2f}s")

            return build_pow_header(
                algorithm=algorithm,
                challenge=challenge["challenge"],
                salt=challenge["salt"],
                answer=answer,
                signature=challenge.get("signature", ""),
                target_path="/api/v0/chat/completion",
            )

    # ---- Messages → Prompt ----

    def _messages_to_prompt(self, request: ChatCompletionRequest) -> str:
        """OpenAI messages → DeepSeek prompt 格式"""
        parts: list[str] = []
        for i, msg in enumerate(request.messages):
            role = msg.role
            content = msg.content

            # 处理 content：可能是 str 或 list
            if isinstance(content, list):
                text = "\n".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            elif isinstance(content, str):
                text = content
            elif content is None:
                text = ""
            else:
                text = str(content)

            # tool_calls in assistant
            tool_calls_text = ""
            if role == "assistant" and msg.tool_calls:
                tool_calls_text = json.dumps(msg.tool_calls, ensure_ascii=False)
                text = tool_calls_text

            if role in ("user", "system"):
                prefix = "" if i == 0 else "用户: "
                parts.append(f"{prefix}{text}")
            elif role == "assistant":
                parts.append(f"助手: {text}")
            elif role == "tool":
                parts.append(f"工具结果: {text}")

        return "\n\n".join(parts)

    # ---- Chat Completion ----

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """非流式对话"""
        token = await self.login()
        session_id = await self._ensure_session()
        challenge_answer = await self._solve_challenge()

        prompt = self._messages_to_prompt(request)

        resolved = self._resolve_options(request)
        payload = {
            "chat_session_id": session_id,
            "parent_message_id": None,
            "prompt": prompt,
            "model_type": resolved["model_type"],
            "ref_file_ids": [],
            "search_enabled": resolved["search_enabled"],
            "thinking_enabled": resolved["thinking_enabled"],
            "preempt": False,
        }

        http_session = await self._transport._get_session()
        url = f"{DEEPSEEK_BASE}/v0/chat/completion"

        async with http_session.post(
            url,
            json=payload,
            headers=self._get_headers({
                "Authorization": f"Bearer {token}",
                "Referer": f"https://chat.deepseek.com/a/chat/s/{session_id}",
                "X-Ds-Pow-Response": challenge_answer,
            }),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"DeepSeek API error: HTTP {resp.status} — {text[:200]}",
                    provider="deepseek",
                )

            raw_body = b""
            async for chunk_data in resp.content.iter_any():
                raw_body += chunk_data

            content = "".join(self._parse_sse_body(raw_body.decode("utf-8", errors="replace")))
            actual_model = (request.model or "deepseek-chat").strip()
            return ProviderResponse(
                status_code=200,
                data={
                    "id": f"chatcmpl-{_random_hex(12)}",
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
        token = await self.login()
        session_id = await self._ensure_session()
        challenge_answer = await self._solve_challenge()

        prompt = self._messages_to_prompt(request)
        resolved = self._resolve_options(request)

        payload = {
            "chat_session_id": session_id,
            "parent_message_id": None,
            "prompt": prompt,
            "model_type": resolved["model_type"],
            "ref_file_ids": [],
            "search_enabled": resolved["search_enabled"],
            "thinking_enabled": resolved["thinking_enabled"],
            "preempt": False,
        }

        logger.info(f"[DeepSeek] Stream: session={session_id[:12]}... model_type={resolved['model_type']}")

        http_session = await self._transport._get_session()
        url = f"{DEEPSEEK_BASE}/v0/chat/completion"

        async with http_session.post(
            url,
            json=payload,
            headers=self._get_headers({
                "Authorization": f"Bearer {token}",
                "Referer": f"https://chat.deepseek.com/a/chat/s/{session_id}",
                "X-Ds-Pow-Response": challenge_answer,
            }),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"DeepSeek API error: HTTP {resp.status} — {text[:200]}",
                    provider="deepseek",
                )

            current_path = ""
            is_first = True
            gathered_content = ""
            actual_model = (request.model or "deepseek-chat").strip()

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

                chunk = self._parse_sse_chunk(parsed, current_path, actual_model)
                if chunk and chunk.content:
                    gathered_content += chunk.content
                    yield chunk
                    is_first = False

            logger.debug(
                f"[DeepSeek] Stream done: {len(gathered_content)} chars"
            )

    def _resolve_options(self, request: ChatCompletionRequest) -> dict:
        """解析 model_type, search_enabled, thinking_enabled

        DeepSeek 服务端 (2026-06) model_type 合法值:
        - default: 通用对话（含 deepseek-chat / v4-flash / v4-pro）
        - expert:  深度思考/推理（deepseek-reasoner / R1 等）
        - vision:  多模态（视觉输入）

        历史值 deepseek_chat / deepseek_reasoner 已弃用，会触发
        "unknown variant" 422 错误。
        """
        model_lower = (request.model or "").lower()

        # 搜索
        search_enabled = bool(
            request.web_search or "search" in model_lower
        )

        # 思考（推理）
        thinking_enabled = bool(
            request.reasoning_effort is not None
            or "think" in model_lower
            or "reasoner" in model_lower
            or "r1" in model_lower
        )

        # 多模态
        vision_enabled = bool(
            "vision" in model_lower or "vl" in model_lower
        )

        # model_type 映射（按优先级：vision > expert > default）
        if vision_enabled:
            model_type = "vision"
        elif thinking_enabled:
            model_type = "expert"
        else:
            model_type = "default"

        if search_enabled:
            logger.info("[DeepSeek] Web search enabled")
        if thinking_enabled:
            logger.info(
                f"[DeepSeek] Thinking mode: effort={request.reasoning_effort}"
            )
        if vision_enabled:
            logger.info("[DeepSeek] Vision mode")

        logger.debug(f"[DeepSeek] Resolved model_type={model_type}")
        return {
            "model_type": model_type,
            "search_enabled": search_enabled,
            "thinking_enabled": thinking_enabled,
        }

    def _parse_sse_chunk(
        self, parsed: dict, current_path_ref: str, model: str = "deepseek"
    ) -> Optional[StreamChunk]:
        """解析单个 SSE chunk → StreamChunk"""
        content = ""

        # DeepSeek 的 chunk 格式:
        # 1. {v: {response: {thinking_enabled: true, fragments: [...]}}}
        # 2. {p: "response/fragments", v: [fragments]}
        # 3. {p: "...", v: "text"}

        if isinstance(parsed.get("v"), dict) and "response" in parsed["v"]:
            resp = parsed["v"]["response"]
            fragments = resp.get("fragments", [])
            for frag in fragments:
                if frag.get("content"):
                    c = frag["content"].replace("FINISHED", "")
                    if c:
                        content += c
            return StreamChunk(content=content, model=model) if content else None

        if parsed.get("p") == "response/fragments" and isinstance(parsed.get("v"), list):
            for frag in parsed["v"]:
                if frag.get("content"):
                    c = frag["content"].replace("FINISHED", "")
                    if c:
                        content += c
            return StreamChunk(content=content, model=model) if content else None

        # 简单 string chunk
        if isinstance(parsed.get("v"), str):
            text = parsed["v"].replace("FINISHED", "")
            return StreamChunk(content=text, model=model) if text else None

        # Array with nested content
        if isinstance(parsed.get("v"), list):
            for item in parsed["v"]:
                if isinstance(item, dict):
                    nested = item.get("v", [])
                    if isinstance(nested, list):
                        for nv in nested:
                            if isinstance(nv, dict) and nv.get("content"):
                                content += nv["content"].replace("FINISHED", "")
                    elif isinstance(nested, str):
                        content += nested.replace("FINISHED", "")
                    if isinstance(item.get("content"), str):
                        content += item["content"].replace("FINISHED", "")
            return StreamChunk(content=content, model=model) if content else None

        return None

    def _parse_sse_body(self, body: str) -> list[str]:
        """解析 SSE body → 文本片段列表"""
        parts: list[str] = []
        for line in body.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = self._parse_sse_chunk(json.loads(data_str), "")
                if chunk and chunk.content:
                    parts.append(chunk.content)
            except Exception:
                continue
        return parts

    # ---- Models ----

    async def list_models(self) -> list[str]:
        return self.account.models or [
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ]

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            return True
        except Exception:
            return False

    # ---- Clear Conversations ----

    async def clear_conversations(self) -> dict:
        """删除 DeepSeek 的所有历史对话

        流程:
        1. GET /v0/chat_session/fetch_page 列出所有 session
        2. POST /v0/chat_session/delete_batch 批量删除
        """
        try:
            token = await self.login()
            session = await self._transport._get_session()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # 1. 列出所有 session
            list_url = f"{DEEPSEEK_BASE}/v0/chat_session/fetch_page?p=0&ps=200"
            async with session.get(list_url, headers=headers) as resp:
                if resp.status != 200:
                    return {"ok": False, "deleted_count": 0, "detail": f"列出 session 失败: HTTP {resp.status}"}
                payload = await resp.json()
            data = payload.get("data", {})
            sessions = data.get("chat_sessions", []) or data.get("sessions", []) or []
            if not sessions:
                return {"ok": True, "deleted_count": 0, "detail": "没有历史对话"}

            # 2. 批量删除
            ids = [s.get("id") for s in sessions if s.get("id")]
            del_url = f"{DEEPSEEK_BASE}/v0/chat_session/delete_batch"
            async with session.post(del_url, json={"chat_session_ids": ids}, headers=headers) as resp:
                if resp.status != 200:
                    return {"ok": False, "deleted_count": 0, "detail": f"批量删除失败: HTTP {resp.status}"}
                return {"ok": True, "deleted_count": len(ids), "detail": f"已删除 {len(ids)} 个对话"}
        except Exception as e:
            return {"ok": False, "deleted_count": 0, "detail": str(e)}
