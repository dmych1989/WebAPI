# -*- coding: utf-8 -*-
"""WebAPI — API Key 管理路由

参考 Chat2API 的 apiKeys.ts 设计：
- GET    /admin/api-keys              列出所有 Key（脱敏）
- POST   /admin/api-keys              创建新 Key（返回完整明文，仅一次）
- PUT    /admin/api-keys/{id}         更新 Name/Description/Enabled
- DELETE /admin/api-keys/{id}         删除 Key
- POST   /admin/api-keys/{id}/regenerate  重新生成 Key 值
- POST   /admin/api-keys/enabled      启用/禁用 API Key 认证
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.config import get_config, save_config, ApiKey
from src.core.logger import logger

router = APIRouter()


# =============================================================================
# 请求/响应模型
# =============================================================================

class CreateApiKeyRequest(BaseModel):
    """创建 API Key 请求"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class UpdateApiKeyRequest(BaseModel):
    """更新 API Key 请求"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    enabled: Optional[bool] = None


class ToggleAuthRequest(BaseModel):
    """启用/禁用认证请求"""
    enabled: bool


# =============================================================================
# 端点
# =============================================================================

@router.get("/api-keys")
async def list_api_keys():
    """列出所有 API Key（key 字段脱敏）

    Returns:
        {
            "auth_enabled": bool,
            "keys": [ApiKey (masked)],
        }
    """
    config = get_config()
    keys = [ak.mask() for ak in config.server.api_key_objects]
    return {
        "auth_enabled": config.server.api_key_enabled,
        "keys": [k.model_dump() for k in keys],
    }


@router.post("/api-keys")
async def create_api_key(req: CreateApiKeyRequest):
    """创建新 API Key

    注意：完整 key 值仅在本次响应中返回，请妥善保存！
    """
    config = get_config()
    new_key = ApiKey.generate(name=req.name, description=req.description)
    config.server.api_key_objects.append(new_key)
    save_config(config)
    logger.info(f"[APIKey] Created: {req.name} (id={new_key.id})")
    # 返回完整 Key（明文，仅一次）
    return {
        "status": "ok",
        "message": "API Key 创建成功！请妥善保存，完整值仅显示一次。",
        "key": new_key.model_dump(),
    }


@router.put("/api-keys/{key_id}")
async def update_api_key(key_id: str, req: UpdateApiKeyRequest):
    """更新 API Key 元数据（name/description/enabled）"""
    config = get_config()
    target = None
    for ak in config.server.api_key_objects:
        if ak.id == key_id:
            target = ak
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"API Key not found: {key_id}")

    if req.name is not None:
        target.name = req.name
    if req.description is not None:
        target.description = req.description
    if req.enabled is not None:
        target.enabled = req.enabled

    save_config(config)
    logger.info(f"[APIKey] Updated: {target.name} (id={key_id})")
    return {
        "status": "ok",
        "key": target.mask().model_dump(),
    }


@router.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: str):
    """删除 API Key"""
    config = get_config()
    original_len = len(config.server.api_key_objects)
    config.server.api_key_objects = [
        ak for ak in config.server.api_key_objects if ak.id != key_id
    ]
    if len(config.server.api_key_objects) == original_len:
        raise HTTPException(status_code=404, detail=f"API Key not found: {key_id}")

    save_config(config)
    logger.info(f"[APIKey] Deleted: id={key_id}")
    return {"status": "ok", "id": key_id, "deleted": True}


@router.post("/api-keys/{key_id}/regenerate")
async def regenerate_api_key(key_id: str):
    """重新生成 API Key 值

    完整新值仅在本次响应中返回。
    """
    import secrets
    config = get_config()
    target = None
    for ak in config.server.api_key_objects:
        if ak.id == key_id:
            target = ak
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"API Key not found: {key_id}")

    target.key = f"sk-webapi-{secrets.token_hex(16)}"
    target.usage_count = 0
    save_config(config)
    logger.info(f"[APIKey] Regenerated: {target.name} (id={key_id})")
    return {
        "status": "ok",
        "message": "API Key 已重新生成，请妥善保存新值。",
        "key": target.model_dump(),
    }


@router.post("/api-keys/auth/toggle")
async def toggle_api_key_auth(req: ToggleAuthRequest):
    """启用/禁用 API Key 认证

    启用时必须有至少 1 个 Key，否则 400。
    """
    config = get_config()
    if req.enabled and not config.server.api_key_objects and not config.server.api_keys:
        raise HTTPException(
            status_code=400,
            detail="请先至少创建一个 API Key，再启用认证",
        )

    config.server.api_key_enabled = req.enabled
    save_config(config)
    logger.info(f"[APIKey] Auth {'enabled' if req.enabled else 'disabled'}")
    return {
        "status": "ok",
        "api_key_enabled": config.server.api_key_enabled,
    }
