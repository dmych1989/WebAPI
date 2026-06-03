# -*- coding: utf-8 -*-
"""WebAPI — 核心数据模型

定义 OpenAI 兼容的请求/响应模型和内部数据模型。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field


# =============================================================================
# OpenAI 兼容请求模型
# =============================================================================

class ChatMessage(BaseModel):
    """Chat 消息"""
    role: str = "user"  # system, user, assistant, tool
    content: str | list[dict[str, Any]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None


class ToolDefinition(BaseModel):
    """函数工具定义"""
    type: str = "function"
    function: dict[str, Any]


class ChatCompletionRequest(BaseModel):
    """OpenAI 兼容 Chat Completion 请求"""
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    max_tokens: Optional[int] = None
    stop: Optional[str | list[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[dict[str, float]] = None
    user: Optional[str] = None
    tools: Optional[list[ToolDefinition]] = None
    tool_choice: Optional[str | dict] = None

    # 扩展字段（部分 Provider 支持）
    web_search: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    deep_research: Optional[bool] = None


# =============================================================================
# OpenAI 兼容响应模型
# =============================================================================

class ChatChoice(BaseModel):
    """选择项"""
    index: int = 0
    message: Optional[ChatMessage] = None
    delta: Optional[dict[str, Any]] = None
    finish_reason: Optional[str] = None


class UsageInfo(BaseModel):
    """Token 使用统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """非流式 Chat Completion 响应"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Optional[UsageInfo] = None


class ModelInfo(BaseModel):
    """模型信息"""
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "webapi"


class ModelListResponse(BaseModel):
    """模型列表响应"""
    object: str = "list"
    data: list[ModelInfo]


# =============================================================================
# 内部数据模型
# =============================================================================

class ProviderResponse(BaseModel):
    """Provider Adapter 返回的标准格式"""
    status_code: int
    data: Optional[dict] = None
    session_id: Optional[str] = None
    headers: dict = Field(default_factory=dict)


class StreamChunk(BaseModel):
    """流式数据块"""
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    model: str = ""
    usage: Optional[dict] = None


class AccountState(BaseModel):
    """账号池中的账号状态"""
    id: str
    provider: str
    name: str
    healthy: bool = True
    last_checked: float = 0
    fail_count: int = 0
    cooldown_until: float = 0
    concurrent_requests: int = 0
