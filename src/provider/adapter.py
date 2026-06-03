# -*- coding: utf-8 -*-
"""WebAPI — Provider Adapter 抽象层

参考 Chat2API 的 proxy/adapters/ 架构：
- Adapter：负责协议转换（OpenAI 请求 → 厂商协议）
- StreamHandler：负责流式响应解析（厂商 SSE/Chunk → OpenAI StreamChunk）
- 两者解耦，方便不同厂商独立实现。

设计原则：
- 对已有 BaseProvider 实现零侵入（新旧并行）
- 默认复用现有 BaseProvider，Adapter 作为可选增强
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

import aiohttp

from src.core.config import AccountConfig
from src.core.models import ChatCompletionRequest, StreamChunk
from src.core.logger import logger
from src.transport.api_reverse import APIReverseTransport


# =============================================================================
# Adapter 抽象接口
# =============================================================================

class BaseAdapter(ABC):
    """Provider Adapter 抽象基类

    Adapter 是协议适配层：把 OpenAI 风格的请求转换成厂商私有协议。
    每个 Provider 可实现自己的 Adapter 来处理特殊细节。
    """

    name: str = ""

    def __init__(self, account: AccountConfig):
        self.account = account
        self._transport = APIReverseTransport()

    # ---- 抽象方法 ----

    @abstractmethod
    def build_request(
        self, request: ChatCompletionRequest, actual_model: str
    ) -> dict[str, Any]:
        """构建厂商协议请求体

        Returns:
            {
                "url": "https://...",
                "method": "POST",
                "headers": {...},
                "body": <bytes|dict|str>,
                "is_stream": bool,
            }
        """
        ...

    @abstractmethod
    async def stream_parser(
        self, response: aiohttp.ClientResponse
    ) -> AsyncIterator[StreamChunk]:
        """解析厂商流式响应 → OpenAI StreamChunk

        不同厂商的流式协议差异很大（SSE / Connect / 二进制 / JSON），
        每个 Adapter 实现自己的解析器。
        """
        ...

    # ---- 公共方法 ----

    def get_base_url(self) -> str:
        """获取厂商基础 URL，子类可覆盖"""
        return ""

    async def send(
        self, request: ChatCompletionRequest, actual_model: str
    ) -> aiohttp.ClientResponse:
        """发送请求（基于 build_request 的结果）"""
        req = self.build_request(request, actual_model)
        session = await self._transport._get_session()
        return await session.request(
            req.get("method", "POST"),
            req["url"],
            headers=req.get("headers", {}),
            data=req.get("body"),
            json=None if req.get("body") is not None or isinstance(req.get("body"), (bytes, str)) else req.get("body"),
        )


class BaseStreamHandler(ABC):
    """流式响应处理器

    独立于 Adapter，允许在多个 Provider 间复用流式解析逻辑。
    """

    @abstractmethod
    async def parse(
        self, response: aiohttp.ClientResponse
    ) -> AsyncIterator[StreamChunk]:
        """解析流式响应"""
        ...

    @staticmethod
    def parse_sse_data(line: str) -> str:
        """通用 SSE data 字段解析（提取 `data: {...}` 中的内容）"""
        line = line.strip()
        if not line:
            return ""
        if line.startswith("data:"):
            return line[5:].strip()
        return line


# =============================================================================
# Provider Forwarder 注册表
# =============================================================================

class ProviderForwarder:
    """Provider 转发器

    参考 Chat2API 的 RequestForwarder，集中管理所有 Provider 的请求转发逻辑。
    替代散落在 routes.py 里的 if-elif 分支。
    """

    def __init__(self):
        self._forwarders: dict[str, callable] = {}

    def register(self, name: str, forwarder_fn: callable) -> None:
        """注册 Provider 转发函数"""
        self._forwarders[name] = forwarder_fn
        logger.debug(f"[Forwarder] Registered: {name}")

    def get(self, name: str) -> Optional[callable]:
        """获取 Provider 转发函数"""
        return self._forwarders.get(name)

    def list_all(self) -> list[str]:
        """列出所有已注册的 Provider"""
        return list(self._forwarders.keys())

    def has(self, name: str) -> bool:
        return name in self._forwarders


# 全局 Forwarder 单例
provider_forwarder = ProviderForwarder()
