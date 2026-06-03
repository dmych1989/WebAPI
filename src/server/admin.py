# -*- coding: utf-8 -*-
"""WebAPI — Admin API

管理接口：配置热更新、账号池状态、Provider 列表。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.core.config import reload_config, get_config
from src.provider.base import ProviderRegistry
from src.pool import account_pool
from src.core.logger import logger

router = APIRouter()


@router.get("/config")
async def get_current_config():
    """获取当前配置（脱敏）"""
    config = get_config()
    return {
        "server": config.server.model_dump(),
        "proxy": config.proxy.model_dump(),
        "load_balance": config.load_balance.model_dump(),
        "providers": {
            k: {
                "enabled": v.enabled,
                "accounts_count": len(v.accounts),
            }
            for k, v in config.providers.items()
        },
    }


@router.post("/config/reload")
async def reload_config_endpoint():
    """热更新配置"""
    try:
        config = reload_config()
        # 重新注册所有账号（不管 enabled 状态，让管理 UI 始终显示全部 Provider）
        for provider_type, provider_config in config.providers.items():
            if provider_config.accounts:
                account_pool.register_provider(provider_type, provider_config)
        logger.info("[Admin] Config reloaded successfully")
        return {"status": "ok", "providers": list(config.providers.keys())}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/pool")
async def get_pool_status():
    """获取账号池状态"""
    return account_pool.get_pool_status()


@router.post("/pool/{provider_type}/{account_name}/reset")
async def reset_account(provider_type: str, account_name: str):
    """手动重置账号状态（标记为健康）"""
    account_pool.mark_healthy(provider_type, account_name)
    return {"status": "ok", "provider": provider_type, "account": account_name}


@router.get("/providers")
async def list_registered_providers():
    """列出已注册的 Provider 类型"""
    return {
        "registered": ProviderRegistry.list_all(),
        "pool": account_pool.get_pool_status(),
    }


@router.get("/stats")
async def get_detailed_stats():
    """获取详细统计信息"""
    from src.core.stats import stats_tracker
    snapshot = stats_tracker.get_snapshot()
    snapshot["pool"] = account_pool.get_pool_status()
    return snapshot


@router.post("/stats/reset")
async def reset_stats():
    """重置统计"""
    from src.core.stats import stats_tracker
    stats_tracker.reset()
    return {"status": "ok"}


@router.post("/login/{provider}")
async def trigger_browser_login(provider: str):
    """触发浏览器自动登录提取 Token
    
    注意：此接口需要服务器运行在有桌面环境的机器上。
    登录成功后 Token 会自动写入 config.yaml。
    
    Args:
        provider: deepseek | kimi | qwen | minimax | doubao | yuanbao
    """
    import asyncio
    from src.login import TokenExtractor

    if provider not in ("deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}. "
                    f"Available: deepseek, kimi, qwen, minimax, doubao, yuanbao"
        )

    try:
        extractor = TokenExtractor(provider, headless=False)
        result = await asyncio.wait_for(extractor.run(), timeout=360)
        return {
            "status": "ok",
            "provider": provider,
            "extracted": {
                "type": result.get("type"),
                "config_key": result.get("config_key"),
                "value_length": len(str(result.get("value", ""))),
            },
            "message": f"{provider} Token 已提取并保存到 config.yaml，请重启服务生效",
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408,
            detail="登录超时（6分钟），请确认已在浏览器中完成登录"
        )
    except Exception as e:
        logger.error(f"[Admin] Login failed for {provider}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
