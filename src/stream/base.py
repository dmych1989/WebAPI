# -*- coding: utf-8 -*-
"""WebAPI — Stream Handler Base

SSE 流式 → OpenAI 兼容 SSE 格式转换。
参考 Chat2API 的 stream.ts StreamHandler 模式。

每个 Provider 需要实现自己的 StreamHandler 子类，
处理 Provider 特有的 SSE 数据格式。
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from src.core.logger import logger

from src.core.models import StreamChunk, ToolDefinition


# =============================================================================
# Base Stream Handler
# =============================================================================

class BaseStreamHandler(ABC):
    """流式处理基类

    每个 Provider 各有一个子类实现，负责：
    1. 解析 Provider 特有的 SSE 格式
    2. 转换为统一的 StreamChunk
    3. 输出 OpenAI 兼容 SSE 字符串
    """

    def __init__(self, actual_model: str):
        self.actual_model = actual_model
        self.request_id = f"chatcmpl-{uuid4().hex[:12]}"
        self.created = int(time.time())

    @abstractmethod
    async def parse_chunk(self, raw_line: str) -> Optional[StreamChunk]:
        """解析单个 SSE 数据行 → StreamChunk

        Args:
            raw_line: SSE data 字段的原始内容

        Returns:
            StreamChunk 或 None（如果此 chunk 无用）
        """
        ...

    async def handle_stream(
        self, raw_stream: AsyncIterator[str]
    ) -> AsyncIterator[str]:
        """处理原始 SSE 流 → OpenAI 兼容 SSE 字符串

        Usage:
            async for chunk in handler.handle_stream(raw_stream):
                yield chunk  # 已经是 "data: {...}\n\n" 格式
        """
        async for line in raw_stream:
            line = line.strip()
            if not line:
                continue

            chunk = await self.parse_chunk(line)
            if chunk is None:
                continue

            yield build_sse_message(self._to_openai_chunk(chunk))

        # 发送结束标记
        yield build_sse_message(self._done_chunk())

    async def handle_non_stream(
        self, raw_stream: AsyncIterator[str]
    ) -> dict[str, Any]:
        """收集原始流 → 完整的 ChatCompletion JSON

        Args:
            raw_stream: 原始 SSE 流

        Returns:
            完整的 OpenAI ChatCompletion 响应字典
        """
        full_content = ""
        reasoning_content = ""
        tool_calls_data: list[dict] = []
        finish_reason = "stop"
        usage = {}

        async for line in raw_stream:
            line = line.strip()
            if not line:
                continue

            chunk = await self.parse_chunk(line)
            if chunk is None:
                continue

            full_content += chunk.content
            reasoning_content += chunk.reasoning_content
            if chunk.tool_calls:
                tool_calls_data.extend(chunk.tool_calls)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.usage:
                usage = chunk.usage

        from src.core.models import ChatMessage

        message = ChatMessage(
            role="assistant",
            content=full_content or None,
        )

        # 组装 reasoning_content
        if reasoning_content:
            message.content = (
                f"【思考过程】\n{reasoning_content}\n\n【回答】\n{full_content}"
            )

        # 组装 tool_calls
        if tool_calls_data:
            message.tool_calls = tool_calls_data

        return {
            "id": self.request_id,
            "object": "chat.completion",
            "created": self.created,
            "model": self.actual_model,
            "choices": [
                {
                    "index": 0,
                    "message": message.model_dump(exclude_none=True),
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage or {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    def _to_openai_chunk(self, chunk: StreamChunk) -> dict:
        """StreamChunk → OpenAI Delta Chunk"""
        delta: dict[str, Any] = {}

        if chunk.content:
            delta["content"] = chunk.content
        if chunk.reasoning_content:
            delta["reasoning_content"] = chunk.reasoning_content
        if chunk.tool_calls:
            delta["tool_calls"] = chunk.tool_calls

        return {
            "id": self.request_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.actual_model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": chunk.finish_reason,
                }
            ],
            "usage": chunk.usage,
        }

    def _done_chunk(self) -> dict:
        """生成 [DONE] 块"""
        return {
            "id": self.request_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.actual_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }


# =============================================================================
# SSE 工具函数
# =============================================================================

def build_sse_message(data: dict | str) -> str:
    """将数据转换为 SSE 格式字符串"""
    if isinstance(data, str):
        return f"data: {data}\n\n"
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def convert_sse_to_openai_chunk(
    sse_data: dict,
    model: str,
    request_id: str,
    created: int,
) -> dict:
    """通用 SSE → OpenAI Chunk 转换工具函数"""
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": sse_data.get("delta", {"content": sse_data.get("content", "")}),
                "finish_reason": sse_data.get("finish_reason"),
            }
        ],
    }


class StreamConverter:
    """流式转换器 — 统一入口"""

    @staticmethod
    async def convert(
        handler: BaseStreamHandler,
        raw_stream: AsyncIterator[str],
        stream: bool = False,
    ) -> AsyncIterator[str] | dict[str, Any]:
        """根据 stream 参数决定转换模式"""
        if stream:
            return handler.handle_stream(raw_stream)
        else:
            return await handler.handle_non_stream(raw_stream)