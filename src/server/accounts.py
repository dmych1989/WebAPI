# -*- coding: utf-8 -*-
"""
WebAPI — 账号管理接口

提供账号 CRUD、凭证验证、会话清理等功能。
参考 Chat2API 的 management/accounts.ts。
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.config import get_config, save_config, reload_config, AccountConfig
from src.provider.base import ProviderRegistry
from src.pool import account_pool
from src.core.logger import logger

router = APIRouter()


# =============================================================================
# 请求/响应模型
# =============================================================================

class CreateAccountRequest(BaseModel):
    """创建账号请求"""
    name: str = Field(..., validation_alias="account_name", description="账号名称")
    token: str = Field(default="", description="Bearer Token / JWT")
    cookie: str = Field(default="", description="Cookie 字符串")
    user_id: str = Field(default="", description="Real User ID")
    service_token: str = Field(default="", description="MiMo serviceToken")
    xiaomichatbot_ph: str = Field(default="", description="MiMo xiaomichatbot_ph")
    models: list[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=5, ge=1, le=20)


class UpdateAccountRequest(BaseModel):
    """更新账号请求（所有字段可选）"""
    name: Optional[str] = Field(default=None, validation_alias="account_name", min_length=1)
    token: Optional[str] = None
    cookie: Optional[str] = None
    user_id: Optional[str] = None
    service_token: Optional[str] = None
    xiaomichatbot_ph: Optional[str] = None
    models: Optional[list[str]] = None
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=20)
    enabled: Optional[bool] = None


class ValidateResult(BaseModel):
    """凭证验证结果"""
    provider: str
    account: str
    valid: bool
    latency_ms: int
    error: str = ""
    user_info: dict = Field(default_factory=dict)


# =============================================================================
# 账号 CRUD
# =============================================================================

@router.get("/providers/{provider}/accounts")
async def list_accounts(provider: str):
    """获取指定 Provider 的所有账号（脱敏）"""
    config = get_config()
    provider_config = config.providers.get(provider)

    if provider_config is None:
        return {"provider": provider, "accounts": [], "total": 0}

    accounts = []
    for acc in provider_config.accounts:
        accounts.append({
            "name": acc.name,
            "enabled": acc.enabled,
            "has_token": bool(acc.token),
            "has_cookie": bool(acc.cookie),
            "has_user_id": bool(acc.user_id),
            "has_service_token": bool(getattr(acc, "service_token", None)),
            "has_xiaomichatbot_ph": bool(getattr(acc, "xiaomichatbot_ph", None)),
            "models": acc.models,
            "max_concurrent": acc.max_concurrent,
            # 脱敏显示凭证前几位
            "token_preview": (acc.token[:20] + "..." if acc.token and len(acc.token) > 20 else acc.token) if acc.token else "",
            "cookie_preview": (acc.cookie[:30] + "..." if acc.cookie and len(acc.cookie) > 30 else acc.cookie) if acc.cookie else "",
            "user_id_preview": acc.user_id or "",
            "service_token_preview": (getattr(acc, "service_token", "")[:20] + "..." if getattr(acc, "service_token", None) and len(getattr(acc, "service_token", "")) > 20 else getattr(acc, "service_token", "")) if getattr(acc, "service_token", None) else "",
        })

    return {"provider": provider, "accounts": accounts, "total": len(accounts)}


@router.post("/providers/{provider}/accounts")
async def create_account(provider: str, body: CreateAccountRequest):
    """为指定 Provider 创建新账号

    自动加密 token/cookie 后写入 config.yaml。
    """
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    if not body.token and not body.cookie and not body.service_token:
        raise HTTPException(status_code=400, detail="至少需要提供 token、cookie 或 service_token")

    config = get_config()
    provider_config = config.providers.get(provider)
    if provider_config is None:
        from src.core.config import ProviderConfig as PC
        config.providers[provider] = PC()
        provider_config = config.providers[provider]

    # 检查同名账号
    for acc in provider_config.accounts:
        if acc.name == body.name:
            raise HTTPException(status_code=409, detail=f"账号 '{body.name}' 已存在")

    new_account = AccountConfig(
        name=body.name,
        token=body.token,
        cookie=body.cookie,
        user_id=body.user_id,
        models=body.models or [],
        max_concurrent=body.max_concurrent,
        health_check_interval=60,
        enabled=True,
    )
    # MiMo 专用字段
    if body.service_token:
        new_account.service_token = body.service_token
    if body.xiaomichatbot_ph:
        new_account.xiaomichatbot_ph = body.xiaomichatbot_ph
    provider_config.accounts.append(new_account)

    save_config(config)
    account_pool.register_provider(provider, provider_config)
    logger.info(f"[Accounts] Created account: {provider}/{body.name}")

    return {
        "status": "ok",
        "provider": provider,
        "account": body.name,
        "message": f"账号 '{body.name}' 已创建并保存到 config.yaml",
    }


@router.put("/providers/{provider}/accounts/{account_name}")
async def update_account(provider: str, account_name: str, body: UpdateAccountRequest):
    """更新账号配置"""
    config = get_config()
    provider_config = config.providers.get(provider)
    if provider_config is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' 未找到")

    target = None
    for acc in provider_config.accounts:
        if acc.name == account_name:
            target = acc
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"账号 '{account_name}' 未找到")

    changes = []
    if body.token is not None:
        target.token = body.token
        changes.append("token")
        # 凭证更新：自动重置账号状态，避免旧失败计数导致 503
        account_pool.mark_healthy(provider, account_name)
        for s in account_pool._accounts.get(provider, []):
            if s.name == account_name:
                s.cooldown_until = 0.0
                break
    if body.cookie is not None:
        target.cookie = body.cookie
        changes.append("cookie")
        # 凭证更新：自动重置账号状态，避免旧失败计数导致 503
        account_pool.mark_healthy(provider, account_name)
        for s in account_pool._accounts.get(provider, []):
            if s.name == account_name:
                s.cooldown_until = 0.0
                break
    if body.user_id is not None:
        target.user_id = body.user_id
        changes.append("user_id")
    if body.service_token is not None:
        target.service_token = body.service_token
        changes.append("service_token")
        account_pool.mark_healthy(provider, account_name)
        for s in account_pool._accounts.get(provider, []):
            if s.name == account_name:
                s.cooldown_until = 0.0
                break
    if body.xiaomichatbot_ph is not None:
        target.xiaomichatbot_ph = body.xiaomichatbot_ph
        changes.append("xiaomichatbot_ph")
    if body.models is not None:
        target.models = body.models
        changes.append("models")
    if body.max_concurrent is not None:
        target.max_concurrent = body.max_concurrent
        changes.append("max_concurrent")
    if body.enabled is not None:
        target.enabled = body.enabled
        changes.append(f"enabled={body.enabled}")
    if body.name is not None and body.name != account_name:
        target.name = body.name
        changes.append(f"name={body.name}")
        account_name = body.name

    save_config(config)
    account_pool.register_provider(provider, provider_config)
    logger.info(f"[Accounts] Updated account: {provider}/{account_name}: {changes}")

    return {
        "status": "ok",
        "provider": provider,
        "account": account_name,
        "changes": changes,
        "message": f"账号 '{account_name}' 已更新",
    }


@router.delete("/providers/{provider}/accounts/{account_name}")
async def delete_account(provider: str, account_name: str):
    """删除账号"""
    config = get_config()
    provider_config = config.providers.get(provider)
    if provider_config is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' 未找到")

    original_count = len(provider_config.accounts)
    provider_config.accounts = [
        acc for acc in provider_config.accounts if acc.name != account_name
    ]

    if len(provider_config.accounts) == original_count:
        raise HTTPException(status_code=404, detail=f"账号 '{account_name}' 未找到")

    save_config(config)
    account_pool.register_provider(provider, provider_config)
    logger.info(f"[Accounts] Deleted account: {provider}/{account_name}")

    return {
        "status": "ok",
        "provider": provider,
        "account": account_name,
        "message": f"账号 '{account_name}' 已删除",
    }


# =============================================================================
# 凭证验证
# =============================================================================

@router.post("/providers/{provider}/accounts/{account_name}/validate")
async def validate_account(provider: str, account_name: str):
    """验证指定账号的凭证是否有效

    使用 Provider 的 health_check() 方法检测凭证可用性。
    成功验证的账号会自动标记为健康。
    """
    if provider not in ProviderRegistry.list_all():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    config = get_config()
    provider_config = config.providers.get(provider)
    if provider_config is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' 未找到")

    account = None
    for acc in provider_config.accounts:
        if acc.name == account_name:
            account = acc
            break

    if account is None:
        raise HTTPException(status_code=404, detail=f"账号 '{account_name}' 未找到")

    if not account.token and not account.cookie:
        return ValidateResult(
            provider=provider,
            account=account_name,
            valid=False,
            latency_ms=0,
            error="未配置 token 或 cookie",
        )

    provider_cls = ProviderRegistry.get(provider)
    if provider_cls is None:
        return ValidateResult(
            provider=provider,
            account=account_name,
            valid=False,
            latency_ms=0,
            error=f"Provider '{provider}' 未注册",
        )

    try:
        instance = provider_cls(account)
        t0 = time.time()
        is_healthy = await asyncio.wait_for(
            instance.health_check(), timeout=15
        )
        latency = int((time.time() - t0) * 1000)

        if is_healthy:
            account_pool.mark_healthy(provider, account_name)
        else:
            account_pool.mark_unhealthy(provider, account_name, "health check returned False")

        return ValidateResult(
            provider=provider,
            account=account_name,
            valid=is_healthy,
            latency_ms=latency,
            error="" if is_healthy else "凭证无效或无法连接",
        )
    except asyncio.TimeoutError:
        account_pool.mark_unhealthy(provider, account_name, "timeout")
        return ValidateResult(
            provider=provider,
            account=account_name,
            valid=False,
            latency_ms=15000,
            error="连接超时（15秒）",
        )
    except Exception as e:
        account_pool.mark_unhealthy(provider, account_name, str(e)[:200])
        return ValidateResult(
            provider=provider,
            account=account_name,
            valid=False,
            latency_ms=0,
            error=str(e)[:200],
        )


@router.post("/providers/{provider}/validate-all")
async def validate_all_provider_accounts(provider: str):
    """验证指定 Provider 的所有账号"""
    config = get_config()
    provider_config = config.providers.get(provider)
    if provider_config is None:
        return {"provider": provider, "results": [], "total": 0}

    results = []
    for acc in provider_config.accounts:
        if not acc.enabled:
            continue
        try:
            resp = await validate_account(provider, acc.name)
            results.append(resp)
        except HTTPException:
            pass

    healthy = sum(1 for r in results if hasattr(r, 'valid') and r.valid)
    return {
        "provider": provider,
        "results": results,
        "total": len(results),
        "healthy": healthy,
        "unhealthy": len(results) - healthy,
    }


# =============================================================================
# 账号状态重置
# =============================================================================

# -----------------------------------------------------------------------------
# 模型清单（合并 config + provider.list_models）
# -----------------------------------------------------------------------------

@router.get("/providers/{provider}/accounts/{account_name}/models")
async def list_account_models(provider: str, account_name: str):
    """获取账号可用的所有模型

    返回三类模型:
    - configured: 当前 config 中账号已配置的模型
    - provider_default: provider.list_models() 返回的默认模型
    - available: configured ∪ provider_default（最终生效）
    """
    config = get_config()
    provider_cfg = config.providers.get(provider)
    if provider_cfg is None:
        raise HTTPException(status_code=404, detail=f"渠道 '{provider}' 未配置")

    target: Optional[AccountConfig] = None
    for acc in provider_cfg.accounts:
        if acc.name == account_name:
            target = acc
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"账号 '{account_name}' 未找到")

    # Provider 默认列表（fallback）
    provider_default: list[str] = []
    provider_cls = ProviderRegistry.get(provider)
    if provider_cls is not None:
        try:
            tmp_instance = ProviderRegistry.create(provider, target)
            provider_default = await tmp_instance.list_models()
        except Exception as e:
            logger.debug(f"[Accounts] list_models fallback failed for {provider}: {e}")

    configured = list(target.models)
    # 合并去重（按出现顺序）
    available: list[str] = []
    seen: set[str] = set()
    for m in configured + provider_default:
        if m and m not in seen:
            available.append(m)
            seen.add(m)

    return {
        "provider": provider,
        "account": account_name,
        "configured": configured,
        "provider_default": provider_default,
        "available": available,
    }


class UpdateAccountModelsRequest(BaseModel):
    """更新账号模型列表"""
    models: list[str] = Field(default_factory=list)


@router.put("/providers/{provider}/accounts/{account_name}/models")
async def update_account_models(
    provider: str, account_name: str, body: UpdateAccountModelsRequest
):
    """更新账号的 models 列表（覆盖式）。

    传入空数组则清空；非空则替换。保存后立即生效到 config（内存 + 磁盘）。
    """
    config = get_config()
    provider_cfg = config.providers.get(provider)
    if provider_cfg is None:
        raise HTTPException(status_code=404, detail=f"渠道 '{provider}' 未配置")

    target: Optional[AccountConfig] = None
    for acc in provider_cfg.accounts:
        if acc.name == account_name:
            target = acc
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"账号 '{account_name}' 未找到")

    # 去重并保序
    seen: set[str] = set()
    new_models: list[str] = []
    for m in body.models:
        m = (m or "").strip()
        if m and m not in seen:
            new_models.append(m)
            seen.add(m)

    target.models = new_models
    try:
        save_config(config)
    except Exception as e:
        logger.warning(f"[Accounts] save_config failed: {e}")
        # 即便落盘失败也保留内存生效

    logger.info(
        f"[Accounts] Updated models for {provider}:{account_name} → {len(new_models)} models"
    )
    return {
        "status": "ok",
        "provider": provider,
        "account": account_name,
        "models": new_models,
        "count": len(new_models),
    }


@router.post("/providers/{provider}/accounts/{account_name}/reset")
async def reset_account_state(provider: str, account_name: str):
    """强制重置账号状态为 healthy + 清空 cooldown

    用途：凭证已更新但账号还卡在 unhealthy / cooldown 状态时手动恢复。
    不做实际健康检查，下次请求会自动 health_check 验证。
    """
    found = False
    for s in account_pool._accounts.get(provider, []):
        if s.name == account_name:
            s.healthy = True
            s.fail_count = 0
            s.cooldown_until = 0.0
            s.last_checked = time.time()
            found = True
            logger.info(f"[Accounts] Reset state: {provider}:{account_name}")
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"账号 '{account_name}' 未找到")
    return {
        "status": "ok",
        "provider": provider,
        "account": account_name,
        "message": f"已重置 {provider}/{account_name} 的账号状态",
    }


# =============================================================================
# 会话清理
# =============================================================================

@router.post("/sessions/clear")
async def clear_all_sessions():
    """清除所有对话记录"""
    try:
        from src.context.manager import get_context_manager
        mgr = get_context_manager()
        count = mgr.clear_all()
        logger.info(f"[Sessions] Cleared {count} conversations")
        return {
            "status": "ok",
            "cleared": count,
            "message": f"已清除 {count} 个对话记录",
        }
    except Exception as e:
        logger.error(f"[Sessions] Clear failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/providers/{provider}/sessions")
async def clear_provider_sessions(provider: str):
    """清除指定 Provider 的所有会话"""
    try:
        from src.context.manager import get_context_manager
        mgr = get_context_manager()
        count = mgr.clear_provider(provider)
        return {
            "status": "ok",
            "provider": provider,
            "cleared": count,
            "message": f"已清除 {provider} 的 {count} 个会话",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
