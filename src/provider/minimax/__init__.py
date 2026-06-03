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

# 官方模型 + 用户自定义模型
DEFAULT_MODELS = [
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
    "MiniMax-M2.1-highspeed",
    "MiniMax-M2",
    "MiMo-V2.5-Pro",
    "MiMo-V2.5",
    "MiMo-V2-Flash",
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
        # 始终返回 Provider 全量模型（不受 account.models 限制）
        return DEFAULT_MODELS

    # ---- Health Check ----

    async def health_check(self) -> bool:
        """健康检查：调用 agent.minimaxi.com 的 device/register 端点
        （对齐 Chat2API src/main/proxy/adapters/minimax.ts requestDeviceInfo）

        - JWT 格式 API Key → 解析 user_id → 构造 device/register 请求
        - 200 + statusInfo.code==0 → 凭证有效
        """
        try:
            await self.login()
            api_key = self._api_key

            # 解析 realUserID（从 JWT 解析或拆解 userId+token 格式）
            real_user_id = None
            jwt_token = api_key
            if api_key and "+" in api_key:
                parts = api_key.split("+", 1)
                real_user_id = parts[0]
                jwt_token = parts[1] if len(parts) > 1 else api_key
            else:
                # 尝试从 JWT 解析 user_id
                import base64
                try:
                    if api_key and api_key.count(".") == 2:
                        parts = api_key.split(".")
                        payload_b64 = parts[1]
                        padding = 4 - len(payload_b64) % 4
                        if padding != 4:
                            payload_b64 += "=" * padding
                        payload = json.loads(
                            base64.urlsafe_b64decode(payload_b64).decode("utf-8", errors="replace")
                        )
                        # JWT 中 user 在嵌套对象里 (e.g. {"user": {"id": "..."}})
                        nested_user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
                        real_user_id = (
                            payload.get("user_id")
                            or payload.get("id")
                            or nested_user.get("id")
                        )
                except Exception:
                    pass

            if not real_user_id:
                logger.warning("[MiniMax] health_check: failed to extract realUserID from token")
                return False

            # 构造 device/register 请求（对齐 Chat2API）
            import time
            import hashlib
            import uuid as uuidlib

            AGENT_BASE = "https://agent.minimaxi.com"
            random_uuid = str(uuidlib.uuid4())
            unix_ms = str(int(time.time() * 1000))
            timestamp = int(time.time())

            user_data = {
                "device_platform": "web",
                "biz_id": "3",
                "app_id": "3001",
                "version_code": "22201",
                "uuid": random_uuid,
                "device_id": None,
                "os_name": "Mac",
                "browser_name": "chrome",
                "device_memory": 8,
                "cpu_core_num": 11,
                "browser_language": "zh-CN",
                "browser_platform": "MacIntel",
                "user_id": real_user_id,
                "screen_width": 1920,
                "screen_height": 1080,
                "unix": unix_ms,
                "lang": "zh",
                "token": jwt_token,
                "timezone_offset": 28800,
                "sys_language": "zh",
                "client": "web",
            }

            # 构造 query string
            query_str = "&".join(
                f"{k}={v}" for k, v in user_data.items() if v is not None
            )
            data_json = json.dumps({"uuid": random_uuid})
            full_uri = f"/v1/api/user/device/register?{query_str}"
            unix_md5 = hashlib.md5(unix_ms.encode("utf-8")).hexdigest()
            yy = hashlib.md5(
                f"{full_uri}_{data_json}{unix_md5}ooui".encode("utf-8")
            ).hexdigest()
            signature = hashlib.md5(
                f"{timestamp}{jwt_token}{data_json}".encode("utf-8")
            ).hexdigest()

            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Content-Type": "application/json",
                "Origin": AGENT_BASE,
                "Referer": f"{AGENT_BASE}/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                "token": jwt_token,
                "x-timestamp": str(timestamp),
                "x-signature": signature,
                "yy": yy,
            }

            session = await self._transport._get_session()
            async with session.post(
                f"{AGENT_BASE}{full_uri}",
                json={"uuid": random_uuid},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"[MiniMax] health_check HTTP {resp.status}")
                    return False
                body = await resp.json()
                status_info = body.get("statusInfo", {}) if isinstance(body, dict) else {}
                if status_info.get("code") == 0:
                    return True
                logger.debug(
                    f"[MiniMax] health_check failed: code={status_info.get('code')}, "
                    f"message={status_info.get('message', '')[:100]}"
                )
                return False
        except Exception as e:
            logger.debug(f"[MiniMax] health_check failed: {type(e).__name__}: {e}")
            return False
