# -*- coding: utf-8 -*-
"""
自动提取配置文件 - 定义所有Provider的提取配置

参考Chat2API的tokenExtractionConfig.ts，为每个Provider定义详细的提取策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TokenSource:
    """Token来源配置"""
    type: str  # "networkHeader" | "localStorage" | "cookie" | "html"
    key: str
    url_pattern: Optional[str] = None
    extract_pattern: Optional[str] = None
    format: Optional[str] = None  # "raw" | "name_value" | "json"


@dataclass
class TokenExtractionConfig:
    """Token提取配置"""
    name: str
    login_url: str
    auth_type: str
    token_sources: List[TokenSource]
    target_domains: List[str]
    success_url_patterns: Optional[List[str]] = None
    window_title: Optional[str] = None
    validate_url: Optional[str] = None
    validate_method: Optional[str] = None
    config_key: Optional[str] = None
    instructions: Optional[List[str]] = None
    fallback_tokens: Optional[List[str]] = None


# 所有Provider的提取配置
AUTO_EXTRACT_CONFIGS = {
    "kimi": TokenExtractionConfig(
        name="Kimi (月之暗面)",
        login_url="https://www.kimi.com/",
        auth_type="token",
        token_sources=[
            # 主要提取方式：网络请求头中的Authorization
            TokenSource(
                type="networkHeader",
                key="token",
                url_pattern="*://*.kimi.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
            # 备用提取方式：Cookie中的kimi-auth
            TokenSource(
                type="cookie",
                key="kimi-auth"
            ),
            # 备用提取方式：localStorage中的access_token
            TokenSource(
                type="localStorage",
                key="access_token"
            ),
            # 备用提取方式：localStorage中的refresh_token
            TokenSource(
                type="localStorage",
                key="refresh_token"
            ),
        ],
        target_domains=[".kimi.com", "kimi.com"],
        success_url_patterns=["kimi.com"],
        window_title="Kimi Login",
        validate_url="https://kimi.com/api",
        validate_method="bearer",
        config_key="token",
        instructions=[
            "获取 Kimi Token 步骤：",
            "1. 访问 https://www.kimi.com/ 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Token 并保存",
            "",
            "💡 支持多种提取方式，确保成功获取到有效Token",
        ],
        fallback_tokens=["access_token", "refresh_token"]
    ),
    
    "deepseek": TokenExtractionConfig(
        name="DeepSeek",
        login_url="https://chat.deepseek.com/",
        auth_type="token",
        token_sources=[
            # 主要提取方式：localStorage中的userToken
            TokenSource(
                type="localStorage",
                key="userToken"
            ),
            # 备用提取方式：网络请求头中的Authorization
            TokenSource(
                type="networkHeader",
                key="Authorization",
                url_pattern="*://*.deepseek.com/*",
                extract_pattern="^Bearer\\s+(.+)$"
            ),
        ],
        target_domains=[".deepseek.com", "deepseek.com"],
        success_url_patterns=["chat.deepseek.com"],
        window_title="DeepSeek Login",
        validate_url="https://chat.deepseek.com/api/v0/users/current",
        validate_method="bearer",
        config_key="token",
        instructions=[
            "获取 DeepSeek Token 步骤：",
            "1. 访问 https://chat.deepseek.com/ 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Token 并保存",
            "",
            "💡 DeepSeek 使用 localStorage.userToken 存储 Token",
        ],
        fallback_tokens=["userToken"]
    ),
    
    "glm": TokenExtractionConfig(
        name="GLM (智谱AI)",
        login_url="https://chatglm.cn",
        auth_type="token",
        token_sources=[
            # 主要提取方式：Cookie中的chatglm_refresh_token
            TokenSource(
                type="cookie",
                key="chatglm_refresh_token"
            ),
            # 备用提取方式：localStorage中的chatglm_refresh_token
            TokenSource(
                type="localStorage",
                key="chatglm_refresh_token"
            ),
        ],
        target_domains=[".chatglm.cn", "chatglm.cn"],
        success_url_patterns=["chatglm.cn"],
        window_title="GLM Login",
        validate_url="https://open.bigmodel.cn/api/paas/v4/models",
        validate_method="bearer",
        config_key="token",
        instructions=[
            "获取 GLM Token 步骤：",
            "1. 访问 https://chatglm.cn 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Token 并保存",
            "",
            "💡 GLM 使用 chatglm_refresh_token 作为凭证",
        ],
        fallback_tokens=["chatglm_refresh_token"]
    ),
    
    "qwen": TokenExtractionConfig(
        name="Qwen (通义千问)",
        login_url="https://www.qianwen.com",
        auth_type="token",
        token_sources=[
            # 主要提取方式：Cookie中的tongyi_sso_ticket
            TokenSource(
                type="cookie",
                key="tongyi_sso_ticket"
            ),
            # 备用提取方式：localStorage中的tongyi_sso_ticket
            TokenSource(
                type="localStorage",
                key="tongyi_sso_ticket"
            ),
        ],
        target_domains=[".qianwen.com", "qianwen.com"],
        success_url_patterns=["qianwen.com"],
        window_title="Qwen Login",
        validate_url="https://qianwen.com/api",
        validate_method="bearer",
        config_key="token",
        instructions=[
            "获取 Qwen Token 步骤：",
            "1. 访问 https://www.qianwen.com 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Token 并保存",
            "",
            "💡 Qwen 使用 tongyi_sso_ticket 作为凭证",
        ],
        fallback_tokens=["tongyi_sso_ticket"]
    ),
    
    "minimax": TokenExtractionConfig(
        name="MiniMax",
        login_url="https://agent.minimaxi.com",
        auth_type="token",
        token_sources=[
            # 主要提取方式：localStorage中的_token
            TokenSource(
                type="localStorage",
                key="_token"
            ),
            # 备用提取方式：localStorage中的user_detail_agent
            TokenSource(
                type="localStorage",
                key="user_detail_agent"
            ),
        ],
        target_domains=[".minimaxi.com", "minimaxi.com"],
        success_url_patterns=["agent.minimaxi.com"],
        window_title="MiniMax Login",
        validate_url="https://agent.minimaxi.com/api",
        validate_method="bearer",
        config_key="token",
        instructions=[
            "获取 MiniMax Token 步骤：",
            "1. 访问 https://agent.minimaxi.com 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Token 并保存",
            "",
            "💡 MiniMax 使用 localStorage._token 存储 Token",
        ],
        fallback_tokens=["_token", "user_detail_agent"]
    ),
    
    "yuanbao": TokenExtractionConfig(
        name="腾讯元宝 (Yuanbao)",
        login_url="https://yuanbao.tencent.com/chat/",
        auth_type="cookie",
        token_sources=[
            # 主要提取方式：Cookie中的x_token
            TokenSource(
                type="cookie",
                key="x_token"
            ),
            # 备用提取方式：所有Cookie
            TokenSource(
                type="all_cookies",
                key="all_cookies",
                format="header_string"
            ),
        ],
        target_domains=[".tencent.com", "yuanbao.tencent.com"],
        success_url_patterns=["yuanbao.tencent.com"],
        window_title="Yuanbao Login",
        validate_url="https://yuanbao.tencent.com/chat/",
        validate_method="cookie",
        config_key="cookie",
        instructions=[
            "获取 元宝 Cookie 步骤：",
            "1. 访问 https://yuanbao.tencent.com/chat/ 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Cookie 并保存",
            "",
            "💡 元宝使用 x_token 和其他 Cookie 作为凭证",
        ],
        fallback_tokens=["x_token"]
    ),
    
    "doubao": TokenExtractionConfig(
        name="豆包 (Doubao)",
        login_url="https://www.doubao.com/",
        auth_type="cookie",
        token_sources=[
            # 主要提取方式：Cookie中的__client_id
            TokenSource(
                type="cookie",
                key="__client_id"
            ),
            # 备用提取方式：Cookie中的doubao_session
            TokenSource(
                type="cookie",
                key="doubao_session"
            ),
            # 备用提取方式：所有Cookie
            TokenSource(
                type="all_cookies",
                key="all_cookies",
                format="header_string"
            ),
        ],
        target_domains=[".doubao.com", "doubao.com"],
        success_url_patterns=["doubao.com"],
        window_title="Doubao Login",
        validate_url="https://www.doubao.com/api",
        validate_method="cookie",
        config_key="cookie",
        instructions=[
            "获取 豆包 Cookie 步骤：",
            "1. 访问 https://www.doubao.com/ 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Cookie 并保存",
            "",
            "💡 豆包使用 __client_id 和其他 Cookie 作为凭证",
        ],
        fallback_tokens=["__client_id", "doubao_session"]
    ),
    
    "mimo": TokenExtractionConfig(
        name="小米 MiMo (Xiaomi AI Studio)",
        login_url="https://aistudio.xiaomimimo.com/",
        auth_type="cookie",
        token_sources=[
            # 主要提取方式：Cookie中的serviceToken
            TokenSource(
                type="cookie",
                key="serviceToken"
            ),
            # 主要提取方式：Cookie中的userId
            TokenSource(
                type="cookie",
                key="userId"
            ),
            # 主要提取方式：Cookie中的xiaomichatbot_ph
            TokenSource(
                type="cookie",
                key="xiaomichatbot_ph"
            ),
            # 备用提取方式：localStorage中的serviceToken
            TokenSource(
                type="localStorage",
                key="serviceToken"
            ),
            # 备用提取方式：localStorage中的userId
            TokenSource(
                type="localStorage",
                key="userId"
            ),
            # 备用提取方式：localStorage中的xiaomichatbot_ph
            TokenSource(
                type="localStorage",
                key="xiaomichatbot_ph"
            ),
        ],
        target_domains=[".xiaomimimo.com", "xiaomimimo.com", ".mi.com"],
        success_url_patterns=["aistudio.xiaomimimo.com"],
        window_title="MiMo Login",
        validate_url="https://aistudio.xiaomimimo.com/api",
        validate_method="cookie",
        config_key="cookie",
        instructions=[
            "获取 MiMo Cookie 步骤：",
            "1. 访问 https://aistudio.xiaomimimo.com/ 并登录你的账号",
            "2. 等待页面加载完成",
            "3. 系统会自动提取 Cookie 并保存",
            "",
            "💡 MiMo 需要 3 个 Cookie 字段：serviceToken, userId, xiaomichatbot_ph",
        ],
        fallback_tokens=["serviceToken", "userId", "xiaomichatbot_ph"]
    ),
    
    "coze": TokenExtractionConfig(
        name="Coze",
        login_url="https://coze.cn",
        auth_type="manual_pat",
        token_sources=[
            # Coze 使用 Personal Access Token，需要手动输入
            TokenSource(
                type="manual",
                key="pat"
            ),
        ],
        target_domains=[".coze.cn", "coze.cn"],
        success_url_patterns=["coze.cn"],
        window_title="Coze Login",
        validate_url="https://api.coze.cn/v1/user/me",
        validate_method="bearer",
        config_key="token",
        instructions=[
            "获取 Coze Personal Access Token 步骤：",
            "1. 访问 https://coze.cn 并登录你的账号",
            "2. 进入「个人中心」→「API密钥」",
            "3. 点击「创建API密钥」",
            "4. 输入密钥名称，点击「创建」",
            "5. 复制生成的 Personal Access Token",
            "",
            "⚠️ API密钥仅显示一次，请妥善保存",
        ],
        fallback_tokens=["pat"]
    ),
}


def get_auto_extract_config(provider: str) -> TokenExtractionConfig:
    """获取指定Provider的自动提取配置"""
    return AUTO_EXTRACT_CONFIGS.get(provider)


def get_supported_providers() -> List[str]:
    """获取支持的Provider列表"""
    return list(AUTO_EXTRACT_CONFIGS.keys())


def get_provider_info(provider: str) -> dict:
    """获取Provider信息"""
    config = AUTO_EXTRACT_CONFIGS.get(provider)
    if not config:
        return {}
    
    return {
        "name": config.name,
        "login_url": config.login_url,
        "auth_type": config.auth_type,
        "supported": True,
        "extraction_methods": [source.type for source in config.token_sources],
        "instructions": config.instructions or []
    }


def validate_provider_config(provider: str) -> bool:
    """验证Provider配置"""
    config = AUTO_EXTRACT_CONFIGS.get(provider)
    if not config:
        return False
    
    # 检查必要的字段
    if not config.name or not config.login_url:
        return False
    
    # 检查token_sources
    if not config.token_sources:
        return False
    
    # 检查token_sources的格式
    for source in config.token_sources:
        if not source.type or not source.key:
            return False
    
    return True


# 配置验证
def validate_all_configs() -> dict:
    """验证所有配置"""
    results = {
        "total": len(AUTO_EXTRACT_CONFIGS),
        "valid": 0,
        "invalid": 0,
        "errors": []
    }
    
    for provider, config in AUTO_EXTRACT_CONFIGS.items():
        if validate_provider_config(provider):
            results["valid"] += 1
        else:
            results["invalid"] += 1
            results["errors"].append(f"Invalid config for {provider}")
    
    return results


# 初始化验证
if __name__ == "__main__":
    # 验证所有配置
    validation_results = validate_all_configs()
    
    print(f"自动提取配置验证结果:")
    print(f"  总配置数: {validation_results['total']}")
    print(f"  有效配置: {validation_results['valid']}")
    print(f"  无效配置: {validation_results['invalid']}")
    
    if validation_results["errors"]:
        print(f"  错误信息:")
        for error in validation_results["errors"]:
            print(f"    - {error}")
    
    if validation_results["invalid"] == 0:
        print(f"✓ 所有配置验证通过")
    else:
        print(f"✗ 存在无效配置")