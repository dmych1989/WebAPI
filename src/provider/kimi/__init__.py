# -*- coding: utf-8 -*-
"""
Kimi Provider Adapter

网页 API 协议:
- Base URL: https://www.kimi.com
- 认证: JWT access token，或 refresh token（首次使用需换取 access token）
- 对话: gRPC-Web Connect 协议 → POST /apiv2/kimi.gateway.chat.v1.ChatService/Chat
- 消息格式: role:text 文本格式（非 JSON）
- 流式: SSE 通过 Connect 协议
"""

from __future__ import annotations

import base64
import json
import struct
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


KIMI_BASE = "https://www.kimi.com"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": KIMI_BASE,
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Priority": "u=1, i",
}


def _detect_token_type(token: str) -> str:
    """检测 token 类型: access (jwt) 或 refresh"""
    if token.startswith("eyJ") and token.count(".") == 2:
        try:
            payload = json.loads(
                base64.b64decode(token.split(".")[1] + "===").decode()
            )
            if payload.get("app_id") == "kimi" and payload.get("typ") == "access":
                return "access"
        except Exception:
            pass
    return "refresh"


def _resolve_kimi_scenario(model: str) -> str:
    """根据模型名解析 Kimi scenario"""
    return "SCENARIO_K2D6" if "k2.6" in model.lower() else "SCENARIO_K2D5"


def _build_kimi_payload(
    model: str,
    content: str,
    enable_search: bool = False,
    enable_thinking: bool = False,
) -> dict:
    """
    构建 Kimi Connect JSON 请求体（参考 Chat2API-main createKimiChatPayload）

    Kimi 新版 API 使用 JSON 结构（非 protobuf），外层用 gRPC-Web frame 包裹 JSON。
    """
    scenario = _resolve_kimi_scenario(model)
    return {
        "scenario": scenario,
        "chat_id": "",
        "tools": [{"type": "TOOL_TYPE_SEARCH", "search": {}}] if enable_search else [],
        "message": {
            "parent_id": "",
            "role": "user",
            "blocks": [{
                "message_id": "",
                "text": {"content": content},
            }],
            "scenario": scenario,
        },
        "options": {
            "thinking": enable_thinking,
        },
    }


def _encode_grpc_frame(payload: dict) -> bytes:
    """gRPC-Web 帧编码（JSON 版）: 1 byte flag + 4 bytes length + JSON data

    参考 Chat2API-main encodeKimiGrpcFrame:
      frameBuffer = 5 bytes header + JSON payload
    """
    json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return b"\x00" + struct.pack(">I", len(json_bytes)) + json_bytes


# 多个已知的 refresh-token 兑换端点，按顺序尝试
_REFRESH_ENDPOINTS = [
    f"{KIMI_BASE}/api/auth/refresh_token",
    f"{KIMI_BASE}/api/auth/refresh",
    f"{KIMI_BASE}/api/v1/auth/refresh",
]


@ProviderRegistry.register("kimi")
class KimiProvider(BaseProvider):
    """Kimi 网页 API 适配器"""

    name = "kimi"
    display_name = "Kimi (月之暗面)"
    auth_type = "jwt"

    def __init__(self, account: AccountConfig):
        self.account = account
        self._token: Optional[str] = account.token
        self._token_type: Optional[str] = None
        self._cache_token: Optional[str] = None
        self._cache_expires: float = 0
        self._transport = APIReverseTransport()

    # ---- Auth ----

    async def login(self) -> str:
        """获取可用的 access token（用于 API 调用）

        Kimi 现在的 token 模型：
        - 旧站 kimi.moonshot.cn 还在用 refresh_token (typ=refresh)
        - 新站 www.kimi.com 已统一使用单个 access_token (typ=access)
        - 不再有公开的 refresh-token 兑换端点（/api/auth/refresh_* 返回 404）

        因此当前实现：
        1. 若是 access token（typ=access）→ 直接缓存使用
        2. 若是 refresh token（typ=refresh）→ 验证一次 /api/user 后当作 access token 用
        3. 任何 401 → 抛 AuthError，提示用户重新登录
        """
        if not self._token:
            raise AuthError(
                "Kimi Token 未配置。请编辑 config/config.yaml 中的 providers.kimi.accounts[0].token，"
                "或运行 python -m src.login kimi 自动登录提取。"
            )

        now = time.time()
        if self._cache_token and self._cache_expires > now:
            return self._cache_token

        if self._token_type is None:
            self._token_type = _detect_token_type(self._token)
            logger.info(f"[Kimi] Token type detected: {self._token_type}")

        # 解释 token 类型
        if self._token_type == "refresh":
            logger.warning(
                "[Kimi] 当前 token 是 refresh_token 类型（typ=refresh）。"
                "如果多次验证失败，建议改用 access_token（typ=access）。"
            )

        if self._token_type == "access":
            # JWT access token 直接缓存使用
            self._cache_token = self._token
            self._cache_expires = now + 300
            return self._token

        # Refresh token / unknown: 尝试用 /api/user 验证
        url = f"{KIMI_BASE}/api/user"
        session = await self._transport._get_session()

        try:
            async with session.get(
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    **FAKE_HEADERS,
                },
            ) as resp:
                body = await resp.text()
                if resp.status == 401:
                    # 解析错误类型
                    err_type = "auth.token.invalid"
                    try:
                        err_obj = json.loads(body)
                        err_type = err_obj.get("error_type", err_type)
                    except (json.JSONDecodeError, ValueError):
                        pass

                    logger.warning(
                        f"[Kimi] Token rejected: {err_type} (HTTP 401)"
                    )
                    self._cache_token = None
                    self._cache_expires = 0

                    # 针对性错误信息
                    if "expired" in err_type.lower() or "过期" in body:
                        msg = (
                            "Kimi Token 已过期（auth.token.expired）。"
                            "请运行: python -m src.login kimi 重新登录。"
                        )
                    elif "empty" in err_type.lower() or "不存在" in body:
                        msg = (
                            "Kimi Token 已被服务端吊销（auth.token.empty / 您的授权不存在）。"
                            "这通常因为您在其它设备重新登录导致旧 token 失效。"
                            "请运行: python -m src.login kimi 重新登录。"
                        )
                    else:
                        msg = (
                            f"Kimi Token 被服务端拒绝（HTTP 401, error_type={err_type}）。"
                            "请运行: python -m src.login kimi 重新登录。"
                        )
                    raise AuthError(msg)
                if resp.status == 200:
                    # 200 OK — 当前 token 有效
                    self._cache_token = self._token
                    self._cache_expires = now + 300
                    logger.info("[Kimi] Token validated via /api/user (200 OK)")
                    return self._token
                # 其它状态码 — 抛出明确的错误
                raise AuthError(
                    f"Kimi Token 验证失败: HTTP {resp.status} — {body[:150]}"
                )
        except aiohttp.ClientError as e:
            # 网络错误（DNS 失败、连接超时等）— 区分报告
            logger.error(f"[Kimi] Network error during login: {e}")
            raise AuthError(
                f"Kimi 服务连接失败: {type(e).__name__}: {e}。"
                f"请检查网络或稍后重试。"
            )

    # 注：保留旧版 _refresh_access_token 以防 Kimi 之后恢复 refresh 端点
    async def _refresh_access_token(self) -> str:
        """用 refresh token 换取新的 access token（兼容方法）

        Kimi 当前未公开 refresh-token 兑换端点。保留此方法以防未来恢复。
        """
        session = await self._transport._get_session()
        last_error: Optional[str] = None

        for url in _REFRESH_ENDPOINTS:
            try:
                async with session.post(
                    url,
                    json={"refresh_token": self._token},
                    headers={"Content-Type": "application/json", **FAKE_HEADERS},
                ) as resp:
                    if resp.status != 200:
                        last_error = f"HTTP {resp.status} at {url}"
                        logger.debug(f"[Kimi] refresh attempt {url} → HTTP {resp.status}")
                        continue
                    data = await resp.json()
                    access = (
                        data.get("access_token")
                        or data.get("token")
                        or (data.get("data") or {}).get("access_token")
                    )
                    if not access:
                        last_error = f"no access_token in response from {url}"
                        continue
                    expires_in = (
                        data.get("expires_in")
                        or (data.get("data") or {}).get("expires_in")
                        or 3600
                    )
                    self._cache_token = access
                    self._cache_expires = time.time() + max(60, int(expires_in) - 60)
                    logger.info(
                        f"[Kimi] Got access_token via {url}, "
                        f"expires in {expires_in}s, len={len(access)}"
                    )
                    return access
            except aiohttp.ClientError as e:
                last_error = f"{type(e).__name__}: {e} at {url}"
                logger.debug(f"[Kimi] refresh attempt {url} → {last_error}")
                continue
            except Exception as e:
                last_error = f"{type(e).__name__}: {e} at {url}"
                continue

        # 全部端点失败：抛错提示用户重登
        raise AuthError(
            f"Kimi refresh-token 兑换失败 ({last_error})。"
            f"请运行: python -m src.login kimi 重新登录。"
        )

    # ---- Messages ----

    def _messages_to_content(
        self, request: ChatCompletionRequest
    ) -> tuple[str, bool, bool]:
        """OpenAI messages → Kimi content 格式

        Kimi 的 content 字段为单字符串，把 system/user/assistant/tool 拼成
        "role:text" 行格式。如果存在 system 消息，单独提取作为 system 行。
        """
        model_lower = request.model.lower()

        enable_thinking = (
            request.reasoning_effort is not None
            or "think" in model_lower
            or "r1" in model_lower
        )
        enable_search = bool(
            request.web_search
            or "search" in model_lower
        )

        system_text_parts: list[str] = []
        other_msgs: list = []
        for msg in request.messages:
            if msg.role == "system":
                text = self._msg_to_text(msg.content)
                if text:
                    system_text_parts.append(text)
            else:
                other_msgs.append(msg)

        parts: list[str] = []
        # 合并所有 system 消息为一行
        if system_text_parts:
            parts.append(f"system:{' '.join(system_text_parts)}")

        for msg in other_msgs:
            text = self._msg_to_text(msg.content)
            # tool_calls in assistant
            if msg.role == "assistant" and msg.tool_calls:
                try:
                    text = (text + " " if text else "") + json.dumps(
                        msg.tool_calls, ensure_ascii=False
                    )
                except Exception:
                    pass
            parts.append(f"{msg.role}:{text}")

        content = "\n".join(parts)
        return content, enable_search, enable_thinking

    @staticmethod
    def _msg_to_text(content: Any) -> str:
        """统一把 ChatMessage.content 转为字符串"""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                (p.get("text", "") if isinstance(p, dict) else str(p))
                for p in content
            )
        return str(content)

    # ---- Chat Completion ----

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """非流式对话"""
        result_parts: list[str] = []
        async for chunk in self.chat_completion_stream(request):
            if chunk.content:
                result_parts.append(chunk.content)
        content = "".join(result_parts)
        actual_model = (request.model or "kimi").strip()
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
        """流式对话

        Kimi (www.kimi.com) 返回的是 gRPC-Web Connect 协议响应:
        - 帧格式: 1 byte flag (0x00) + 4 bytes length (big-endian) + JSON payload
        - 事件类型: heartbeat, op:set, op:append
        - 文本事件: {"op":"append", "mask":"block.text.content", "block":{"text":{"content":"..."}}}
        - 初始事件: {"op":"set", "mask":"block.text", "block":{"text":{"content":"..."}}}
        - 结束事件: {"op":"set", "mask":"message.status", "message":{"status":"MESSAGE_STATUS_COMPLETED"}}
        """
        token = await self.login()
        content, enable_search, enable_thinking = self._messages_to_content(request)

        logger.info(
            f"[Kimi] Stream: model={request.model} "
            f"search={enable_search} thinking={enable_thinking} "
            f"msgs={len(request.messages)}"
        )

        # 构建 Connect JSON 请求 + gRPC-Web frame
        payload = _build_kimi_payload(
            request.model or "Kimi-K2.6",
            content,
            enable_search=enable_search,
            enable_thinking=enable_thinking,
        )
        grpc_frame = _encode_grpc_frame(payload)

        http_session = await self._transport._get_session()
        url = f"{KIMI_BASE}/apiv2/kimi.gateway.chat.v1.ChatService/Chat"

        async with http_session.post(
            url,
            data=grpc_frame,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/connect+json",
                **FAKE_HEADERS,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                if resp.status == 401:
                    self._cache_token = None
                    self._cache_expires = 0
                    raise AuthError(
                        f"Kimi API 401 — access token rejected. Body: {text[:200]}"
                    )
                raise ProviderError(
                    f"Kimi API error: HTTP {resp.status} — {text[:200]}",
                    provider="kimi",
                )

            # gRPC-Web Connect 流式响应: 5-byte frame header + JSON payload
            # Frame: 1 byte flag (0x00 = data) + 4 bytes big-endian length + payload
            buf = b""
            async for data in resp.content.iter_any():
                if not data:
                    continue
                buf += data
                # 持续解析所有完整帧
                while True:
                    frame_data, buf = self._consume_grpc_frame(buf)
                    if frame_data is None:
                        break
                    for chunk in self._parse_kimi_event(frame_data, request.model):
                        yield chunk

            # 处理尾部残留
            if len(buf) >= 5:
                frame_data, _ = self._consume_grpc_frame(buf)
                if frame_data is not None:
                    for chunk in self._parse_kimi_event(frame_data, request.model):
                        yield chunk

            logger.debug("[Kimi] Stream done")

    @staticmethod
    def _consume_grpc_frame(buf: bytes) -> tuple[Optional[bytes], bytes]:
        """从 buf 头部取出一个 gRPC-Web 帧 (5 字节 header + payload)，返回 (payload, 剩余 buf)

        返回 (None, buf) 表示当前 buf 不足以组成一个完整帧。
        """
        if len(buf) < 5:
            return None, buf
        # 1 byte flag + 4 bytes big-endian length
        flag = buf[0]
        length = struct.unpack(">I", buf[1:5])[0]
        if flag != 0x00:
            # 非数据帧（trailer 等），跳过
            if len(buf) < 5 + length:
                return None, buf
            return b"", buf[5 + length:]
        if len(buf) < 5 + length:
            return None, buf
        payload = bytes(buf[5:5 + length])
        return payload, buf[5 + length:]

    def _parse_kimi_event(
        self, frame_data: bytes, request_model: Optional[str]
    ) -> list[StreamChunk]:
        """解析单个 gRPC-Web 帧 (JSON) → StreamChunk 列表"""
        if not frame_data:
            return []
        actual_model = (request_model or "kimi").strip()
        try:
            obj = json.loads(frame_data.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []

        if not isinstance(obj, dict):
            return []

        # heartbeat 事件 → 跳过
        if "heartbeat" in obj:
            return []

        op = obj.get("op")

        # op:append + block.text.content → 增量文本
        if op == "append":
            block = obj.get("block") or {}
            text_obj = block.get("text") if isinstance(block, dict) else None
            if isinstance(text_obj, dict):
                delta = text_obj.get("content")
                if isinstance(delta, str) and delta:
                    return [StreamChunk(content=delta, model=actual_model)]
            return []

        # op:set + block.text → 首块文本（包含 " 从前" 等首段）
        if op == "set" and obj.get("mask") == "block.text":
            block = obj.get("block") or {}
            text_obj = block.get("text") if isinstance(block, dict) else None
            if isinstance(text_obj, dict):
                first = text_obj.get("content")
                if isinstance(first, str) and first:
                    return [StreamChunk(content=first, model=actual_model)]
            return []

        # 消息状态完成 → finish_reason
        if op == "set" and obj.get("mask") == "message.status":
            msg = obj.get("message") or {}
            status = msg.get("status") if isinstance(msg, dict) else None
            if status == "MESSAGE_STATUS_COMPLETED":
                return [StreamChunk(finish_reason="stop", model=actual_model)]
            return []

        # 其它事件 (chat, message, chat.lastRequest, chat.name, ...) → 跳过
        return []

    @staticmethod
    def _parse_sse_line(line: str) -> str:
        """解析单行 SSE/Kimi 流式响应 → 文本片段

        支持三种格式:
        - `data: {...}` — Connect SSE
        - `{...}` — 裸 JSON
        - 其它纯文本行
        """
        line = line.strip()
        if not line:
            return ""

        if line.startswith("data:"):
            segment = line[5:].strip()
        else:
            segment = line

        if not segment or segment == "[DONE]":
            return ""

        # 尝试 JSON 解析
        if segment.startswith("{") or segment.startswith("["):
            try:
                obj = json.loads(segment)
                return KimiProvider._extract_text_from_obj(obj)
            except json.JSONDecodeError:
                return segment

        # 纯文本片段
        return segment

    @staticmethod
    def _extract_text_from_obj(obj: Any) -> str:
        """从 JSON 对象中递归提取文本"""
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            for key in ("text", "content", "message", "delta"):
                if key in obj:
                    v = obj[key]
                    if isinstance(v, str):
                        return v
                    nested = KimiProvider._extract_text_from_obj(v)
                    if nested:
                        return nested
            # response 字段嵌套
            if "response" in obj:
                nested = KimiProvider._extract_text_from_obj(obj["response"])
                if nested:
                    return nested
            # choices 数组
            if "choices" in obj and isinstance(obj["choices"], list) and obj["choices"]:
                choice = obj["choices"][0]
                if isinstance(choice, dict):
                    nested = KimiProvider._extract_text_from_obj(choice.get("delta"))
                    if nested:
                        return nested
                    nested = KimiProvider._extract_text_from_obj(choice.get("message"))
                    if nested:
                        return nested
        if isinstance(obj, list):
            for item in obj:
                nested = KimiProvider._extract_text_from_obj(item)
                if nested:
                    return nested
        return ""

    # ---- Models ----

    async def list_models(self) -> list[str]:
        # 始终返回 Provider 全量模型（不受 account.models 限制）
        return [
            "Kimi-K2.6",
            "Kimi-K2.6-Think",
            "Kimi-K2.6-Search",
        ]

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            return True
        except Exception as e:
            logger.debug(f"[Kimi] health_check failed: {type(e).__name__}: {e}")
            return False
