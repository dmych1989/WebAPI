# -*- coding: utf-8 -*-
"""WebAPI — Provider 抽象基类与注册中心

设计参考 Chat2API 的 ProviderForwarder + AIClient2API 的 ApiServiceAdapter。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from src.core.config import AccountConfig, ProviderConfig
from src.core.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderResponse,
    StreamChunk,
)
from src.core.exceptions import ProviderError
from src.core.logger import logger


# =============================================================================
# Provider 抽象基类
# =============================================================================

class BaseProvider(ABC):
    """Provider 抽象基类

    所有 LLM Provider 必须实现以下方法：
    - chat_completion(): 非流式对话
    - chat_completion_stream(): 流式对话
    - list_models(): 列出可用模型
    - health_check(): 健康检查
    """

    # 子类必须定义
    name: str = ""
    display_name: str = ""
    auth_type: str = "token"  # token | cookie | oauth | jwt

    def __init__(self, account: AccountConfig):
        self.account = account
        self._http_session = None

    # ---- 抽象方法 ----

    @abstractmethod
    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ProviderResponse:
        """非流式对话"""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式对话 — 返回 StreamChunk 生成器"""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """返回此 Provider 支持的模型列表"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查：Token 有效 / API 可达"""
        ...

    # ---- 可选方法 ----

    async def refresh_token(self) -> bool:
        """刷新 Token（Provider 可选实现）"""
        return False

    async def create_session(self) -> str:
        """创建对话会话（有状态 Provider 需要）"""
        return ""

    async def delete_session(self, session_id: str) -> bool:
        """删除对话会话"""
        return False

    async def generate_title(self, session_id: str, content: str) -> str:
        """生成对话标题（可选）"""
        return ""

    async def clear_conversations(self) -> dict:
        """清除所有对话历史（Provider 可选实现）

        Returns:
            dict: {
                "ok": bool,
                "deleted_count": int,
                "detail": str,
            }
        """
        return {"ok": False, "deleted_count": 0, "detail": "该 Provider 未实现 clear_conversations"}


# =============================================================================
# Provider 注册中心
# =============================================================================

class ProviderRegistry:
    """Provider 注册中心 — 管理所有 Provider 类型"""

    _providers: dict[str, type[BaseProvider]] = {}

    @classmethod
    def register(cls, name: str):
        """装饰器：注册 Provider 类

        用法:
            @ProviderRegistry.register("deepseek")
            class DeepSeekProvider(BaseProvider):
                ...
        """
        def wrapper(provider_cls: type[BaseProvider]):
            cls._providers[name] = provider_cls
            provider_cls.name = name
            logger.info(f"[Registry] Registered provider: {name}")
            return provider_cls
        return wrapper

    @classmethod
    def get(cls, name: str) -> type[BaseProvider] | None:
        """获取 Provider 类"""
        return cls._providers.get(name)

    @classmethod
    def create(cls, name: str, account: AccountConfig) -> BaseProvider:
        """工厂方法：根据名称 + 账号配置创建 Provider 实例"""
        provider_cls = cls._providers.get(name)
        if provider_cls is None:
            raise ProviderError(f"Unknown provider: {name}")
        return provider_cls(account)

    @classmethod
    def list_all(cls) -> list[str]:
        """列出所有已注册的 Provider 名称"""
        return list(cls._providers.keys())


# =============================================================================
# Provider Forwarder 注册中心
# =============================================================================

class ProviderForwarder:
    """Provider 转发器 — 集中调度 Provider 的请求转发逻辑

    参考 Chat2API 的 RequestForwarder 模式：
    - 每个 Provider 可注册一个 forwarder 函数
    - routes.py 通过 forwarder 统一调用，替代散落的 if-elif 分支
    - 默认使用 BaseProvider 自带的 chat_completion() 实现

    用法:
        @provider_forwarder.register("custom-provider")
        async def forward_custom(provider, request, actual_model):
            ...
    """

    def __init__(self):
        self._forwarders: dict[str, callable] = {}

    def register(self, name: str, forwarder_fn: callable) -> None:
        """注册 Provider 转发函数"""
        self._forwarders[name] = forwarder_fn

    def get(self, name: str) -> Optional[callable]:
        """获取 Provider 转发函数（不存在则返回默认 BaseProvider 实现）"""
        return self._forwarders.get(name)

    def has(self, name: str) -> bool:
        return name in self._forwarders

    def list_all(self) -> list[str]:
        return list(self._forwarders.keys())


# 全局 Forwarder 单例
provider_forwarder = ProviderForwarder()


# =============================================================================
# Provider 调度器
# =============================================================================

class ProviderDispatcher:
    """Provider 调度器

    根据请求的 model 找到对应的 Provider + 账号。
    参考 Chat2API 的 forwarder.ts ProviderForwarder 列表模式。
    """

    def __init__(self, model_mapper, load_balancer):
        self.model_mapper = model_mapper
        self.load_balancer = load_balancer

    async def dispatch(
        self, request: ChatCompletionRequest
    ) -> tuple[BaseProvider, str]:
        """根据请求找到 Provider 实例 + 实际模型名

        Returns:
            (provider_instance, actual_model_name)
        """
        # 1. 模型映射：request.model → (provider_type, actual_model)
        provider_type, actual_model = self.model_mapper.map(request.model)

        # 2. 从账号池获取可用账号
        account = await self.load_balancer.select_account(provider_type, request.model)

        if account is None:
            # Fallback 降级
            account = await self._try_fallback(provider_type, request.model)
            if account is None:
                from src.core.exceptions import NoAvailableProvider
                raise NoAvailableProvider(provider_type)

        # 3. 创建 Provider 实例
        provider = ProviderRegistry.create(provider_type, account)

        logger.info(
            f"[Dispatch] model={request.model} → provider={provider_type} "
            f"actual={actual_model} account={account.name}"
        )

        return provider, actual_model

    async def _try_fallback(
        self, provider_type: str, model: str
    ) -> Optional[AccountConfig]:
        """尝试 Fallback Provider"""
        from src.core.config import get_config

        fallback_chain = get_config().provider_fallback
        candidates = fallback_chain.get(provider_type, [])

        for fallback_type in candidates:
            account = await self.load_balancer.select_account(fallback_type, model)
            if account:
                logger.info(f"[Fallback] {provider_type} → {fallback_type}")
                return account

        return None
