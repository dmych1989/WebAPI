# -*- coding: utf-8 -*-
"""WebAPI — 账号池管理

多账号轮询、健康检查、冷却恢复、故障转移。
参考 AIClient2API 的 ProviderPoolManager 和 Chat2API 的 LoadBalancer。
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

from src.core.logger import logger

from src.core.config import AccountConfig, ProviderConfig, get_config
from src.core.models import AccountState


class LoadBalanceStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    FILL_FIRST = "fill_first"
    FAILOVER = "failover"
    WEIGHTED = "weighted"


class AccountPool:
    """账号池

    管理多个 Provider 的多个账号，负责：
    - 账号注册与移除
    - 轮询选择
    - 健康状态管理
    - 冷却恢复
    """

    def __init__(self):
        # provider_type → list[AccountState]
        self._accounts: dict[str, list[AccountState]] = {}
        # 轮询指针: provider_type → 当前索引
        self._round_robin_index: dict[str, int] = {}

    def register_provider(self, provider_type: str, config: ProviderConfig):
        """注册一个 Provider 的所有账号

        始终注册所有账号（包括 enabled=False 的），以便管理 UI 完整显示全部 Provider。
        - enabled=True 账号：直接进入轮询池
        - enabled=False 账号：以"未启用"状态进入，UI 显示但不参与实际请求
        """
        states = []
        for account in config.accounts:
            state = AccountState(
                id=f"{provider_type}:{account.name}",
                provider=provider_type,
                name=account.name,
            )
            # 未启用的账号初始不健康（不参与轮询）
            if not account.enabled:
                state.healthy = False
                state.fail_count = 0
            states.append(state)
        self._accounts[provider_type] = states
        self._round_robin_index[provider_type] = 0
        enabled_count = sum(1 for a in config.accounts if a.enabled)
        logger.info(
            f"[Pool] Registered {provider_type}: {len(states)} accounts "
            f"({enabled_count} enabled)"
        )

    def get_account_config(self, provider_type: str, name: str) -> Optional[AccountConfig]:
        """获取账号的配置"""
        config = get_config().providers.get(provider_type)
        if config is None:
            return None
        for acc in config.accounts:
            if acc.name == name:
                return acc
        return None

    async def select_account(
        self,
        provider_type: str,
        model: str,
        strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN,
    ) -> Optional[AccountConfig]:
        """选择一个健康账号

        Args:
            provider_type: Provider 类型
            model: 请求的模型名
            strategy: 负载均衡策略

        Returns:
            AccountConfig 或 None
        """
        if strategy == LoadBalanceStrategy.FAILOVER:
            return await self._select_failover(provider_type, model)
        elif strategy == LoadBalanceStrategy.FILL_FIRST:
            return await self._select_fill_first(provider_type, model)
        else:
            return await self._select_round_robin(provider_type, model)

    async def _select_round_robin(
        self, provider_type: str, model: str
    ) -> Optional[AccountConfig]:
        """轮询选择"""
        states = self._get_healthy_accounts(provider_type, model)
        if not states:
            return None

        index = self._round_robin_index.get(provider_type, 0)
        total = len(states)
        # 最多尝试 total 次
        for _ in range(total):
            index = index % total
            state = states[index]
            self._round_robin_index[provider_type] = (index + 1) % total

            if self._can_accept(state):
                return self.get_account_config(provider_type, state.name)
            index += 1

        return None

    async def _select_fill_first(
        self, provider_type: str, model: str
    ) -> Optional[AccountConfig]:
        """填满优先 — 第一个有空位的账号"""
        states = self._get_healthy_accounts(provider_type, model)
        if not states:
            return None
        # 找第一个未达上限的账号
        for state in states:
            if self._can_accept(state):
                return self.get_account_config(provider_type, state.name)
        return None

    async def _select_failover(
        self, provider_type: str, model: str
    ) -> Optional[AccountConfig]:
        """故障转移 — 始终用第一个健康账号"""
        # failover 与 fill_first 逻辑相同
        return await self._select_fill_first(provider_type, model)

    def _get_healthy_accounts(
        self, provider_type: str, model: str
    ) -> list[AccountState]:
        """获取健康的账号列表（按 model 过滤 + 按健康状态过滤）

        模型匹配规则（按优先级）：
        1. 如果账号 models 列表为空 → 接受所有模型
        2. 如果账号 models 列表包含 "*" → 接受所有模型
        3. 如果 model 完全匹配列表中任一项 → 接受
        4. 如果 model 与列表中任一项**互为子串**（不区分大小写）→ 接受
           例：列表 ["deepseek-v4-flash"] 接受 "deepseek-chat" / "deepseek" / "DeepSeek-V4-Flash"
        5. 如果 model 与列表中任一项**前缀族相同**（即第一个 `-` 之前的部分相同）→ 接受
           例：列表 ["deepseek-v4-flash"] 接受 "deepseek-chat"（同属 deepseek 族）
           例：列表 ["Kimi-K2.6"] 接受 "kimi" / "Kimi-K2.6-Think"
           例：列表 ["glm-4-plus"] 接受 "glm-4-flash"
        6. 否则跳过
        """
        states = self._accounts.get(provider_type, [])
        now = time.time()
        model_lower = model.lower().strip() if model else ""
        # 模型族前缀（第一个 `-` 之前的部分），例如 "deepseek-chat" → "deepseek"
        model_family = model_lower.split("-")[0] if model_lower else ""

        available = []
        for state in states:
            # 冷却期检查
            if state.cooldown_until > now:
                continue
            # 健康检查
            if not state.healthy:
                continue
            # 模型匹配检查
            config = self.get_account_config(provider_type, state.name)
            if config and config.models:
                models_list = config.models
                # 1) 空列表 → 接受所有
                if not models_list:
                    available.append(state)
                    continue
                # 2) 通配符 "*" → 接受所有
                if "*" in models_list:
                    available.append(state)
                    continue
                # 3) 完全匹配
                if model in models_list:
                    available.append(state)
                    continue
                # 4) 子串匹配（不区分大小写）— 兼容 deepseek-chat vs deepseek-v4-flash
                if any(
                    m.lower() in model_lower or model_lower in m.lower()
                    for m in models_list if m
                ):
                    available.append(state)
                    continue
                # 5) 模型族前缀匹配 — 同属一个 Provider 内的不同变体（如 deepseek-chat vs deepseek-v4-flash）
                if model_family and any(
                    m.lower().split("-")[0] == model_family
                    for m in models_list if m
                ):
                    available.append(state)
                    continue
                # 6) 不匹配，跳过
                logger.debug(
                    f"[Pool] Skip {provider_type}:{state.name}: model '{model}' "
                    f"not in {models_list}"
                )
                continue
            available.append(state)

        return available

    def _can_accept(self, state: AccountState) -> bool:
        """判断账号是否可以接受新请求"""
        config = self.get_account_config(state.provider, state.name)
        if config is None:
            return False
        return state.concurrent_requests < config.max_concurrent

    # ---- 状态管理 ----

    def mark_healthy(self, provider_type: str, name: str):
        """标记账号健康"""
        for state in self._accounts.get(provider_type, []):
            if state.name == name:
                state.healthy = True
                state.fail_count = 0
                state.last_checked = time.time()
                logger.debug(f"[Pool] {provider_type}:{name} → healthy")

    def mark_unhealthy(self, provider_type: str, name: str, reason: str = ""):
        """标记账号不健康 + 设置冷却

        冷却策略：指数退避
        - fail_count=1: base_cooldown (默认 60s)
        - fail_count=2: base_cooldown * 2 (120s)
        - fail_count=3: base_cooldown * 4 (240s)
        - fail_count=5+: base_cooldown * 8 (480s, 封顶)
        这样当 Token 失效时不会持续打服务端 API。
        """
        base_cooldown = get_config().load_balance.rate_limit_cooldown
        for state in self._accounts.get(provider_type, []):
            if state.name == name:
                state.healthy = False
                state.fail_count += 1
                # 指数退避
                multiplier = min(2 ** (state.fail_count - 1), 8)
                cooldown = base_cooldown * multiplier
                state.cooldown_until = time.time() + cooldown
                state.last_checked = time.time()
                logger.warning(
                    f"[Pool] {provider_type}:{name} → unhealthy (fail={state.fail_count}, "
                    f"cooldown={cooldown}s, reason={reason})"
                )

    def increment_concurrent(self, provider_type: str, name: str):
        """增加并发计数"""
        for state in self._accounts.get(provider_type, []):
            if state.name == name:
                state.concurrent_requests += 1
                return

    def decrement_concurrent(self, provider_type: str, name: str):
        """减少并发计数"""
        for state in self._accounts.get(provider_type, []):
            if state.name == name:
                state.concurrent_requests = max(0, state.concurrent_requests - 1)
                return

    def get_pool_status(self) -> dict:
        """获取账号池状态（用于管理 API）

        包含所有已注册 Provider 的所有账号（不管 enabled 状态），
        以便管理 UI 能完整显示全部 6 个 Provider。
        """
        result = {}
        for provider_type, states in self._accounts.items():
            result[provider_type] = [
                {
                    "name": s.name,
                    "healthy": s.healthy,
                    "fail_count": s.fail_count,
                    "concurrent": s.concurrent_requests,
                    "cooldown_remaining": max(0, s.cooldown_until - time.time()),
                    "enabled": self._is_account_enabled(provider_type, s.name),
                }
                for s in states
            ]
        return result

    def _is_account_enabled(self, provider_type: str, name: str) -> bool:
        """查询账号是否在配置中启用"""
        config = get_config().providers.get(provider_type)
        if config is None:
            return False
        for acc in config.accounts:
            if acc.name == name:
                return acc.enabled
        return False

    def get_registered_providers(self) -> list[str]:
        """获取所有已注册的 Provider 类型（含 enabled=False）"""
        return list(self._accounts.keys())

    # ---- 健康检查 ----

    async def health_check_all(self, providers_map: dict[str, type]):
        """定时健康检查所有账号

        Args:
            providers_map: {provider_type: ProviderClass} 映射
        """
        for provider_type, states in self._accounts.items():
            for state in states:
                try:
                    config = self.get_account_config(provider_type, state.name)
                    if config is None:
                        continue
                    provider_cls = providers_map.get(provider_type)
                    if provider_cls is None:
                        continue
                    provider = provider_cls(config)
                    is_healthy = await provider.health_check()
                    if is_healthy:
                        self.mark_healthy(provider_type, state.name)
                    else:
                        self.mark_unhealthy(provider_type, state.name, "health check failed")
                except Exception as e:
                    self.mark_unhealthy(provider_type, state.name, str(e))

    async def start_health_check_loop(
        self, providers_map: dict[str, type], interval: int = 60
    ):
        """启动定时健康检查循环"""
        logger.info(f"[Pool] Health check loop started (interval={interval}s)")
        while True:
            await asyncio.sleep(interval)
            await self.health_check_all(providers_map)


# 全局单例
account_pool = AccountPool()
