# -*- coding: utf-8 -*-
"""WebAPI — 自定义异常"""


class WebAPIError(Exception):
    """WebAPI 基础异常"""
    pass


class ProviderError(WebAPIError):
    """Provider 相关错误"""
    def __init__(self, message: str, provider: str = "", status_code: int = 500):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class AuthError(ProviderError):
    """认证错误"""
    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, status_code=401, **kwargs)


class RateLimitError(ProviderError):
    """限流错误"""
    def __init__(self, message: str = "Rate limit exceeded", **kwargs):
        super().__init__(message, status_code=429, **kwargs)


class NoAvailableProvider(ProviderError):
    """无可用 Provider

    当账号池中所有账号都不可用时（Token 失效 / 冷却中 / 被禁用）抛出。
    提供针对性的重置/重新登录建议。
    """
    def __init__(self, provider_type: str = ""):
        # 针对性提示：哪些 Provider 常见 Token 失效
        reset_hints = {
            "kimi": "（Token 可能已过期，请到管理 UI 点击 🔑 重新登录 Kimi）",
            "deepseek": "（Cookie/Token 可能已过期，请到管理 UI 点击 🔑 重新登录 DeepSeek）",
            "qwen": "（Token 可能已过期，请到管理 UI 点击 🔑 重新登录通义千问）",
            "doubao": "（Cookie 可能已过期，请到管理 UI 点击 🔑 重新登录豆包）",
            "yuanbao": "（Cookie 可能已过期，请到管理 UI 点击 🔑 重新登录元宝）",
            "minimax": "（Token 可能已过期，请到管理 UI 点击 🔑 重新登录 MiniMax）",
            "glm": "（凭证可能已过期，请到管理 UI 点击 🔑 重新登录智谱）",
        }
        hint = reset_hints.get(provider_type, "（所有账号可能都在冷却中或被禁用）")
        msg = f"No available provider for type: {provider_type}。{hint}"
        super().__init__(msg, status_code=503, provider=provider_type)


class TokenExpiredError(AuthError):
    """Token 过期错误"""
    pass


class StreamError(WebAPIError):
    """流式处理错误"""
    pass


class NetworkError(WebAPIError):
    """网络传输错误"""
    def __init__(self, message: str = "Network error", **kwargs):
        super().__init__(message)
        self.status_code = kwargs.get("status_code", 502)


class ValidationError(WebAPIError):
    """参数验证错误"""
    pass


class ConfigError(WebAPIError):
    """配置错误"""
    pass
