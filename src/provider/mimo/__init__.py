# -*- coding: utf-8 -*-
"""
MiMo (Xiaomi AI Studio) Provider Adapter
参考 Chat2API-main/src/main/proxy/adapters/mimo.ts 重写

网页 API 协议：
- Base URL: https://aistudio.xiaomimimo.com
- 认证: Cookie（serviceToken, userId, xiaomichatbot_ph）
- 对话: POST /open-apis/bot/chat（SSE 流）
- 会话保存: POST /open-apis/chat/conversation/save
- 会话删除: POST /open-apis/chat/conversation/delete

配置方式：
1. 登录 https://aistudio.xiaomimimo.com
2. 打开 DevTools -> Application -> Cookies
3. 提取 serviceToken, userId, xiaomichatbot_ph

支持的模型：
- mimo-v2.5-pro（最新旗舰）
- mimo-v2.5（通用）
- mimo-v2-flash（快速响应）
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Optional, List

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, ChatMessage, ProviderResponse, StreamChunk
from src.core.exceptions import ProviderError, AuthError
from src.core.logger import logger
from src.provider.base import BaseProvider, ProviderRegistry

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────
MIMO_BASE = "https://aistudio.xiaomimimo.com"
MIMO_CHAT_URL = f"{MIMO_BASE}/open-apis/bot/chat"
MIMO_CONVERSATION_SAVE_URL = f"{MIMO_BASE}/open-apis/chat/conversation/save"
MIMO_CONVERSATION_DELETE_URL = f"{MIMO_BASE}/open-apis/chat/conversation/delete"

# ─────────────────────────────────────────────────────────────
# Default Headers (matching Chat2API-main)
# ─────────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Origin": MIMO_BASE,
    "Referer": f"{MIMO_BASE}/",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="144", "Not(A:Brand";v="8", "Google Chrome";v="144"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Timezone": "Asia/Shanghai",
}

# ─────────────────────────────────────────────────────────────
# Model Configuration (aligned with Chat2API-main)
# ─────────────────────────────────────────────────────────────
DEFAULT_MODELS = [
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "mimo-v2-flash",
]

# Display name -> internal model name mapping
MODEL_MAPPINGS = {
    "mimo-v2.5-pro": "mimo-v2.5-pro",
    "mimo-v2.5": "mimo-v2.5",
    "mimo-v2-flash": "mimo-v2-flash",
    # Backward compat
    "mimo-v2-pro": "mimo-v2.5-pro",
    "mimo-v2-omni": "mimo-v2.5",
    "mimo-v2": "mimo-v2.5",
    # Short forms
    "flash": "mimo-v2-flash",
    "pro": "mimo-v2.5-pro",
}


# ─────────────────────────────────────────────────────────────
# UUID Helper (matching Chat2API-main's uuid(false))
# ─────────────────────────────────────────────────────────────
def _uuid_no_hyphens() -> str:
    """Generate UUID without hyphens (32-char hex), matching Chat2API-main uuid(false)."""
    return uuid.uuid4().hex


# ─────────────────────────────────────────────────────────────
# Citation Stripping (from Chat2API-main)
# ─────────────────────────────────────────────────────────────
def strip_citations(text: str) -> str:
    """Strip citation markers like (citation:1), [1], etc."""
    text = re.sub(r'从\(citation:\d+\)中[：:]\s*', '', text)
    text = re.sub(r'-?\s*citation:\d+[：:]\s*', '', text)
    text = re.sub(r'[（\(]\s*citation:\d+(?:,\s*citation:\d+)*\s*[）\)]', '', text)
    text = re.sub(r'citation:\d+(?:,\s*citation:\d+)*', '', text)
    text = re.sub(r'\(citation:\d+\)', '', text)
    text = re.sub(r'\[\d+\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def strip_citations_streaming(text: str, buffer: list) -> str:
    """Strip citations in streaming mode with buffer for partial matches."""
    combined = buffer[0] + text if buffer else text

    cleaned = combined
    cleaned = re.sub(r'从\(citation:\d+\)中[：:]\s*', '', cleaned)
    cleaned = re.sub(r'-?\s*citation:\d+[：:]\s*', '', cleaned)
    cleaned = re.sub(r'[（\(]\s*citation:\d+(?:,\s*citation:\d+)*\s*[）\)]', '', cleaned)
    cleaned = re.sub(r'citation:\d+(?:,\s*citation:\d+)*', '', cleaned)
    cleaned = re.sub(r'\(citation:\d+\)', '', cleaned)
    cleaned = re.sub(r'\[\d+\]', '', cleaned)

    # Check for incomplete citation at end
    citation_start = cleaned.rfind('(citation')
    if citation_start != -1:
        after = cleaned[citation_start:]
        if ')' not in after:
            buffer.clear()
            buffer.append(after)
            cleaned = cleaned[:citation_start]
        else:
            buffer.clear()
    else:
        buffer.clear()

    return re.sub(r'\s+', ' ', cleaned).strip()


# ─────────────────────────────────────────────────────────────
# Think Tag Processing (from Chat2API-main)
# ─────────────────────────────────────────────────────────────
def strip_think_tags(text: str) -> str:
    """Strip <think> tags from content."""
    text = text.replace('\x00', '')
    text = re.sub(r'^<think[^>]*>', '', text)
    text = re.sub(r'^&gt;', '', text)
    # Handle partial tag remnants
    for partial in ['hink>', 'ink>', 'nk>', 'k>', '>']:
        if text.startswith(partial):
            text = text[len(partial):]
    return text


def strip_think(text: str) -> str:
    """Remove all think content from text."""
    text = text.replace('\x00', '')
    text = re.sub(r'<think[\s\S]*?</think>', '', text)
    text = re.sub(r'<think[\s\S]*?</thinkgt;', '', text)
    open_idx = text.find('<think')
    if open_idx != -1:
        text = text[:open_idx]
    return text.strip()


def extract_think_content(text: str) -> tuple[str, str]:
    """Extract thinking and content separately from text with <think> tags.
    Returns (thinking, content) tuple.
    """
    thinking = ''
    content = text

    # Match complete <think>...</think> blocks
    for m in re.finditer(r'<think[^>]*>([\s\S]*?)</think>', text):
        thinking += m.group(1)

    # Match <think>...</thinkgt; (malformed closing)
    for m in re.finditer(r'<think[^>]*>([\s\S]*?)</thinkgt;', text):
        thinking += m.group(1)

    content = strip_think(text)

    # Handle unclosed <think> tag
    open_idx = text.find('<think')
    if open_idx != -1 and '</think' not in text and '</thinkgt;' not in text:
        partial = text[open_idx:]
        thinking += re.sub(r'<think[^>]*>', '', partial)

    return thinking, content


# ─────────────────────────────────────────────────────────────
# Multi-turn Query Builder (from Chat2API-main buildMimoQuery)
# ─────────────────────────────────────────────────────────────
def _extract_text_content(content: str | list) -> str:
    """Extract text from message content (string or multimodal list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get('type') == 'text' and part.get('text'):
                parts.append(part['text'])
        return '\n'.join(parts)
    return ''


def build_mimo_query(messages: list[ChatMessage]) -> str:
    """Build query string from OpenAI messages with role prefixes.

    Single user message: return content directly.
    Multi-turn: prefix each message with role (System/User/Assistant).
    """
    entries: list[tuple[str, str]] = []

    for msg in messages:
        content = _extract_text_content(msg.content).strip()
        if not content:
            continue

        role = msg.role
        if role == 'system':
            role = 'System'
        elif role == 'assistant':
            role = 'Assistant'
        else:
            role = 'User'

        entries.append((role, content))

    # Single user message: return directly
    if len(entries) == 1 and entries[0][0] == 'User':
        return entries[0][1]

    return '\n\n'.join(f'{role}: {content}' for role, content in entries)


# ─────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────
@ProviderRegistry.register("mimo")
class MiMoProvider(BaseProvider):
    """小米 MiMo AI Studio 网页 API 适配器

    认证要求：
    - serviceToken: 服务凭证（从 Cookie 获取）
    - userId: 用户 ID（从 Cookie 获取）
    - xiaomichatbot_ph: 会话标识（从 Cookie 获取）
    """

    name = "mimo"
    display_name = "小米 MiMo (Xiaomi MiMo)"
    auth_type = "cookie"

    def __init__(self, account: AccountConfig):
        super().__init__(account)

        # Extract credentials from AccountConfig
        # token field -> serviceToken
        # user_id field -> userId
        # xiaomichatbot_ph -> ph token (via extra field)
        self._service_token = (
            account.token
            or getattr(account, "service_token", "")
            or getattr(account, "serviceToken", "")
        )
        self._user_id = (
            account.user_id
            or getattr(account, "userId", "")
        )
        self._ph_token = (
            getattr(account, "xiaomichatbot_ph", "")
            or getattr(account, "ph_token", "")
            or getattr(account, "phToken", "")
        )

        if not self._service_token or not self._user_id or not self._ph_token:
            raise AuthError(
                "MiMo provider requires 3 credentials: serviceToken, userId, xiaomichatbot_ph.\n"
                "Please login to https://aistudio.xiaomimimo.com, open DevTools -> Application -> Cookies,\n"
                "and configure: token=<serviceToken>, user_id=<userId>, xiaomichatbot_ph=<ph value>"
            )

        self._http_session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close(self) -> None:
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    async def list_models(self) -> List[str]:
        return DEFAULT_MODELS

    def _build_cookie(self) -> str:
        return (
            f"serviceToken={self._service_token}; "
            f"userId={self._user_id}; "
            f"xiaomichatbot_ph={self._ph_token}"
        )

    def _build_headers(self) -> dict[str, str]:
        headers = DEFAULT_HEADERS.copy()
        headers["Cookie"] = self._build_cookie()
        return headers

    def _build_url(self, path: str) -> str:
        """Build URL with ph_token query parameter."""
        return f"{MIMO_BASE}{path}?xiaomichatbot_ph={self._ph_token}"

    def _map_model(self, model: str) -> str:
        """Map model name to internal MiMo model name."""
        if not model:
            return "mimo-v2-flash"
        return MODEL_MAPPINGS.get(model, MODEL_MAPPINGS.get(model.lower(), model))

    # ---- Conversation Management ----

    async def _save_conversation(self, conversation_id: str) -> None:
        """Save conversation before sending chat (matching Chat2API-main flow)."""
        session = await self._get_session()
        try:
            async with session.post(
                self._build_url("/open-apis/chat/conversation/save"),
                headers=self._build_headers(),
                json={
                    "conversationId": conversation_id,
                    "title": "新对话",
                    "type": "chat",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                code = data.get("code", -1)
                if resp.status != 200 or code != 0:
                    msg = data.get("msg") or data.get("message") or f"HTTP {resp.status}"
                    raise ProviderError(
                        f"MiMo save conversation failed: {msg}",
                        provider="mimo",
                    )
        except aiohttp.ClientError as e:
            raise ProviderError(f"MiMo save conversation network error: {e}", provider="mimo")

    async def _delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation after use (cleanup)."""
        session = await self._get_session()
        try:
            async with session.post(
                self._build_url("/open-apis/chat/conversation/delete"),
                headers=self._build_headers(),
                json=[conversation_id],
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                return resp.status == 200 and data.get("code") == 0
        except Exception as e:
            logger.warning(f"[MiMo] Failed to delete conversation {conversation_id[:8]}: {e}")
            return False

    # ---- Health Check ----

    async def health_check(self) -> bool:
        """Health check: try save+delete a test conversation."""
        try:
            test_conv = _uuid_no_hyphens()
            await self._save_conversation(test_conv)
            await self._delete_conversation(test_conv)
            return True
        except Exception as e:
            logger.error(f"[MiMo] Health check failed: {e}")
            return False

    # ---- Chat Completion (non-stream) ----

    async def chat_completion(self, request: ChatCompletionRequest) -> ProviderResponse:
        """Non-stream chat completion via stream collection."""
        try:
            content_parts: List[str] = []
            reasoning_parts: List[str] = []
            usage_data: dict = {}

            async for chunk in self.chat_completion_stream(request):
                if chunk.content:
                    content_parts.append(chunk.content)
                if chunk.reasoning_content:
                    reasoning_parts.append(chunk.reasoning_content)
                if chunk.usage:
                    usage_data = chunk.usage

            content = "".join(content_parts)
            reasoning = "".join(reasoning_parts)

            message: dict[str, Any] = {"role": "assistant", "content": content}
            if reasoning:
                message["reasoning_content"] = reasoning

            return ProviderResponse(
                status_code=200,
                data={
                    "id": f"chatcmpl-{_uuid_no_hyphens()[:24]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request.model or "mimo-v2-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": usage_data.get("prompt_tokens", 0),
                        "completion_tokens": usage_data.get("completion_tokens", 0),
                        "total_tokens": usage_data.get("total_tokens", 0),
                    },
                },
            )

        except Exception as e:
            logger.error(f"[MiMo] Non-stream error: {e}")
            raise

    # ---- Chat Completion (stream) ----

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completion via MiMo SSE protocol.

        SSE format:
            event: text
            data: {"content":"Hello"}

            event: message
            data: {"content":"world"}

            event: usage
            data: {"promptTokens":10,"completionTokens":5,...}

            event: dialogId
            data: {"content":"abc123"}

            event: finish
            data: {}
        """
        session = await self._get_session()

        # Map model
        actual_model = self._map_model(request.model)

        # Build query from messages
        query = build_mimo_query(request.messages)

        # Generate IDs
        conversation_id = _uuid_no_hyphens()
        msg_id = _uuid_no_hyphens()[:32]

        # Determine thinking mode
        model_lower = (request.model or "").lower()
        enable_thinking = bool(
            model_lower.endswith("-think")
            or model_lower.endswith("-r1")
            or "think" in model_lower.split('-')[-1]
            or "reasoning" in model_lower
        )

        # Temperature
        temperature = request.temperature if request.temperature is not None else 0.8
        top_p = request.top_p if request.top_p is not None else 0.95

        # Build request body (matching Chat2API-main exactly)
        payload = {
            "msgId": msg_id,
            "conversationId": conversation_id,
            "query": query,
            "isEditedQuery": False,
            "modelConfig": {
                "enableThinking": enable_thinking,
                "webSearchStatus": "disabled",
                "model": actual_model,
                "temperature": temperature,
                "topP": top_p,
            },
            "multiMedias": [],
        }

        headers = self._build_headers()

        logger.info(
            f"[MiMo] Stream: model={actual_model} thinking={enable_thinking} "
            f"conv={conversation_id[:8]} query_len={len(query)}"
        )

        conversation_saved = False

        try:
            # Step 1: Save conversation
            try:
                await self._save_conversation(conversation_id)
                conversation_saved = True
            except ProviderError as e:
                logger.warning(f"[MiMo] Save conversation failed (continuing): {e}")

            # Step 2: Send chat request
            async with session.post(
                self._build_url("/open-apis/bot/chat"),
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise ProviderError(
                        f"MiMo API error: HTTP {resp.status} - {text[:200]}",
                        provider="mimo",
                    )

                # Parse SSE stream
                async for chunk in self._parse_sse_stream(
                    resp, actual_model, enable_thinking
                ):
                    yield chunk

        except aiohttp.ClientError as e:
            raise ProviderError(f"MiMo network error: {e}", provider="mimo")
        finally:
            # Cleanup: delete conversation
            if conversation_saved:
                asyncio_create = self._delete_conversation(conversation_id)
                # Fire-and-forget cleanup
                import asyncio
                asyncio.ensure_future(asyncio_create)

    async def _parse_sse_stream(
        self,
        resp: aiohttp.ClientResponse,
        actual_model: str,
        enable_thinking: bool,
    ) -> AsyncIterator[StreamChunk]:
        """Parse MiMo SSE stream with thinking/citation support.

        Handles chunk types: text, message, usage, dialogId, finish.
        Processes <think> tags and citations.
        """
        # State tracking
        state: str = "init"  # init -> thinking -> content
        total_content = ""
        last_processed = 0
        think_end_found = False
        THINK_END_1 = "</think>"
        THINK_END_2 = "</thinkgt;"

        # Citation buffers
        citation_buf: list = []
        thinking_citation_buf: list = []

        # Usage tracking
        usage_data: dict = {}

        buffer = ""
        current_event = ""

        async for raw_line in resp.content:
            try:
                line_text = raw_line.decode("utf-8", errors="replace")
            except Exception:
                continue

            buffer += line_text
            lines = buffer.split("\n")
            buffer = lines.pop() if lines else ""

            for line in lines:
                trimmed = line.strip()

                if trimmed.startswith("event:"):
                    current_event = trimmed[6:].strip()
                    continue

                if not trimmed.startswith("data:"):
                    continue

                # Parse JSON data
                json_str = trimmed[5:].strip()
                if not json_str:
                    continue

                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    logger.warning(f"[MiMo] SSE parse error: {json_str[:80]}")
                    continue

                chunk_type = data.get("type", current_event)

                # Handle text/message chunks
                if chunk_type in ("text", "message"):
                    content = (data.get("content") or "").replace("\x00", "")
                    if not content:
                        continue

                    total_content += content

                    # State machine for thinking mode
                    if state == "init":
                        think_start = total_content.find("<think")
                        if think_start != -1:
                            state = "thinking"
                            last_processed = think_start
                        else:
                            state = "content"

                    if state == "thinking" and not think_end_found:
                        # Look for think end tag
                        end_idx = total_content.find(THINK_END_1, last_processed)
                        actual_end = THINK_END_1

                        if end_idx == -1:
                            end_idx = total_content.find(THINK_END_2, last_processed)
                            actual_end = THINK_END_2

                        if end_idx != -1:
                            think_end_found = True
                            think_raw = total_content[last_processed:end_idx]
                            think_clean = strip_think_tags(think_raw)
                            think_clean = strip_citations_streaming(
                                think_clean, thinking_citation_buf
                            )
                            if think_clean:
                                yield StreamChunk(
                                    reasoning_content=think_clean,
                                    model=actual_model,
                                )
                            last_processed = end_idx + len(actual_end)
                            state = "content"
                        else:
                            # Still thinking
                            think_raw = total_content[last_processed:]
                            think_clean = strip_think_tags(think_raw)
                            think_clean = strip_citations_streaming(
                                think_clean, thinking_citation_buf
                            )
                            if think_clean:
                                yield StreamChunk(
                                    reasoning_content=think_clean,
                                    model=actual_model,
                                )
                            last_processed = len(total_content)

                    if state == "content" and last_processed < len(total_content):
                        content_part = total_content[last_processed:]
                        cleaned = strip_citations_streaming(
                            content_part, citation_buf
                        )
                        if cleaned:
                            yield StreamChunk(
                                content=cleaned,
                                model=actual_model,
                            )
                        last_processed = len(total_content)

                elif chunk_type == "usage":
                    usage = data.get("usage", data)
                    prompt_tokens = usage.get("promptTokens", 0)
                    completion_tokens = usage.get("completionTokens", 0)
                    total_tokens = usage.get("totalTokens", 0)
                    reasoning_tokens = usage.get("reasoningTokens", 0)

                    usage_data = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    }

                    yield StreamChunk(
                        content="",
                        model=actual_model,
                        usage=usage_data,
                    )

                elif chunk_type == "dialogId":
                    dialog_id = data.get("content", "")
                    if dialog_id:
                        logger.debug(f"[MiMo] dialogId={dialog_id[:12]}")

                elif chunk_type == "finish":
                    # Stream complete
                    pass

        # Process any remaining buffer
        if buffer.strip().startswith("data:"):
            json_str = buffer.strip()[5:].strip()
            try:
                data = json.loads(json_str)
                chunk_type = data.get("type", current_event)
                if chunk_type in ("text", "message") and data.get("content"):
                    content = data["content"].replace("\x00", "")
                    cleaned = strip_citations(content)
                    if cleaned:
                        yield StreamChunk(content=cleaned, model=actual_model)
            except json.JSONDecodeError:
                pass
