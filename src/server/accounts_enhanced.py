# -*- coding: utf-8 -*-
"""
增强版账号管理接口 - 参考Chat2API的management/accounts.ts

提供更完善的账号管理功能，包括：
- 统一的凭证验证
- 自动凭证刷新
- 账号状态管理
- 批量操作支持
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from src.core.config import get_config, save_config, reload_config, AccountConfig
from src.provider.base import ProviderRegistry
from src.pool import account_pool
from src.core.logger import logger
from src.login.credential_manager import credential_manager, CredentialValidationResult


router = APIRouter()


# =============================================================================
# 请求/响应模型
# =============================================================================

class CreateAccountRequest(BaseModel):
    """创建账号请求"""
    name: str = Field(..., min_length=1, description="账号名称")
    token: str = Field(default="", description="Bearer Token / JWT")
    cookie: str = Field(default="", description="Cookie 字符串")
    user_id: str = Field(default="", description="Real User ID")
    models: List[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=5, ge=1, le=20)


class UpdateAccountRequest(BaseModel):
    """更新账号请求（所有字段可选）"""
    name: Optional[str] = Field(default=None, min_length=1)
    token: Optional[str] = None
    cookie: Optional[str] = None
    user_id: Optional[str] = None
    models: Optional[List[str]] = None
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=20)
    enabled: Optional[bool] = None


class AccountStatusResponse(BaseModel):
    """账号状态响应"""
    name: str
    enabled: bool
    healthy: bool
    last_checked: float
    fail_count: int
    cooldown_until: float
    validation_result: Optional[CredentialValidationResult] = None


class BulkOperationRequest(BaseModel):
    """批量操作请求"""
    account_names: List[str]
    action: str = Field(..., description="启用/禁用/删除/验证")
    enabled: Optional[bool] = None


class RefreshCredentialsRequest(BaseModel):
    """刷新凭证请求"""
    account_names: List[str]


# =============================================================================
# 增强的账号管理接口
# =============================================================================

@router.get("/providers/{provider}/accounts/enhanced")
async def list_accounts_enhanced(provider: str):
    """获取指定 Provider 的所有账号（包含详细状态）"""
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    config = get_config()
    provider_config = config.providers.get(provider)
    
    if provider_config is None:
        return {"provider": provider, "accounts": [], "total": 0}

    accounts = []
    for acc in provider_config.accounts:
        # 获取账号池状态
        account_state = account_pool.get_account_state(provider, acc.name)
        
        # 获取验证结果
        validation_result = None
        if acc.enabled:
            try:
                validation_result = await credential_manager.validate_account_credentials(provider, acc)
            except Exception as e:
                logger.error(f"[Accounts] Validation failed for {provider}/{acc.name}: {e}")
        
        accounts.append({
            "name": acc.name,
            "enabled": acc.enabled,
            "has_token": bool(acc.token),
            "has_cookie": bool(acc.cookie),
            "has_user_id": bool(acc.user_id),
            "models": acc.models,
            "max_concurrent": acc.max_concurrent,
            "health_check_interval": acc.health_check_interval,
            # 脱敏显示凭证前几位
            "token_preview": (acc.token[:20] + "..." if acc.token and len(acc.token) > 20 else acc.token) if acc.token else "",
            "cookie_preview": (acc.cookie[:30] + "..." if acc.cookie and len(acc.cookie) > 30 else acc.cookie) if acc.cookie else "",
            "user_id_preview": acc.user_id or "",
            # 状态信息
            "healthy": account_state.healthy if account_state else False,
            "last_checked": account_state.last_checked if account_state else 0,
            "fail_count": account_state.fail_count if account_state else 0,
            "cooldown_until": account_state.cooldown_until if account_state else 0,
            "validation_result": validation_result
        })

    return {
        "provider": provider, 
        "accounts": accounts, 
        "total": len(accounts)
    }


@router.get("/providers/{provider}/accounts/{account_name}/status")
async def get_account_status(provider: str, account_name: str):
    """获取指定账号的详细状态"""
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    config = get_config()
    provider_config = config.providers.get(provider)
    
    if provider_config is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")

    # 查找账号
    account = None
    for acc in provider_config.accounts:
        if acc.name == account_name:
            account = acc
            break
    
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")

    # 获取账号池状态
    account_state = account_pool.get_account_state(provider, account_name)
    
    # 获取验证结果
    validation_result = None
    if account.enabled:
        try:
            validation_result = await credential_manager.validate_account_credentials(provider, account)
        except Exception as e:
            logger.error(f"[Accounts] Validation failed for {provider}/{account_name}: {e}")
    
    return {
        "provider": provider,
        "account": account_name,
        "enabled": account.enabled,
        "healthy": account_state.healthy if account_state else False,
        "last_checked": account_state.last_checked if account_state else 0,
        "fail_count": account_state.fail_count if account_state else 0,
        "cooldown_until": account_state.cooldown_until if account_state else 0,
        "validation_result": validation_result
    }


@router.post("/providers/{provider}/accounts/bulk")
async def bulk_account_operations(provider: str, body: BulkOperationRequest, background_tasks: BackgroundTasks):
    """批量账号操作"""
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    config = get_config()
    provider_config = config.providers.get(provider)
    
    if provider_config is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")

    # 验证账号是否存在
    existing_accounts = [acc.name for acc in provider_config.accounts]
    invalid_accounts = [name for name in body.account_names if name not in existing_accounts]
    
    if invalid_accounts:
        raise HTTPException(
            status_code=404, 
            detail=f"Accounts not found: {', '.join(invalid_accounts)}"
        )

    changes = []
    
    for account_name in body.account_names:
        if body.action == "enable":
            # 启用账号
            for acc in provider_config.accounts:
                if acc.name == account_name:
                    acc.enabled = True
                    account_pool.mark_healthy(provider, account_name)
                    changes.append(f"Enabled {account_name}")
                    break
        
        elif body.action == "disable":
            # 禁用账号
            for acc in provider_config.accounts:
                if acc.name == account_name:
                    acc.enabled = False
                    account_pool.mark_unhealthy(provider, account_name, "Disabled by user")
                    changes.append(f"Disabled {account_name}")
                    break
        
        elif body.action == "delete":
            # 删除账号
            original_count = len(provider_config.accounts)
            provider_config.accounts = [
                acc for acc in provider_config.accounts if acc.name != account_name
            ]
            
            if len(provider_config.accounts) < original_count:
                account_pool.mark_unhealthy(provider, account_name)
                changes.append(f"Deleted {account_name}")
            else:
                changes.append(f"Failed to delete {account_name} - not found")
        
        elif body.action == "validate":
            # 验证账号（异步）
            background_tasks.add_task(validate_account_credentials, provider, account_name)
            changes.append(f"Started validation for {account_name}")
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

    # 保存配置
    save_config(config)
    account_pool.register_provider(provider, provider_config)

    logger.info(f"[Accounts] Bulk operation on {provider}: {', '.join(changes)}")

    return {
        "status": "ok",
        "provider": provider,
        "action": body.action,
        "changes": changes,
        "message": f"Bulk operation completed for {len(body.account_names)} accounts"
    }


@router.post("/providers/{provider}/accounts/{account_name}/refresh")
async def refresh_account_credentials(provider: str, account_name: str):
    """刷新账号凭证"""
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    config = get_config()
    provider_config = config.providers.get(provider)
    
    if provider_config is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")

    # 查找账号
    account = None
    for acc in provider_config.accounts:
        if acc.name == account_name:
            account = acc
            break
    
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")

    try:
        # 尝试刷新凭证
        new_credentials = await credential_manager.refresh_account_credentials(provider, account)
        
        if new_credentials:
            # 更新账号配置
            for key, value in new_credentials.items():
                if hasattr(account, key):
                    setattr(account, key, value)
            
            save_config(config)
            account_pool.register_provider(provider, provider_config)
            
            logger.info(f"[Accounts] Credentials refreshed for {provider}/{account_name}")
            
            return {
                "status": "ok",
                "provider": provider,
                "account": account_name,
                "message": "Credentials refreshed successfully"
            }
        else:
            return {
                "status": "warning",
                "provider": provider,
                "account": account_name,
                "message": "No refresh available or failed"
            }
            
    except Exception as e:
        logger.error(f"[Accounts] Refresh failed for {provider}/{account_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/{provider}/accounts/summary")
async def get_accounts_summary(provider: str):
    """获取账号状态摘要"""
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    try:
        summary = await credential_manager.get_account_status_summary(provider)
        return summary
    except Exception as e:
        logger.error(f"[Accounts] Failed to get summary for {provider}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 辅助函数
# =============================================================================

async def validate_account_credentials(provider: str, account_name: str):
    """验证账号凭证（异步）"""
    try:
        config = get_config()
        provider_config = config.providers.get(provider)
        
        if not provider_config:
            return
        
        account = None
        for acc in provider_config.accounts:
            if acc.name == account_name:
                account = acc
                break
        
        if not account or not account.enabled:
            return
        
        # 验证凭证
        result = await credential_manager.validate_account_credentials(provider, account)
        
        if result.valid:
            account_pool.mark_healthy(provider, account_name)
            logger.info(f"[Accounts] Account {provider}/{account_name} validated successfully")
        else:
            account_pool.mark_unhealthy(provider, account_name, result.error)
            logger.warning(f"[Accounts] Account {provider}/{account_name} validation failed: {result.error}")
            
    except Exception as e:
        logger.error(f"[Accounts] Validation task failed for {provider}/{account_name}: {e}")
        account_pool.mark_unhealthy(provider, account_name, str(e))