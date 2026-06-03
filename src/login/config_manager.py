# -*- coding: utf-8 -*-
"""
配置管理器 - 参考Chat2API的配置管理架构

提供统一的配置管理功能，包括：
- Provider配置管理
- 账号配置管理
- 凭证加密存储
- 配置验证
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from cryptography.fernet import Fernet
from src.core.config import AccountConfig, ProviderConfig, get_config, save_config
from src.core.logger import logger


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path("config/config.yaml")
        self.fernet_key = None
        self._init_encryption()
    
    def _init_encryption(self):
        """初始化加密"""
        try:
            # 尝试从配置中获取加密密钥
            config = get_config()
            if hasattr(config, 'encryption_key') and config.encryption_key:
                self.fernet_key = config.encryption_key.encode()
            else:
                # 生成新的加密密钥
                self.fernet_key = Fernet.generate_key()
                config.encryption_key = self.fernet_key.decode()
                save_config(config)
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to init encryption: {e}")
            self.fernet_key = None
    
    def encrypt_string(self, text: str) -> str:
        """加密字符串"""
        if not self.fernet_key:
            return text
        
        fernet = Fernet(self.fernet_key)
        return fernet.encrypt(text.encode()).decode()
    
    def decrypt_string(self, encrypted_text: str) -> str:
        """解密字符串"""
        if not self.fernet_key:
            return encrypted_text
        
        try:
            fernet = Fernet(self.fernet_key)
            return fernet.decrypt(encrypted_text.encode()).decode()
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to decrypt: {e}")
            return encrypted_text
    
    def encrypt_credentials(self, credentials: Dict[str, str]) -> Dict[str, str]:
        """加密凭证"""
        encrypted = {}
        for key, value in credentials.items():
            if value:
                encrypted[key] = self.encrypt_string(value)
            else:
                encrypted[key] = value
        return encrypted
    
    def decrypt_credentials(self, encrypted_credentials: Dict[str, str]) -> Dict[str, str]:
        """解密凭证"""
        decrypted = {}
        for key, value in encrypted_credentials.items():
            if value:
                decrypted[key] = self.decrypt_string(value)
            else:
                decrypted[key] = value
        return decrypted
    
    def add_account(self, provider_type: str, account_config: AccountConfig) -> bool:
        """添加账号"""
        try:
            config = get_config()
            
            if provider_type not in config.providers:
                from src.core.config import ProviderConfig
                config.providers[provider_type] = ProviderConfig()
            
            # 检查是否已存在同名账号
            for acc in config.providers[provider_type].accounts:
                if acc.name == account_config.name:
                    logger.warning(f"[ConfigManager] Account {account_config.name} already exists")
                    return False
            
            # 加密凭证
            encrypted_credentials = self.encrypt_credentials({
                "token": account_config.token,
                "cookie": account_config.cookie,
                "user_id": account_config.user_id
            })
            
            # 创建新的账号配置
            new_account = AccountConfig(
                name=account_config.name,
                token=encrypted_credentials.get("token", ""),
                cookie=encrypted_credentials.get("cookie", ""),
                user_id=encrypted_credentials.get("user_id", ""),
                models=account_config.models,
                max_concurrent=account_config.max_concurrent,
                health_check_interval=account_config.health_check_interval,
                enabled=account_config.enabled
            )
            
            config.providers[provider_type].accounts.append(new_account)
            save_config(config)
            
            logger.info(f"[ConfigManager] Added account {provider_type}/{account_config.name}")
            return True
            
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to add account: {e}")
            return False
    
    def update_account(self, provider_type: str, account_name: str, updates: Dict[str, Any]) -> bool:
        """更新账号"""
        try:
            config = get_config()
            provider_config = config.providers.get(provider_type)
            
            if not provider_config:
                logger.error(f"[ConfigManager] Provider {provider_type} not found")
                return False
            
            # 查找账号
            account_found = False
            for acc in provider_config.accounts:
                if acc.name == account_name:
                    account_found = True
                    
                    # 更新字段
                    if "name" in updates:
                        acc.name = updates["name"]
                    if "models" in updates:
                        acc.models = updates["models"]
                    if "max_concurrent" in updates:
                        acc.max_concurrent = updates["max_concurrent"]
                    if "health_check_interval" in updates:
                        acc.health_check_interval = updates["health_check_interval"]
                    if "enabled" in updates:
                        acc.enabled = updates["enabled"]
                    
                    # 更新凭证（加密存储）
                    if "token" in updates or "cookie" in updates or "user_id" in updates:
                        current_credentials = {
                            "token": acc.token,
                            "cookie": acc.cookie,
                            "user_id": acc.user_id
                        }
                        
                        # 更新凭证
                        if "token" in updates:
                            current_credentials["token"] = updates["token"]
                        if "cookie" in updates:
                            current_credentials["cookie"] = updates["cookie"]
                        if "user_id" in updates:
                            current_credentials["user_id"] = updates["user_id"]
                        
                        # 加密并保存
                        encrypted_credentials = self.encrypt_credentials(current_credentials)
                        acc.token = encrypted_credentials.get("token", "")
                        acc.cookie = encrypted_credentials.get("cookie", "")
                        acc.user_id = encrypted_credentials.get("user_id", "")
                    
                    break
            
            if not account_found:
                logger.error(f"[ConfigManager] Account {account_name} not found")
                return False
            
            save_config(config)
            logger.info(f"[ConfigManager] Updated account {provider_type}/{account_name}")
            return True
            
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to update account: {e}")
            return False
    
    def delete_account(self, provider_type: str, account_name: str) -> bool:
        """删除账号"""
        try:
            config = get_config()
            provider_config = config.providers.get(provider_type)
            
            if not provider_config:
                logger.error(f"[ConfigManager] Provider {provider_type} not found")
                return False
            
            original_count = len(provider_config.accounts)
            provider_config.accounts = [
                acc for acc in provider_config.accounts if acc.name != account_name
            ]
            
            if len(provider_config.accounts) < original_count:
                save_config(config)
                logger.info(f"[ConfigManager] Deleted account {provider_type}/{account_name}")
                return True
            else:
                logger.error(f"[ConfigManager] Account {account_name} not found")
                return False
                
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to delete account: {e}")
            return False
    
    def get_account(self, provider_type: str, account_name: str) -> Optional[AccountConfig]:
        """获取账号"""
        try:
            config = get_config()
            provider_config = config.providers.get(provider_type)
            
            if not provider_config:
                return None
            
            for acc in provider_config.accounts:
                if acc.name == account_name:
                    # 解密凭证
                    decrypted_credentials = self.decrypt_credentials({
                        "token": acc.token,
                        "cookie": acc.cookie,
                        "user_id": acc.user_id
                    })
                    
                    # 创建新的账号配置（包含解密后的凭证）
                    return AccountConfig(
                        name=acc.name,
                        token=decrypted_credentials.get("token", ""),
                        cookie=decrypted_credentials.get("cookie", ""),
                        user_id=decrypted_credentials.get("user_id", ""),
                        models=acc.models,
                        max_concurrent=acc.max_concurrent,
                        health_check_interval=acc.health_check_interval,
                        enabled=acc.enabled
                    )
            
            return None
            
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to get account: {e}")
            return None
    
    def list_accounts(self, provider_type: str, include_credentials: bool = False) -> List[AccountConfig]:
        """列出账号"""
        try:
            config = get_config()
            provider_config = config.providers.get(provider_type)
            
            if not provider_config:
                return []
            
            accounts = []
            for acc in provider_config.accounts:
                if include_credentials:
                    # 解密凭证
                    decrypted_credentials = self.decrypt_credentials({
                        "token": acc.token,
                        "cookie": acc.cookie,
                        "user_id": acc.user_id
                    })
                    
                    account = AccountConfig(
                        name=acc.name,
                        token=decrypted_credentials.get("token", ""),
                        cookie=decrypted_credentials.get("cookie", ""),
                        user_id=decrypted_credentials.get("user_id", ""),
                        models=acc.models,
                        max_concurrent=acc.max_concurrent,
                        health_check_interval=acc.health_check_interval,
                        enabled=acc.enabled
                    )
                else:
                    account = AccountConfig(
                        name=acc.name,
                        token="",  # 不包含凭证
                        cookie="",
                        user_id="",
                        models=acc.models,
                        max_concurrent=acc.max_concurrent,
                        health_check_interval=acc.health_check_interval,
                        enabled=acc.enabled
                    )
                
                accounts.append(account)
            
            return accounts
            
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to list accounts: {e}")
            return []
    
    def validate_config(self) -> Dict[str, Any]:
        """验证配置"""
        try:
            config = get_config()
            errors = []
            warnings = []
            
            # 检查Provider配置
            for provider_type, provider_config in config.providers.items():
                if not provider_config.accounts:
                    warnings.append(f"Provider {provider_type} has no accounts")
                
                # 检查账号配置
                for acc in provider_config.accounts:
                    if not acc.name:
                        errors.append(f"Account in {provider_type} has no name")
                    
                    if not acc.models:
                        warnings.append(f"Account {acc.name} in {provider_type} has no models")
                    
                    if not acc.token and not acc.cookie:
                        warnings.append(f"Account {acc.name} in {provider_type} has no credentials")
            
            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to validate config: {e}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": [],
                "timestamp": time.time()
            }
    
    def export_config(self, include_credentials: bool = False) -> Dict[str, Any]:
        """导出配置"""
        try:
            config = get_config()
            
            # 转换为可序列化的格式
            export_data = {
                "server": config.server.model_dump() if hasattr(config, 'server') else {},
                "proxy": config.proxy.model_dump() if hasattr(config, 'proxy') else {},
                "load_balance": config.load_balance.model_dump() if hasattr(config, 'load_balance') else {},
                "providers": {},
                "model_mappings": config.model_mappings,
                "provider_fallback": config.provider_fallback,
                "context_management": config.context_management.model_dump() if hasattr(config, 'context_management') else {},
                "tool_calling": config.tool_calling.model_dump() if hasattr(config, 'tool_calling') else {},
                "logging": config.logging.model_dump() if hasattr(config, 'logging') else {}
            }
            
            # 导出Provider配置
            for provider_type, provider_config in config.providers.items():
                accounts_data = []
                for acc in provider_config.accounts:
                    if include_credentials:
                        # 包含凭证
                        account_data = {
                            "name": acc.name,
                            "token": acc.token,
                            "cookie": acc.cookie,
                            "user_id": acc.user_id,
                            "models": acc.models,
                            "max_concurrent": acc.max_concurrent,
                            "health_check_interval": acc.health_check_interval,
                            "enabled": acc.enabled
                        }
                    else:
                        # 不包含凭证
                        account_data = {
                            "name": acc.name,
                            "models": acc.models,
                            "max_concurrent": acc.max_concurrent,
                            "health_check_interval": acc.health_check_interval,
                            "enabled": acc.enabled
                        }
                    
                    accounts_data.append(account_data)
                
                export_data["providers"][provider_type] = {
                    "enabled": provider_config.enabled,
                    "accounts": accounts_data
                }
            
            return export_data
            
        except Exception as e:
            logger.error(f"[ConfigManager] Failed to export config: {e}")
            return {"error": str(e)}


# 全局配置管理器实例
config_manager = ConfigManager()