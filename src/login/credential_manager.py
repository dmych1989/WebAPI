# -*- coding: utf-8 -*-
"""
凭证管理器 - 参考Chat2API的credential管理架构

提供统一的凭证验证、刷新、加密存储等功能。
支持多种认证方式和Provider特定的验证逻辑。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import aiohttp
from src.core.config import get_config, AccountConfig
from src.core.logger import logger
from src.provider.base import ProviderRegistry
from src.login.adapters import BaseOAuthAdapter, TokenValidationResult, CredentialInfo


@dataclass
class CredentialValidationResult:
    """凭证验证结果"""
    valid: bool
    error: str = ""
    latency_ms: int = 0
    account_info: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.account_info is None:
            self.account_info = {}


class BaseCredentialValidator(ABC):
    """凭证验证器基类"""
    
    def __init__(self, provider_type: str):
        self.provider_type = provider_type
    
    @abstractmethod
    async def validate_credentials(self, credentials: Dict[str, str]) -> CredentialValidationResult:
        """验证凭证"""
        pass
    
    @abstractmethod
    async def refresh_credentials(self, credentials: Dict[str, str]) -> Optional[Dict[str, str]]:
        """刷新凭证（如果支持）"""
        pass


class CredentialManager:
    """凭证管理器 - 统一管理所有Provider的凭证"""
    
    def __init__(self):
        self.validators: Dict[str, BaseCredentialValidator] = {}
        self.adapters: Dict[str, BaseOAuthAdapter] = {}
        self._init_validators()
    
    def _init_validators(self):
        """初始化所有Provider的验证器"""
        # 这里可以扩展更多验证器
        pass
    
    def get_validator(self, provider_type: str) -> Optional[BaseCredentialValidator]:
        """获取Provider的验证器"""
        return self.validators.get(provider_type)
    
    def get_adapter(self, provider_type: str) -> Optional[BaseOAuthAdapter]:
        """获取Provider的适配器"""
        if provider_type not in self.adapters:
            try:
                from src.login.adapters import create_adapter
                adapter = create_adapter(provider_type)
                self.adapters[provider_type] = adapter
                return adapter
            except Exception as e:
                logger.error(f"[CredentialManager] Failed to create adapter for {provider_type}: {e}")
                return None
        return self.adapters.get(provider_type)
    
    async def validate_account_credentials(self, provider_type: str, account_config: AccountConfig) -> CredentialValidationResult:
        """验证单个账号的凭证"""
        start_time = time.time()
        
        try:
            # 获取适配器
            adapter = self.get_adapter(provider_type)
            if not adapter:
                return CredentialValidationResult(
                    valid=False, 
                    error=f"No adapter available for provider: {provider_type}"
                )
            
            # 构建凭证字典
            credentials = {}
            if account_config.token:
                credentials["token"] = account_config.token
            if account_config.cookie:
                credentials["cookie"] = account_config.cookie
            if account_config.user_id:
                credentials["user_id"] = account_config.user_id
            
            if not credentials:
                return CredentialValidationResult(
                    valid=False, 
                    error="No credentials configured"
                )
            
            # 使用适配器验证凭证
            result = await adapter.validate_token(credentials)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            return CredentialValidationResult(
                valid=result.valid,
                error=result.error,
                latency_ms=latency_ms,
                account_info=result.account_info or {}
            )
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[CredentialManager] Validation failed for {provider_type}: {e}")
            return CredentialValidationResult(
                valid=False, 
                error=str(e),
                latency_ms=latency_ms
            )
    
    async def validate_all_provider_accounts(self, provider_type: str) -> Dict[str, CredentialValidationResult]:
        """验证指定Provider的所有账号"""
        config = get_config()
        provider_config = config.providers.get(provider_type)
        
        if not provider_config:
            return {}
        
        results = {}
        
        for account in provider_config.accounts:
            if not account.enabled:
                continue
                
            result = await self.validate_account_credentials(provider_type, account)
            results[account.name] = result
            
        return results
    
    async def refresh_account_credentials(self, provider_type: str, account_config: AccountConfig) -> Optional[Dict[str, str]]:
        """刷新账号凭证"""
        try:
            adapter = self.get_adapter(provider_type)
            if not adapter:
                return None
            
            # 构建当前凭证
            credentials = {}
            if account_config.token:
                credentials["token"] = account_config.token
            if account_config.cookie:
                credentials["cookie"] = account_config.cookie
            if account_config.user_id:
                credentials["user_id"] = account_config.user_id
            
            # 尝试刷新
            result = await adapter.refresh_token(credentials)
            
            if result and result.credentials:
                return result.credentials
            
            return None
            
        except Exception as e:
            logger.error(f"[CredentialManager] Refresh failed for {provider_type}: {e}")
            return None
    
    async def get_account_status_summary(self, provider_type: str) -> Dict[str, Any]:
        """获取账号状态摘要"""
        results = await self.validate_all_provider_accounts(provider_type)
        
        total = len(results)
        healthy = sum(1 for r in results.values() if r.valid)
        unhealthy = total - healthy
        
        return {
            "provider": provider_type,
            "total_accounts": total,
            "healthy_accounts": healthy,
            "unhealthy_accounts": unhealthy,
            "validation_results": results
        }


class GLMCredentialValidator(BaseCredentialValidator):
    """GLM凭证验证器"""
    
    def __init__(self):
        super().__init__("glm")
        self.api_base = "https://open.bigmodel.cn/api/paas/v4"
    
    async def validate_credentials(self, credentials: Dict[str, str]) -> CredentialValidationResult:
        """验证GLM凭证"""
        start_time = time.time()
        
        token = credentials.get("token") or credentials.get("refresh_token")
        if not token:
            return CredentialValidationResult(
                valid=False, 
                error="Token cannot be empty"
            )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_base}/models",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 401:
                        return CredentialValidationResult(
                            valid=False, 
                            error="Token is invalid or expired (401)",
                            latency_ms=int((time.time() - start_time) * 1000)
                        )
                    if resp.status == 403:
                        return CredentialValidationResult(
                            valid=False, 
                            error="Token is forbidden (403)",
                            latency_ms=int((time.time() - start_time) * 1000)
                        )
                    if resp.status != 200:
                        return CredentialValidationResult(
                            valid=False, 
                            error=f"Token validation failed (HTTP {resp.status})",
                            latency_ms=int((time.time() - start_time) * 1000)
                        )
                    
                    body = await resp.json()
                    data = body.get("data", {})
                    models = data.get("data", []) if isinstance(data, dict) else []
                    
                    return CredentialValidationResult(
                        valid=True,
                        latency_ms=int((time.time() - start_time) * 1000),
                        account_info={
                            "models_count": len(models),
                            "models": [m.get("id") for m in models] if models else []
                        }
                    )
                    
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return CredentialValidationResult(
                valid=False, 
                error=f"Validation request failed: {e}",
                latency_ms=latency_ms
            )
    
    async def refresh_credentials(self, credentials: Dict[str, str]) -> Optional[Dict[str, str]]:
        """GLM API Key 不支持刷新"""
        return None


class DeepSeekCredentialValidator(BaseCredentialValidator):
    """DeepSeek凭证验证器"""
    
    def __init__(self):
        super().__init__("deepseek")
        self.api_base = "https://chat.deepseek.com"
    
    async def validate_credentials(self, credentials: Dict[str, str]) -> CredentialValidationResult:
        """验证DeepSeek凭证"""
        start_time = time.time()
        
        token = credentials.get("token") or credentials.get("userToken")
        if not token:
            return CredentialValidationResult(
                valid=False, 
                error="Token cannot be empty"
            )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.api_base}/api/v0/users/current",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 401:
                        return CredentialValidationResult(
                            valid=False, 
                            error="Token is invalid or expired",
                            latency_ms=int((time.time() - start_time) * 1000)
                        )
                    
                    if resp.status == 200:
                        body = await resp.json()
                        return CredentialValidationResult(
                            valid=True,
                            latency_ms=int((time.time() - start_time) * 1000),
                            account_info={
                                "user_id": body.get("id"),
                                "username": body.get("username"),
                                "email": body.get("email")
                            }
                        )
                    else:
                        return CredentialValidationResult(
                            valid=False, 
                            error=f"Validation failed (HTTP {resp.status})",
                            latency_ms=int((time.time() - start_time) * 1000)
                        )
                        
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return CredentialValidationResult(
                valid=False, 
                error=f"Validation request failed: {e}",
                latency_ms=latency_ms
            )
    
    async def refresh_credentials(self, credentials: Dict[str, str]) -> Optional[Dict[str, str]]:
        """DeepSeek Token 不支持刷新"""
        return None


# 全局凭证管理器实例
credential_manager = CredentialManager()


# 注册验证器
def register_validator(provider_type: str, validator: BaseCredentialValidator):
    """注册Provider验证器"""
    credential_manager.validators[provider_type] = validator


# 初始化时注册所有验证器
register_validator("glm", GLMCredentialValidator())
register_validator("deepseek", DeepSeekCredentialValidator())