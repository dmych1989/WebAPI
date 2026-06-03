# -*- coding: utf-8 -*-
"""WebAPI — 核心配置管理模块

支持从 YAML 文件和环境变量加载配置，Pydantic 验证。
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# =============================================================================
# 子配置模型
# =============================================================================

class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "127.0.0.1"
    port: int = 8080
    api_key_enabled: bool = False
    # 旧版：纯字符串列表（向后兼容）
    api_keys: list[str] = Field(default_factory=list)
    # 新版：API Key 对象列表（参考 Chat2API 的 ApiKey 模型）
    api_key_objects: list["ApiKey"] = Field(default_factory=list)


class ApiKey(BaseModel):
    """API Key 对象

    参考 Chat2API 的 ApiKey 模型：
    - id: 唯一标识
    - name: 用户友好名
    - key: 实际密钥值
    - enabled: 是否启用
    - created_at: 创建时间戳（毫秒）
    - description: 可选说明
    - usage_count: 使用次数（可选统计）
    """
    id: str
    name: str
    key: str
    enabled: bool = True
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    description: str = ""
    usage_count: int = 0

    @staticmethod
    def generate(name: str, description: str = "") -> "ApiKey":
        """生成新的 API Key

        Returns:
            ApiKey: 带随机密钥值的对象
        """
        # 格式: sk-webapi-{32 字符十六进制}
        random_part = secrets.token_hex(16)
        return ApiKey(
            id=secrets.token_hex(8),
            name=name,
            key=f"sk-webapi-{random_part}",
            enabled=True,
            description=description,
        )

    def mask(self) -> "ApiKey":
        """返回脱敏副本（用于 UI 显示）

        保留前缀和后 8 字符，中间用 ... 替代
        """
        if len(self.key) <= 12:
            masked_value = self.key[:4] + "..."
        else:
            masked_value = self.key[:10] + "..." + self.key[-8:]
        return ApiKey(
            id=self.id,
            name=self.name,
            key=masked_value,
            enabled=self.enabled,
            created_at=self.created_at,
            description=self.description,
            usage_count=self.usage_count,
        )


# 解决 Pydantic v2 前向引用
ApiKey.model_rebuild()
ServerConfig.model_rebuild()


class ProxyConfig(BaseModel):
    """代理/请求配置"""
    timeout: int = 120
    retry_count: int = 3
    retry_delay: int = 5


class LoadBalanceConfig(BaseModel):
    """负载均衡配置"""
    default_strategy: str = "round_robin"
    rate_limit_cooldown: int = 60


class AccountConfig(BaseModel):
    """单个账号配置"""
    model_config = {"extra": "allow"}  # 允许额外字段（如 user_id, metadata 等）

    name: str
    token: str = ""
    cookie: str = ""
    user_id: str = ""  # 某些 Provider (如 MiniMax) 需要的 Real User ID
    models: list[str] = Field(default_factory=list)
    max_concurrent: int = 5
    health_check_interval: int = 60
    enabled: bool = True


class ProviderConfig(BaseModel):
    """单个 Provider 配置"""
    enabled: bool = True
    accounts: list[AccountConfig] = Field(default_factory=list)


class ModelMapping(BaseModel):
    """模型映射配置"""
    provider: str
    actual_model: Optional[str] = None


class ContextManagementConfig(BaseModel):
    """上下文管理配置"""
    enabled: bool = False
    max_messages: int = 50
    max_tokens: int = 128000
    strategy: str = "sliding_window"


class ToolCallingConfig(BaseModel):
    """工具调用配置"""
    enabled: bool = True
    mode: str = "prompt_engineering"


class LoggingConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    file: str = "logs/webapi.log"
    max_size: str = "10MB"
    retention: str = "7 days"


# =============================================================================
# 主配置模型
# =============================================================================

class AppConfig(BaseModel):
    """应用配置主模型"""
    server: ServerConfig = Field(default_factory=ServerConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    load_balance: LoadBalanceConfig = Field(default_factory=LoadBalanceConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    model_mappings: dict[str, ModelMapping] = Field(default_factory=dict)
    provider_fallback: dict[str, list[str]] = Field(default_factory=dict)
    context_management: ContextManagementConfig = Field(default_factory=ContextManagementConfig)
    tool_calling: ToolCallingConfig = Field(default_factory=ToolCallingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# =============================================================================
# 配置管理器
# =============================================================================

_config: Optional[AppConfig] = None


def _find_config_path() -> Path:
    """查找配置文件路径"""
    candidates = [
        Path("config/config.yaml"),
        Path("../config/config.yaml"),
        Path(os.environ.get("WEBAPI_CONFIG", "")),
    ]
    for p in candidates:
        if p.is_file():
            return p
    # 回退到默认路径
    return Path("config/config.yaml")


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """加载配置

    优先级：传入路径 > 环境变量 WEBAPI_CONFIG > config/config.yaml

    加载时自动解密 AccountConfig.token / cookie 字段（如果带 enc:v1: 前缀），
    加密密钥从 config/.encryption_key 自动加载。
    """
    global _config

    path = config_path or _find_config_path()

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        cfg = AppConfig(**raw)
        _decrypt_provider_credentials(cfg)
    else:
        cfg = AppConfig()

    # 环境变量覆盖（可选）
    if port := os.environ.get("WEBAPI_PORT"):
        cfg.server.port = int(port)
    if host := os.environ.get("WEBAPI_HOST"):
        cfg.server.host = host

    _config = cfg
    return cfg


def _decrypt_provider_credentials(cfg: AppConfig) -> None:
    """解密所有 Provider 账号的 token/cookie 字段

    - 加载配置后调用，从密文还原为明文供运行时使用
    - 明文字段保持原样
    - 失败时仅记录警告，不中断加载
    """
    from src.utils.crypto import credential_crypto

    for provider_type, pcfg in cfg.providers.items():
        for account in pcfg.accounts:
            if account.token and credential_crypto.is_encrypted(account.token):
                try:
                    account.token = credential_crypto.decrypt(account.token)
                except ValueError as e:
                    from src.core.logger import logger
                    logger.warning(
                        f"[Config] Failed to decrypt token for "
                        f"{provider_type}:{account.name}: {e}"
                    )
            if account.cookie and credential_crypto.is_encrypted(account.cookie):
                try:
                    account.cookie = credential_crypto.decrypt(account.cookie)
                except ValueError as e:
                    from src.core.logger import logger
                    logger.warning(
                        f"[Config] Failed to decrypt cookie for "
                        f"{provider_type}:{account.name}: {e}"
                    )


def get_config() -> AppConfig:
    """获取当前配置（单例）"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config(config_path: Optional[Path] = None) -> AppConfig:
    """重新加载配置（热更新）"""
    global _config
    _config = load_config(config_path)
    return _config


def save_config(cfg: AppConfig, config_path: Optional[Path] = None, encrypt_credentials: bool = True) -> Path:
    """保存配置到 YAML 文件

    Args:
        cfg: 应用配置
        config_path: 输出路径，默认与加载路径相同
        encrypt_credentials: 是否对 token/cookie 字段加密（默认 True）

    Returns:
        实际写入的文件路径
    """
    path = config_path or _find_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = cfg.model_dump()

    if encrypt_credentials:
        from src.utils.crypto import credential_crypto
        for provider_type, pcfg in data.get("providers", {}).items():
            for account in pcfg.get("accounts", []):
                if account.get("token") and not credential_crypto.is_encrypted(account["token"]):
                    account["token"] = credential_crypto.encrypt(account["token"])
                if account.get("cookie") and not credential_crypto.is_encrypted(account["cookie"]):
                    account["cookie"] = credential_crypto.encrypt(account["cookie"])
                if account.get("service_token") and not credential_crypto.is_encrypted(account["service_token"]):
                    account["service_token"] = credential_crypto.encrypt(account["service_token"])
                if account.get("xiaomichatbot_ph") and not credential_crypto.is_encrypted(account["xiaomichatbot_ph"]):
                    account["xiaomichatbot_ph"] = credential_crypto.encrypt(account["xiaomichatbot_ph"])

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return path
