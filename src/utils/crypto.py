# -*- coding: utf-8 -*-
"""WebAPI — 凭证加密模块

参考 Chat2API 的 safeStorage 设计：
- 使用 Fernet (AES-128-CBC + HMAC-SHA256) 对称加密
- 密钥存到 config/.encryption_key（首次启动自动生成）
- 对 AccountConfig.token / cookie 字段加密后写入 YAML

加密前缀：`enc:v1:` 标识已加密字段，方便回退。

使用：
    from src.utils.crypto import credential_crypto

    # 加密
    encrypted = credential_crypto.encrypt(plaintext_token)
    # 解密
    plaintext = credential_crypto.decrypt(encrypted)
    # 判断是否加密
    if credential_crypto.is_encrypted(value): ...
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from src.core.logger import logger


# 加密前缀标识
ENCRYPTION_PREFIX = "enc:v1:"


class CredentialCrypto:
    """凭证加密器

    使用 Fernet 对称加密，密钥自动管理。
    加密格式：enc:v1:<base64-fernet-token>
    """

    def __init__(self, key_path: Optional[Path] = None):
        # 默认 key 路径
        if key_path is None:
            key_path = self._find_key_path()
        self.key_path = key_path
        self._fernet: Optional[Fernet] = None
        self._init_fernet()

    @staticmethod
    def _find_key_path() -> Path:
        """查找密钥文件路径"""
        candidates = [
            Path("config/.encryption_key"),
            Path(os.environ.get("WEBAPI_ENCRYPTION_KEY_PATH", "")),
        ]
        for p in candidates:
            if p.is_file():
                return p
        # 默认路径（首次启动时会创建）
        return Path("config/.encryption_key")

    def _init_fernet(self) -> None:
        """初始化 Fernet（必要时生成新密钥）"""
        key: Optional[bytes] = None

        if self.key_path.is_file():
            try:
                key = self.key_path.read_bytes().strip()
                # 验证 key 格式
                Fernet(key)
                logger.debug(f"[Crypto] Loaded existing key from {self.key_path}")
            except (ValueError, Exception) as e:
                logger.warning(f"[Crypto] Invalid key file, regenerating: {e}")
                key = None

        if key is None:
            # 生成新密钥
            key = Fernet.generate_key()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(key)
            # Windows 下限制文件权限
            try:
                os.chmod(self.key_path, 0o600)
            except (OSError, AttributeError):
                pass
            logger.info(f"[Crypto] Generated new encryption key: {self.key_path}")

        self._fernet = Fernet(key)

    def is_encrypted(self, value: str) -> bool:
        """判断字符串是否已加密"""
        if not value:
            return False
        return value.startswith(ENCRYPTION_PREFIX)

    def encrypt(self, plaintext: str) -> str:
        """加密明文 → 密文字符串

        Args:
            plaintext: 原始凭证字符串

        Returns:
            带 enc:v1: 前缀的密文
        """
        if not plaintext:
            return plaintext

        # 已加密则直接返回
        if self.is_encrypted(plaintext):
            return plaintext

        # 加密
        if self._fernet is None:
            self._init_fernet()

        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return ENCRYPTION_PREFIX + token.decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """解密密文 → 明文

        Args:
            ciphertext: 带 enc:v1: 前缀的密文

        Returns:
            原始明文
        """
        if not ciphertext:
            return ciphertext

        # 未加密则直接返回（兼容明文配置）
        if not self.is_encrypted(ciphertext):
            return ciphertext

        if self._fernet is None:
            self._init_fernet()

        try:
            token = ciphertext[len(ENCRYPTION_PREFIX):]
            plaintext = self._fernet.decrypt(token.encode("ascii"))
            return plaintext.decode("utf-8")
        except (InvalidToken, ValueError) as e:
            logger.error(f"[Crypto] Decryption failed: {e}")
            raise ValueError(f"Decryption failed: {e}") from e

    def rotate_key(self) -> None:
        """轮换密钥（生成新密钥）

        注意：轮换后旧加密的凭证将无法解密，需重新登录。
        """
        if self.key_path.is_file():
            # 备份旧密钥
            backup = self.key_path.with_suffix(".key.old")
            self.key_path.rename(backup)
            logger.warning(f"[Crypto] Old key backed up to {backup}")
        self._fernet = None
        self._init_fernet()


# 全局单例
credential_crypto = CredentialCrypto()
