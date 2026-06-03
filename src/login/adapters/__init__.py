# -*- coding: utf-8 -*-
"""
OAuth Adapters — 各 Provider 凭证验证适配器

参考 Chat2API src/main/oauth/adapters/ 设计模式：
- 每个 Provider 有独立的验证适配器
- validateToken() 验证凭证有效性
- refreshToken() 刷新 Token（如支持）
"""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass


@dataclass
class TokenValidationResult:
    """Token 验证结果"""
    valid: bool
    token_type: Optional[str] = None
    expires_at: Optional[int] = None
    account_info: Optional[dict] = None
    error: Optional[str] = None


@dataclass
class CredentialInfo:
    """凭证信息"""
    type: str  # jwt | refresh | access | cookie
    value: str
    expires_at: Optional[int] = None
    refresh_token: Optional[str] = None
    extra: Optional[dict] = None


class BaseOAuthAdapter(ABC):
    """OAuth 适配器基类"""

    provider_type: str = ""

    def __init__(self, provider_id: str = "account-1"):
        self.provider_id = provider_id

    @abstractmethod
    async def validate_token(self, credentials: dict) -> TokenValidationResult:
        """验证凭证有效性"""
        raise NotImplementedError

    @abstractmethod
    async def refresh_token(self, credentials: dict) -> Optional[CredentialInfo]:
        """刷新 Token（如支持）"""
        raise NotImplementedError

    def parse_jwt(self, token: str) -> Optional[dict]:
        """解析 JWT payload（不验证签名）"""
        if not token or "." not in token:
            return None
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload_b64 = parts[1]
            # base64url decode (补齐 padding)
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_bytes.decode("utf-8", errors="replace"))
        except Exception:
            return None

    def is_guest_account(self, token: str) -> bool:
        """检查是否为 Guest 账号"""
        payload = self.parse_jwt(token)
        if payload:
            email = payload.get("email", "")
            return "@guest.com" in email
        return False


# ----------------------------------------------------------------------
# 适配器注册表
# ----------------------------------------------------------------------

from src.login.adapters.deepseek import DeepSeekAdapter
from src.login.adapters.glm import GLMAdapter
from src.login.adapters.kimi import KimiAdapter
from src.login.adapters.minimax import MiniMaxAdapter
from src.login.adapters.mimo import MiMoAdapter
from src.login.adapters.qwen import QwenAdapter
from src.login.adapters.doubao import DoubaoAdapter
from src.login.adapters.yuanbao import YuanbaoAdapter

ADAPTERS: dict[str, type[BaseOAuthAdapter] | None] = {
    "deepseek": DeepSeekAdapter,
    "glm": GLMAdapter,
    "kimi": KimiAdapter,
    "minimax": MiniMaxAdapter,
    "mimo": MiMoAdapter,
    "qwen": QwenAdapter,
    "doubao": DoubaoAdapter,
    "yuanbao": YuanbaoAdapter,
    "coze": None,  # Coze 使用 PAT，直接 API 验证
}


def get_adapter(provider: str) -> Optional[BaseOAuthAdapter]:
    """获取指定 Provider 的 OAuth 适配器"""
    cls = ADAPTERS.get(provider)
    if cls is None:
        return None
    return cls()
