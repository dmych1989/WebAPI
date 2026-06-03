# -*- coding: utf-8 -*-
"""WebAPI — OpenAI 兼容 API 路由

端点：
- POST /v1/chat/completions
- GET /v1/models
- GET /health
- GET /stats
"""

from __future__ import annotations

import json
import time
import traceback
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from src.core.logger import logger
from src.core.stats import stats_tracker

from src.core.config import get_config
from src.core.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelInfo,
    ModelListResponse,
    StreamChunk,
)
from src.core.exceptions import (
    WebAPIError,
    AuthError,
    RateLimitError,
    NoAvailableProvider,
    TokenExpiredError,
)
from src.provider.base import ProviderDispatcher
from src.provider.registry import model_mapper
from src.pool import account_pool
from src.core.context_manager import context_manager
from src.core.tool_calling import tool_calling

router = APIRouter()

# 延迟初始化调度器（避免循环导入）
_dispatcher: ProviderDispatcher | None = None


def _get_dispatcher() -> ProviderDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ProviderDispatcher(
            model_mapper=model_mapper,
            load_balancer=account_pool,
        )
    return _dispatcher


# =============================================================================
# POST /v1/chat/completions
# =============================================================================

@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI 兼容 Chat Completions API

    支持流式 (stream=True) 和非流式两种模式。
    """
    logger.info(
        f"[Chat] model={request.model} stream={request.stream} "
        f"messages={len(request.messages)}"
    )

    start_ts = time.time()
    stats_tracker.increment_active()
    is_error = False
    provider_type = request.model.split("-")[0]

    try:
        # 0. 上下文窗口管理
        context_manager.trim(request)

        # 0.5. 工具调用注入
        tool_calling.inject_tools(request)

        # 1. 调度：找到合适的 Provider + 账号
        dispatcher = _get_dispatcher()
        provider, actual_model = await dispatcher.dispatch(request)
        provider_type = provider.name

        # 2. 增加并发计数
        account_pool.increment_concurrent(provider.name, provider.account.name)

        try:
            if request.stream:
                # 流式模式
                return StreamingResponse(
                    _stream_response(provider, request, actual_model),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            else:
                # 非流式模式
                response = await provider.chat_completion(request)
                account_pool.mark_healthy(provider.name, provider.account.name)
                return JSONResponse(
                    status_code=response.status_code,
                    content=response.data,
                )
        finally:
            # 减少并发计数
            account_pool.decrement_concurrent(provider.name, provider.account.name)

    except NoAvailableProvider as e:
        is_error = True
        stats_tracker.record_error(provider_type, request.model, "no_available_provider")
        return _error_response(503, str(e))
    except AuthError as e:
        is_error = True
        # 标记账号不健康
        try:
            dispatcher = _get_dispatcher()
            ptype, _ = dispatcher.model_mapper.map(request.model)
            for s in account_pool._accounts.get(ptype, []):
                account_pool.mark_unhealthy(ptype, s.name, f"auth_error: {e}")
        except Exception:
            pass
        stats_tracker.record_error(provider_type, request.model, "auth_error")
        return _error_response(401, str(e))
    except RateLimitError as e:
        is_error = True
        stats_tracker.record_error(provider_type, request.model, "rate_limit")
        return _error_response(429, str(e))
    except WebAPIError as e:
        is_error = True
        stats_tracker.record_error(provider_type, request.model, type(e).__name__)
        return _error_response(e.status_code, str(e))
    except Exception as e:
        is_error = True
        logger.error(f"[Chat] Unexpected error: {traceback.format_exc()}")
        stats_tracker.record_error(provider_type, request.model, "internal_error")
        return _error_response(500, f"Internal server error: {e}")
    finally:
        stats_tracker.decrement_active()
        if not is_error:
            latency = (time.time() - start_ts) * 1000
            stats_tracker.record_request(provider_type, request.model, success=True, latency_ms=latency)


async def _stream_response(
    provider, request: ChatCompletionRequest, actual_model: str
):
    """流式响应生成器（OpenAI 严格兼容）

    关键点（修复 Cherry Studio 等客户端的 "Connection closed" 错误）：
    1. 第一个 chunk 必须是单独的 role chunk（delta: {role: "assistant"}，无 content）
    2. 每个 chunk 的 finish_reason 在非终态时必须省略（而非 null）
    3. 终态 chunk 用 delta: {} + finish_reason: "stop"（不带 content）
    4. 保持稳定的 request_id/created/model 字段
    5. 使用 \r\n 分隔（SSE 规范，部分 SDK 严格要求）
    6. 每隔 10s 发送 ": keep-alive\r\n\r\n" 注释防超时
    """
    request_id = f"chatcmpl-{uuid4().hex[:12]}"
    created = int(time.time())
    is_first = True
    last_send_ts = time.time()

    async def _send_event(payload: dict) -> str:
        """序列化并包装成 SSE 事件，使用 \\r\\n 分隔"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\r\n\r\n"

    async def _send_keepalive():
        """发送 SSE 注释心跳（Cherry Studio 等客户端需要）"""
        return ": keep-alive\r\n\r\n"

    def _base_chunk(delta: dict, finish_reason: Optional[str] = None) -> dict:
        """构造基础 chunk 字典"""
        return {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": actual_model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    **({"finish_reason": finish_reason} if finish_reason else {}),
                }
            ],
        }

    try:
        # ── 1) 先发 role-only 块（严格 OpenAI 协议） ──
        role_chunk = _base_chunk({"role": "assistant", "content": ""})
        yield await _send_event(role_chunk)
        last_send_ts = time.time()
        is_first = False

        # ── 2) 主循环：转发 content 块 ──
        async for chunk in provider.chat_completion_stream(request):
            # 防止长流超时
            if time.time() - last_send_ts > 10:
                yield await _send_keepalive()
                last_send_ts = time.time()

            if chunk.content or chunk.reasoning_content:
                delta: dict = {}
                if chunk.content:
                    delta["content"] = chunk.content
                if chunk.reasoning_content:
                    delta["reasoning_content"] = chunk.reasoning_content
                yield await _send_event(_base_chunk(delta))
                last_send_ts = time.time()

        # ── 3) 终态块：delta: {} + finish_reason: "stop" ──
        yield await _send_event(_base_chunk({}, finish_reason="stop"))

        # ── 4) 终止标记 ──
        yield "data: [DONE]\r\n\r\n"

    except Exception as e:
        logger.error(f"[Stream] Error: {traceback.format_exc()}")
        # 尝试发送错误块（保持流可被客户端识别为已结束）
        try:
            err_payload = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": actual_model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "error": {"message": str(e), "type": "stream_error"},
            }
            yield await _send_event(err_payload)
            yield "data: [DONE]\r\n\r\n"
        except Exception:
            pass


def _chunk_to_openai(
    chunk: StreamChunk,
    model: str,
    request_id: Optional[str] = None,
    created: Optional[int] = None,
    include_role: bool = False,
) -> dict:
    """StreamChunk → OpenAI Delta Chunk（保留兼容旧调用）"""
    delta: dict = {}
    if include_role:
        delta["role"] = "assistant"
    if chunk.content:
        delta["content"] = chunk.content
    if chunk.reasoning_content:
        delta["reasoning_content"] = chunk.reasoning_content
    if chunk.tool_calls:
        delta["tool_calls"] = chunk.tool_calls

    return {
        "id": request_id or f"chatcmpl-{model}",
        "object": "chat.completion.chunk",
        "created": created or int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": chunk.finish_reason,
            }
        ],
    }


# =============================================================================
# GET /v1/models
# =============================================================================

@router.get("/v1/models")
async def list_models():
    """OpenAI 兼容的 /v1/models 端点

    遍历配置中所有 Provider 的所有账号，合并可用模型列表返回。
    优先使用 account.models 配置；若为空则回退到 provider.list_models()。
    即使 enabled=False 也会返回，让用户能完整看到所有已配置的模型。
    """
    from src.core.config import get_config
    from src.provider.base import ProviderRegistry

    config = get_config()
    seen: set[str] = set()  # 去重 (model_id, owned_by)
    models: list[ModelInfo] = []

    for provider_type, provider_config in config.providers.items():
        provider_cls = ProviderRegistry.get(provider_type)
        # 先确定 fallback 模型列表（来自 Provider 自身）
        fallback_models: list[str] = []
        if provider_cls is not None:
            try:
                tmp_account = provider_config.accounts[0] if provider_config.accounts else None
                if tmp_account is not None:
                    tmp_instance = ProviderRegistry.create(provider_type, tmp_account)
                    fallback_models = await tmp_instance.list_models()
            except Exception:
                pass

        for account in provider_config.accounts:
            # 优先使用 account.models 配置；为空时使用 provider.list_models()
            account_models = account.models or []
            if not account_models and fallback_models:
                account_models = fallback_models
            for model_name in account_models:
                key = (model_name, provider_type)
                if key in seen:
                    continue
                seen.add(key)
                models.append(ModelInfo(id=model_name, owned_by=provider_type))

    return ModelListResponse(data=models)


# =============================================================================
# GET /health
# =============================================================================

@router.get("/health")
async def health():
    """健康检查"""
    pool_status = account_pool.get_pool_status()
    enabled_providers = {
        k: len(v) for k, v in pool_status.items()
    }

    return {
        "status": "ok",
        "version": "0.1.0",
        "providers": enabled_providers,
        "pool": pool_status,
    }


# =============================================================================
# GET /stats
# =============================================================================

@router.get("/stats")
async def stats():
    """请求统计"""
    snapshot = stats_tracker.get_snapshot()
    snapshot["pool"] = account_pool.get_pool_status()
    snapshot["models_available"] = len(model_mapper.list_models())
    return snapshot


# =============================================================================
# GET /
# =============================================================================

@router.get("/")
async def root():
    return {
        "service": "WebAPI",
        "version": "0.1.0",
        "docs": "/v1/docs",
        "health": "/health",
        "endpoints": {
            "chat_completions": "POST /v1/chat/completions",
            "models": "GET /v1/models",
        },
    }


# =============================================================================
# 错误响应
# =============================================================================

def _error_response(status_code: int, message: str) -> JSONResponse:
    """OpenAI 兼容错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": "server_error" if status_code >= 500 else "invalid_request_error",
                "code": str(status_code),
            }
        },
    )
