# -*- coding: utf-8 -*-
"""
适配器工厂 - 参考Chat2API的适配器架构

统一管理所有Provider的适配器创建和配置。
"""

from __future__ import annotations

from typing import Dict, Type, Optional
from src.login.adapters.base import BaseOAuthAdapter, TokenValidationResult, CredentialInfo


class AdapterFactory:
    """适配器工厂类"""
    
    _adapters: Dict[str, Type[BaseOAuthAdapter]] = {}
    
    @classmethod
    def register_adapter(cls, provider_type: str, adapter_class: Type[BaseOAuthAdapter]):
        """注册适配器"""
        cls._adapters[provider_type] = adapter_class
    
    @classmethod
    def create_adapter(cls, provider_type: str, **kwargs) -> BaseOAuthAdapter:
        """创建适配器实例"""
        if provider_type not in cls._adapters:
            raise ValueError(f"No adapter registered for provider: {provider_type}")
        
        adapter_class = cls._adapters[provider_type]
        return adapter_class(**kwargs)
    
    @classmethod
    def get_registered_providers(cls) -> list[str]:
        """获取已注册的Provider列表"""
        return list(cls._adapters.keys())
    
    @classmethod
    def has_adapter(cls, provider_type: str) -> bool:
        """检查是否有适配器"""
        return provider_type in cls._adapters


def create_adapter(provider_type: str, **kwargs) -> BaseOAuthAdapter:
    """创建适配器的便捷函数"""
    return AdapterFactory.create_adapter(provider_type, **kwargs)