# -*- coding: utf-8 -*-
"""
Qwen (通义千问) Provider Adapter

网页 API 协议:
- Base URL: https://chat2.qianwen.com (对话接口)
- 认证: tongyi_sso_ticket Cookie
- 对话: POST /api/v2/chat（SSE 流）
- Session 管理: POST /api/v2/session/page/list, POST /api/v1/session/delete/batch
- 消息格式: JSON messages 数组
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Optional, List

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry
from src.transport.api_reverse import APIReverseTransport


QWEN_CHAT2_BASE = "https://chat2.qianwen.com"  # ✅ 修正：chat2-api.qianwen.com → chat2.qianwen.com
QWEN_CHAT2_API_BASE = "https://chat2-api.qianwen.com"  # Session 管理
QWEN_CHAT_SIDE_BASE = "https://chat-side.qianwen.com"  # 文件记录删除

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
        """构建通用 URL 参数（扁平化到 payload 中）"""
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
        """流式对话（完整对齐 Chat2API-main 的 qwen.ts chatCompletion 协议）

        关键点：
        - endpoint: /api/v2/chat（Chat2API qwen.ts 协议）
        - payload: 完整 Chat2API 结构（scene/messages/biz_data/protocol_version 等）
        - URL query: 8 个基础参数拼接为 queryString（biz_id/chat_client/device/fr/pr/ut/nonce/timestamp）
        - 响应解析: SSE data: 事件，content 来自 data.messages[].content
        - 深度思考: data.multi_load[deep_think].think_content
        """
        await self.login()
        session_id = _short_uuid()
        req_id = _short_uuid()
        ut_uuid = _short_uuid()

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

        # 构建消息内容（OpenAI messages → Qwen 单条 prompt）
        prompt, _ = self._messages_to_qwen(request)

        # 收集 system prompt 并合并到用户消息前（Chat2API 风格）
        system_prompt = ""
        for msg in request.messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_prompt = msg.content
                break

        final_content = (
            f"{system_prompt}\n\nUser: {prompt}" if system_prompt else prompt
        )

        timestamp_ms = int(time.time() * 1000)
        nonce = _random_nonce()

        logger.info(
            f"[Qwen] Stream: model={actual_model} search={enable_search} "
            f"thinking={enable_thinking} session={session_id[:8]}"
        )

        # ✅ Chat2API-main 完整 payload 结构
        payload = {
            "deep_search": "1" if (enable_search or enable_thinking) else "0",
            "req_id": req_id,
            "model": actual_model,
            "scene": "chat",
            "session_id": session_id,
            "sub_scene": "chat",
            "temporary": False,
            "messages": [
                {
                    "content": final_content,
                    "mime_type": "text/plain",
                    "meta_data": {
                        "ori_query": final_content,
                    },
                }
            ],
            "from": "default",
            "parent_req_id": "0",
            "enable_search": enable_search,
            "biz_data": '{"entryPoint":"tongyigw"}',
            "scene_param": "first_turn",
            "chat_client": "h5",
            "client_tm": str(timestamp_ms),
            "protocol_version": "v2",
            "biz_id": "ai_qwen",
        }

        # ✅ Query string 拼接到 URL（与 Chat2API-main 一致的 8 个参数）
        query_string = (
            f"biz_id=ai_qwen&chat_client=h5&device=pc&fr=pc&pr=qwen"
            f"&ut={ut_uuid}&nonce={nonce}&timestamp={timestamp_ms}"
        )
        url = f"{QWEN_CHAT2_BASE}/api/v2/chat?{query_string}"

        logger.debug(f"[Qwen] POST {url}")

        http_session = await self._transport._get_session()
        headers = self._get_auth_headers()

        async with http_session.post(
            url,
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Qwen API error: HTTP {resp.status} — {text[:300]}",
                    provider="qwen",
                )

            is_first = True
            # 跟踪 thinking 内容（用于流式拼接）
            pending_thinking: list[str] = []

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

                # Chat2API 新协议主解析路径
                text, thinking = self._extract_output_v2(data)

                # 思考内容：先 yield 一个 reasoning 块
                if thinking:
                    pending_thinking.append(thinking)
                    yield StreamChunk(
                        content="",
                        model="qwen",
                        role="assistant" if is_first else None,
                        reasoning_content=thinking,
                    )
                    if is_first:
                        is_first = False
                    continue

                if text:
                    if is_first:
                        is_first = False
                    yield StreamChunk(
                        content=text,
                        model="qwen",
                        role="assistant" if is_first else None,
                    )

        logger.debug("[Qwen] Stream done")

    def _extract_output_v2(self, data: dict) -> tuple[str, str]:
        """Chat2API-main 新协议响应解析

        返回 (content, thinking_content):
        - content: 主回复文本（来自 data.messages[].content）
        - thinking_content: 深度思考文本（来自 data.messages[].meta_data.multi_load[].content.think_content）

        完整结构参考 Chat2API-main qwen.ts QwenStreamHandler.handleStream()。
        """
        # 1) 解析 data.messages 数组
        inner = data.get("data", {})
        messages: list[dict] = []
        if isinstance(inner, dict):
            messages = inner.get("messages", []) or []
        elif isinstance(inner, list):
            messages = inner

        # 1a) 收集每个 message 的 thinking 内容（来自 meta_data.multi_load[]）
        # 优先级: deep_think > multimodal_chat_think（避免重复）
        thinking_parts: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            meta = msg.get("meta_data", {}) or {}
            multi_load = meta.get("multi_load", []) or []
            if not isinstance(multi_load, list):
                continue
            # 优先取 deep_think
            deep_think_content = ""
            fallback_content = ""
            for load in multi_load:
                if not isinstance(load, dict):
                    continue
                load_type = load.get("type", "")
                if load_type == "deep_think" and isinstance(load.get("content"), dict):
                    deep_think_content = (
                        load["content"].get("think_content")
                        or load["content"].get("content")
                        or ""
                    )
                    break
                elif load_type == "multimodal_chat_think" and isinstance(load.get("content"), dict):
                    fallback_content = (
                        load["content"].get("think_content")
                        or load["content"].get("content")
                        or ""
                    )
            # 选择 non-empty 的那个
            chosen = deep_think_content or fallback_content
            if chosen and isinstance(chosen, str):
                # 过滤 [(deep_think)] / [(multimodal_chat_think)] 标记
                cleaned = (
                    chosen
                    .replace("[(deep_think)]", "")
                    .replace("[(multimodal_chat_think)]", "")
                )
                if cleaned.strip():
                    thinking_parts.append(cleaned)

        if thinking_parts:
            # 取最长的（Chat2API 风格：每次事件只 emit 新增的 thinking）
            return "", max(thinking_parts, key=len)

        # 2) 主消息内容（data.messages[].content）
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mime = msg.get("mime_type", "")
            content = msg.get("content", "")
            if not content or not isinstance(content, str):
                continue
            # 仅取纯文本/iframe 类型
            if mime not in ("text/plain", "multi_load/iframe"):
                continue
            # 过滤纯 [(deep_think)] 标记
            if content.strip() in ("[(deep_think)]", "[(multimodal_chat_think)]"):
                continue
            cleaned = (
                content
                .replace("[(deep_think)]", "")
                .replace("[(multimodal_chat_think)]", "")
            )
            if cleaned:
                return cleaned, ""

        # 3) 兜底：旧版格式（output.text / choices[].delta.content / text / content）
        output = data.get("output", {})
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str) and text:
                return text, ""

        choices = data.get("choices", [])
        if choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta", {})
            if isinstance(delta, dict) and delta.get("content"):
                return delta["content"], ""

        if isinstance(data.get("text"), str) and data["text"]:
            return data["text"], ""
        if isinstance(data.get("content"), str) and data["content"]:
            return data["content"], ""

        return "", ""

    def _extract_output(self, data: dict) -> str:
        """旧版响应解析（保留以防兼容）

        新协议下 SSE 流由 chat_completion_stream 内部解析，
        本方法仅用于其他调用方兼容旧格式。
        """
        content, _ = self._extract_output_v2(data)
        return content

    # ---- Models ----

    async def list_models(self) -> list[str]:
        # 始终返回 Provider 全量模型（不受 account.models 限制）
        return [
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen3-max",
            "qwen3-max-preview",
            "qwen3-max-thinking-preview",
            "qwen3.5-flash",
            "qwen3.6",
            "qwen3.7-max",
            "qwen3-coder",
            "qwen3-vl-plus",
        ]

    # ---- Session Management ----

    def _extract_session_ids(self, data: dict) -> list[str]:
        """从 Session 列表响应中提取 session_id"""
        candidate_lists: list[list] = []
        for path in [
            ["data", "list"], ["data", "sessions"], ["data", "sessionList"],
            ["data", "records"], ["data", "items"], ["data", "dataList"],
            ["data", "result", "list"], ["data", "result", "records"],
            ["data", "pageData", "list"], ["data", "pageData", "records"],
            ["list"], ["sessions"],
        ]:
            obj: Any = data
            ok = True
            for key in path:
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    ok = False
                    break
            if ok and isinstance(obj, list):
                candidate_lists.append(obj)

        session_ids: set[str] = set()
        for items in candidate_lists:
            for item in items:
                if not isinstance(item, dict):
                    continue
                sid = (
                    item.get("session_id")
                    or item.get("sessionId")
                    or (item.get("session", {}) or {}).get("id")
                    or item.get("id")
                )
                if isinstance(sid, str) and sid:
                    session_ids.add(sid)
        return list(session_ids)

    async def list_sessions(self, page_num: int = 1, cursor: Optional[str] = None) -> dict:
        """获取 Session 列表（分页）

        Returns: {"session_ids": [...], "has_more": bool, "next_cursor": str}
        """
        session = await self._transport._get_session()
        url = f"{QWEN_CHAT2_API_BASE}/api/v2/session/page/list"

        body: dict[str, Any] = {"pageSize": 100, "pageNum": page_num}
        if cursor:
            body["cursor"] = cursor

        async with session.post(
            url,
            json=body,
            headers=self._get_auth_headers(),
            params=self._get_params(),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ProviderError(
                    f"Qwen session list failed: HTTP {resp.status} — {text[:200]}",
                    provider="qwen",
                )
            data = await resp.json()

        if data.get("success") is False:
            raise ProviderError(
                f"Qwen session list success=false: {json.dumps(data)[:200]}",
                provider="qwen",
            )

        inner = data.get("data", {}) or {}
        next_cursor = (
            inner.get("nextCursor")
            or inner.get("next_cursor")
            or inner.get("cursor")
            or ""
        )
        has_more = (
            inner.get("hasMore")
            or inner.get("has_more")
            or (inner.get("page", {}) or {}).get("hasMore")
            or (inner.get("result", {}) or {}).get("hasMore")
            or False
        )

        return {
            "session_ids": self._extract_session_ids(data),
            "has_more": bool(has_more),
            "next_cursor": str(next_cursor) if next_cursor else "",
        }

    async def _delete_related_file_records(self, session_ids: list[str]) -> bool:
        """删除 session 关联的文件记录"""
        if not session_ids:
            return True

        session = await self._transport._get_session()
        url = f"{QWEN_CHAT_SIDE_BASE}/api/v2/file/record/delete"
        timestamp = int(time.time() * 1000)

        async with session.post(
            url,
            json={"sessionIds": session_ids},
            headers=self._get_auth_headers(),
            params=self._get_params({"nonce": _random_nonce(), "timestamp": timestamp}),
        ) as resp:
            if resp.status != 200:
                logger.warning(f"[Qwen] File record delete HTTP {resp.status}")
                return False
            data = await resp.json()
            if data.get("success") is False:
                logger.warning("[Qwen] File record delete success=false")
                return False
            return True

    async def delete_sessions(self, session_ids: list[str]) -> bool:
        """批量删除 sessions（含关联文件记录）"""
        if not session_ids:
            return True

        session = await self._transport._get_session()
        url = f"{QWEN_CHAT2_API_BASE}/api/v1/session/delete/batch"

        async with session.post(
            url,
            json={"session_ids": session_ids},
            headers=self._get_auth_headers(),
            params=self._get_params(),
        ) as resp:
            if resp.status != 200:
                logger.warning(f"[Qwen] Session delete HTTP {resp.status}")
                return False
            data = await resp.json()

        success = data.get("success")
        code = data.get("code")
        msg = data.get("msg", "Unknown error")
        if success is False or (isinstance(code, int) and code != 0):
            logger.warning(f"[Qwen] Session delete failed: {msg}")
            return False

        # 清理关联文件记录
        file_ok = await self._delete_related_file_records(session_ids)
        if not file_ok:
            logger.warning("[Qwen] Sessions deleted but file record cleanup failed")
        return True

    async def delete_session(self, session_id: str) -> bool:
        """删除单个 session"""
        if not session_id:
            return False
        try:
            ok = await self.delete_sessions([session_id])
            if ok:
                logger.info(f"[Qwen] Session deleted: {session_id}")
            return ok
        except Exception as e:
            logger.warning(f"[Qwen] Failed to delete session {session_id}: {e}")
            return False

    async def delete_all_chats(self) -> bool:
        """删除所有聊天记录（全量分页遍历 → 批量删除）"""
        all_ids: list[str] = []
        next_cursor = ""

        for page_num in range(1, 101):
            result = await self.list_sessions(page_num, next_cursor or None)
            all_ids.extend(result["session_ids"])
            if not result["has_more"] or not result["session_ids"]:
                break
            next_cursor = result["next_cursor"]

        # 去重
        seen: set[str] = set()
        unique_ids: list[str] = []
        for sid in all_ids:
            if sid not in seen:
                seen.add(sid)
                unique_ids.append(sid)

        if not unique_ids:
            logger.info("[Qwen] No sessions to delete")
            return True

        logger.info(f"[Qwen] Found {len(unique_ids)} sessions to delete")

        # 分批删除（每批 100）
        for i in range(0, len(unique_ids), 100):
            batch = unique_ids[i : i + 100]
            ok = await self.delete_sessions(batch)
            if not ok:
                return False

        logger.info("[Qwen] All sessions deleted")
        return True

    # ---- Health Check ----

    async def health_check(self) -> bool:
        try:
            await self.login()
            return True
        except Exception:
            return False