# -*- coding: utf-8 -*-
"""WebAPI — Provider Model Mapper

模型名称映射：OpenAI 风格模型名 → Provider Type + 实际模型名。
参考 Chat2API 的 modelMapper.ts。
"""

from __future__ import annotations

import fnmatch
from typing import Optional

from src.core.config import ModelMapping, get_config
from src.core.logger import logger
from src.core.exceptions import ProviderError


class ModelMapper:
    """模型映射器

    支持精确映射和通配符映射：
        "deepseek-v4-flash" → (deepseek, deepseek-v4-flash)
        "*deepseek*" → (deepseek, 原始模型名)
    """

    def __init__(self):
        self._mappings: dict[str, ModelMapping] = {}
        self._refresh()

    def _refresh(self):
        """从配置刷新映射表"""
        config = get_config()
        self._mappings = dict(config.model_mappings)

    def map(self, model: str) -> tuple[str, str]:
        """
        返回 (provider_type, actual_model)

        Args:
            model: 用户请求的模型名（如 "deepseek-v4-flash"）

        Returns:
            tuple: (provider_type, actual_model_name)
        """
        # 1. 精确匹配优先
        if model in self._mappings:
            mapping = self._mappings[model]
            return mapping.provider, mapping.actual_model or model

        # 2. 通配符匹配
        for pattern, mapping in self._mappings.items():
            if "*" in pattern and fnmatch.fnmatch(model, pattern):
                return mapping.provider, mapping.actual_model or model

        # 3. 从模型名推断 Provider
        provider_type = self._infer_provider(model)
        logger.info(f"[Mapper] Inferred: {model} → {provider_type}")
        return provider_type, model

    def _infer_provider(self, model: str) -> str:
        """从模型名推断 Provider 类型"""
        model_lower = model.lower()
        if "deepseek" in model_lower:
            return "deepseek"
        if "kimi" in model_lower:
            return "kimi"
        if "qwen" in model_lower:
            return "qwen"
        if "glm" in model_lower:
            return "glm"
        if "minimax" in model_lower:
            return "minimax"
        if "doubao" in model_lower or "skylark" in model_lower:
            return "doubao"
        if "yuanbao" in model_lower:
            return "yuanbao"
        if "coze" in model_lower:
            return "coze"
        # 默认使用模型名第一个横线前的部分
        return model_lower.split("-")[0]

    def add_mapping(
        self,
        request_model: str,
        provider: str,
        actual_model: Optional[str] = None,
    ):
        """动态添加映射"""
        self._mappings[request_model] = ModelMapping(
            provider=provider, actual_model=actual_model
        )
        logger.info(f"[Mapper] Added: {request_model} → {provider}/{actual_model}")

    def list_models(self) -> list[str]:
        """返回所有可用模型名"""
        return list(self._mappings.keys())

    def reload(self):
        """热重载配置"""
        self._refresh()


# 全局单例
model_mapper = ModelMapper()

# Provider 注册中心
from src.provider.base import ProviderRegistry


def get_provider(name: str, account=None):
    """获取 Provider 实例
    
    Args:
        name: Provider 名称
        account: 账号配置（可选）
        
    Returns:
        Provider 实例
    """
    from src.core.config import get_config
    config = get_config()
    
    if account is None:
        # 从配置中获取默认账号
        provider_config = config.providers.get(name)
        if provider_config and provider_config.enabled and provider_config.accounts:
            account = provider_config.accounts[0]
        else:
            raise ProviderError(f"No account configured for provider: {name}")
    
    return ProviderRegistry.create(name, account)


def list_providers():
    """列出所有可用的 Provider"""
    return ProviderRegistry.list_all()
