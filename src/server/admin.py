# -*- coding: utf-8 -*-
"""WebAPI — Admin API

管理接口：配置热更新、账号池状态、Provider 列表。
"""

from __future__ import annotations

from typing import Optional

import asyncio
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.core.config import reload_config, get_config
from src.provider.base import ProviderRegistry
from src.pool import account_pool
from src.core.logger import logger

router = APIRouter()


class ManualCredentialInput(BaseModel):
    """手动输入的凭证

    字段全部可选 — 用户根据 Provider 提示填入对应字段：
    - token:  Bearer Token / JWT（kimi/deepseek/minimax/qwen）
    - cookie: Cookie 字符串（yuanbao/doubao/glm/qwen 等）
    - user_id: Real User ID（minimax 等需要 User ID 的 Provider）
    - service_token: MiMo 专用 serviceToken
    - xiaomichatbot_ph: MiMo 专用会话标识
    - account_name: 自定义账户名称（不填则自动生成）
    - models:  要暴露的模型列表（不填则使用 provider 自身的默认模型）
    """
    account_name: Optional[str] = None
    token: Optional[str] = None
    cookie: Optional[str] = None
    user_id: Optional[str] = None
    service_token: Optional[str] = None
    xiaomichatbot_ph: Optional[str] = None
    models: Optional[list[str]] = None


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


@router.post("/providers/check")
async def check_all_providers():
    """主动触发所有渠道健康检查（刷新按钮专用）

    对每个已启用的 Provider 账号执行 health_check(),
    返回逐渠道的检测结果（成功/失败 + 原因 + 延迟）。
    """
    config = get_config()
    results = []

    for provider_type in ProviderRegistry.list_all():
        provider_cls = ProviderRegistry.get(provider_type)
        if provider_cls is None:
            continue

        provider_config = config.providers.get(provider_type)
        if provider_config is None:
            continue

        for acc_config in provider_config.accounts:
            if not acc_config.enabled:
                continue

            result = {
                "provider": provider_type,
                "account": acc_config.name,
                "healthy": False,
                "reason": "",
                "latency_ms": 0,
            }

            try:
                provider = provider_cls(acc_config)
                t0 = time.time()
                is_healthy = await asyncio.wait_for(
                    provider.health_check(), timeout=15
                )
                latency = int((time.time() - t0) * 1000)
                result["latency_ms"] = latency

                if is_healthy:
                    account_pool.mark_healthy(provider_type, acc_config.name)
                    result["healthy"] = True
                    result["reason"] = "OK"
                else:
                    account_pool.mark_unhealthy(
                        provider_type, acc_config.name, "health check failed"
                    )
                    result["reason"] = "health check returned False"
            except asyncio.TimeoutError:
                account_pool.mark_unhealthy(provider_type, acc_config.name, "timeout")
                result["reason"] = "连接超时（15秒）"
            except Exception as e:
                err_msg = str(e)[:200]
                account_pool.mark_unhealthy(provider_type, acc_config.name, err_msg)
                result["reason"] = err_msg

            results.append(result)

    total = len(results)
    healthy = sum(1 for r in results if r["healthy"])
    unhealthy = total - healthy

    return {
        "status": "ok",
        "message": f"检测完成：{healthy}/{total} 个渠道可用",
        "total": total,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "results": results,
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

    先用 GUI 模式尝试（需要桌面环境），失败自动返回友好错误。
    登录成功后凭证会自动加密写入 config.yaml。

    Args:
        provider: deepseek | kimi | qwen | minimax | doubao | yuanbao | glm | coze
    """
    import asyncio
    from src.login import PROVIDER_CONFIGS, TokenExtractor

    if provider not in PROVIDER_CONFIGS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}. "
                    f"Available: {', '.join(PROVIDER_CONFIGS.keys())}"
        )

    cfg = PROVIDER_CONFIGS[provider]

    # Coze / manual_pat providers: 不走浏览器，返回手动输入指引
    if cfg.get("auth_type") == "manual_pat":
        instructions = cfg.get("pat_instructions", [])
        return {
            "status": "manual_input_required",
            "provider": provider,
            "auth_type": "manual_pat",
            "message": (
                f"⚠️ {cfg['name']} 使用 Personal Access Token (PAT) 认证，需手动输入。\n\n"
                + "\n".join(instructions)
            ),
            "login_url": cfg.get("login_url"),
            "fallback": "manual_input",
        }

    # 先检查 playwright 是否可用
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "status": "error",
            "provider": provider,
            "message": (
                "\u26a0\ufe0f Playwright \u672a\u5b89\u88c5\uff0c\u65e0\u6cd5\u81ea\u52a8\u767b\u5f55\u3002\n"
                "\u8bf7\u5148\u8fd0\u884c: pip install playwright && playwright install chromium\n"
                "\u6216\u4f7f\u7528\u300c\u270f\ufe0f \u8f93\u5165\u300d\u6309\u94ae\u624b\u52a8\u7c98\u8d34\u51ed\u8bc1\u3002"
            ),
            "fallback": "manual_input",
        }

    try:
        extractor = TokenExtractor(provider, headless=False)
        result = await asyncio.wait_for(extractor.run(), timeout=360)

        # 检查是否真的提取到了凭证
        is_dict = isinstance(result, dict)
        value_len = len(str(result.get("value", ""))) if is_dict else len(str(result))
        type_str = result.get("type") if is_dict else "unknown"
        cfg_key = result.get("config_key") if is_dict else "unknown"

        if not is_dict or not result or value_len == 0 or not type_str:
            return {
                "status": "warning",
                "provider": provider,
                "extracted": {
                    "type": type_str or None,
                    "config_key": cfg_key or None,
                    "value_length": value_len,
                },
                "message": (
                    f"⚠️ {provider} 浏览器流程已完成，但未提取到凭证。\n"
                    "可能原因: (1) 浏览器窗口中未完成登录\n"
                    "           (2) 该 Provider 暂时无法通过自动方式获取 Token\n"
                    "💡 建议改用「✏️ 输入」按钮手动粘贴 Token/Cookie。"
                ),
                "fallback": "manual_input",
            }

        return {
            "status": "ok",
            "provider": provider,
            "extracted": {
                "type": type_str,
                "config_key": cfg_key,
                "value_length": value_len,
            },
            "message": f"✅ {provider} 凭证已提取并保存到 config.yaml，请重启服务生效",
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408,
            detail="\u767b\u5f55\u8d85\u65f6\uff086\u5206\u949f\uff09\uff0c\u8bf7\u786e\u8ba4\u5df2\u5728\u6d4f\u89c8\u5668\u4e2d\u5b8c\u6210\u767b\u5f55"
        )
    except RuntimeError as e:
        # RuntimeError \u6765\u81ea TokenExtractor\uff08Playwright \u4e0d\u53ef\u7528\u7b49\uff09
        return {
            "status": "error",
            "provider": provider,
            "message": f"\u26a0\ufe0f {str(e)}\n\n\ud83d\udca1 \u66ff\u4ee3\u65b9\u6848: \u4f7f\u7528\u300c\u270f\ufe0f \u8f93\u5165\u300d\u6309\u94ae\u624b\u52a8\u7c98\u8d34 Token/Cookie",
            "fallback": "manual_input",
        }
    except Exception as e:
        logger.error(f"[Admin] Login failed for {provider}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 各 Provider 的凭证字段提示 + 登录指引（前端 Modal 渲染用）
# 参考 Chat2API 的 LoginGuideDialog + providerGuides + builtin credentialFields
PROVIDER_CREDENTIAL_HINTS = {
    "deepseek": {
        "login_url": "https://chat.deepseek.com/",
        "steps": [
            "点击下方按钮打开 DeepSeek 网站",
            "登录你的账号（扫码/手机/邮箱）",
            "按 F12 打开开发者工具",
            "切换到 Application（应用程序）标签",
            "左侧找到 Local Storage → chat.deepseek.com",
            '找到 userToken 字段，复制其值',
        ],
        "primary": "token",
        "fields": [
            {
                "name": "token",
                "label": "userToken (JWT)",
                "placeholder": "粘贴从 Local Storage 复制的 userToken 值",
                "help": "从浏览器 DevTools → Application → Local Storage → userToken 复制",
                "required": True,
            },
        ],
    },
    "kimi": {
        "login_url": "https://www.kimi.com/",
        "steps": [
            "点击下方按钮打开 Kimi 网站",
            "登录你的账号",
            "按 F12 打开开发者工具",
            "切换到 Application → Local Storage → www.kimi.com",
            "找到 access_token 或 refresh_token 字段",
            "复制其值（JWT，以 eyJ 开头）",
        ],
        "primary": "token",
        "fields": [
            {
                "name": "token",
                "label": "access_token (JWT, eyJ...)",
                "placeholder": "粘贴从 Local Storage 复制的 access_token",
                "help": "或从 Network 请求中复制 Authorization: Bearer xxx",
                "required": True,
            },
        ],
    },
    "qwen": {
        "login_url": "https://www.qianwen.com/?source=tongyigw",
        "steps": [
            "点击下方按钮打开通义千问网站",
            "登录你的阿里云账号",
            "按 F12 打开开发者工具",
            "切换到 Application → Cookies → www.qianwen.com",
            "找到 tongyi_sso_ticket 字段",
            "复制其值",
        ],
        "primary": "token",
        "fields": [
            {
                "name": "token",
                "label": "tongyi_sso_ticket",
                "placeholder": "粘贴 Cookie 中 tongyi_sso_ticket 的值",
                "help": "F12 → Application → Cookies → qianwen.com → tongyi_sso_ticket",
                "required": True,
            },
        ],
    },
    "minimax": {
        "login_url": "https://agent.minimaxi.com/",
        "steps": [
            "点击下方按钮打开 MiniMax (Hailuo AI) 网站",
            "登录你的账号",
            "按 F12 打开开发者工具",
            "切换到 Application → Local Storage → agent.minimaxi.com",
            '找到 _token 字段（JWT，以 eyJ 开头），复制其值',
            "如需 realUserID，同时找到 user_detail_agent 字段",
        ],
        "primary": "token",
        "fields": [
            {
                "name": "token",
                "label": "JWT Token (_token)",
                "placeholder": "粘贴 _token 值（JWT，以 eyJ 开头）",
                "help": "F12 → Application → Local Storage → agent.minimaxi.com → _token",
                "required": True,
            },
            {
                "name": "user_id",
                "label": "Real User ID（可选）",
                "placeholder": "从 user_detail_agent JSON 中提取 realUserID 字段",
                "help": "填写后将以 'realUserID+JWT' 格式拼接认证",
                "required": False,
            },
        ],
    },
    "doubao": {
        "login_url": "https://www.doubao.com/chat/",
        "steps": [
            "点击下方按钮打开豆包网站",
            "登录你的抖音/字节账号",
            "按 F12 打开开发者工具",
            "切换到 Application → Cookies → www.doubao.com",
            "复制所有 Cookie（全选 → 复制）",
            "或使用浏览器扩展一键导出",
        ],
        "primary": "cookie",
        "fields": [
            {
                "name": "cookie",
                "label": "完整 Cookie 字符串",
                "placeholder": "粘贴从 doubao.com 复制的完整 Cookie（name1=value1; name2=value2; ...）",
                "help": "F12 → Application → Cookies → doubao.com → 全选 Cookie 拼接为字符串",
                "required": True,
            },
        ],
    },
    "yuanbao": {
        "login_url": "https://yuanbao.tencent.com/chat/",
        "steps": [
            "点击下方按钮打开腾讯元宝网站",
            "登录你的微信/QQ 账号",
            "按 F12 打开开发者工具",
            "切换到 Application → Cookies → yuanbao.tencent.com",
            "复制所有 Cookie（全选 → 复制）",
            "确保包含关键的 hy_source、hy_token 等字段",
        ],
        "primary": "cookie",
        "fields": [
            {
                "name": "cookie",
                "label": "完整 Cookie 字符串",
                "placeholder": "粘贴从 yuanbao.tencent.com 复制的完整 Cookie",
                "help": "F12 → Application → Cookies → yuanbao.tencent.com → 全选 Cookie 拼接",
                "required": True,
            },
        ],
    },
    "glm": {
        "login_url": "https://chatglm.cn/main/alltoolsdetail?lang=zh",
        "steps": [
            "点击下方按钮打开 GLM 工具页面",
            "登录你的账号（手机/微信）",
            "按 F12 打开开发者工具",
            "切换到 Application → Cookies → chatglm.cn",
            "找到 chatglm_refresh_token 字段",
            "复制其值",
        ],
        "primary": "cookie",
        "fields": [
            {
                "name": "cookie",
                "label": "chatglm_refresh_token",
                "placeholder": "粘贴从 Cookie 复制的 chatglm_refresh_token 值",
                "help": "F12 → Application → Cookies → chatglm.cn → chatglm_refresh_token",
                "required": True,
            },
        ],
    },
    "mimo": {
        "login_url": "https://aistudio.xiaomimimo.com/",
        "steps": [
            "点击下方按钮打开 MiMo AI Studio 网站",
            "登录你的小米账号",
            "按 F12 打开开发者工具",
            "切换到 Application（应用程序）标签",
            "左侧找到 Cookies → https://aistudio.xiaomimimo.com",
            "找到并复制以下 3 个字段的值：",
            "  - serviceToken",
            "  - userId",
            "  - xiaomichatbot_ph",
        ],
        "primary": "service_token",
        "fields": [
            {
                "name": "service_token",
                "label": "serviceToken",
                "placeholder": "从浏览器 Cookie 复制的 serviceToken 值",
                "help": "F12 → Application → Cookies → serviceToken",
                "required": True,
            },
            {
                "name": "user_id",
                "label": "userId",
                "placeholder": "从浏览器 Cookie 复制的 userId 值",
                "help": "F12 → Application → Cookies → userId",
                "required": True,
            },
            {
                "name": "xiaomichatbot_ph",
                "label": "xiaomichatbot_ph",
                "placeholder": "从浏览器 Cookie 复制的 xiaomichatbot_ph 值",
                "help": "F12 → Application → Cookies → xiaomichatbot_ph",
                "required": True,
            },
        ],
    },
}


@router.get("/credentials/hints")
async def get_credential_hints():
    """获取所有 Provider 的凭证输入提示"""
    return PROVIDER_CREDENTIAL_HINTS


@router.post("/credentials/{provider}")
async def set_manual_credentials(
    provider: str, body: ManualCredentialInput
):
    """手动输入凭证（保存到 config.yaml）

    适用于千问/minimax 等无法自动获取凭证的场景。
    字段全部可选 — 用户根据 Provider 提示填入对应字段。
    凭证会被 Fernet 加密后保存；config.yaml 中显示为 `enc:v1:...` 密文。

    Args:
        provider: deepseek | kimi | qwen | minimax | doubao | yuanbao | glm
        body: {token?, cookie?, user_id?}

    Returns:
        {status, fields_saved, message}
    """
    if provider not in PROVIDER_CREDENTIAL_HINTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}. "
            f"Available: {', '.join(PROVIDER_CREDENTIAL_HINTS.keys())}",
        )

    # 至少要有一个非空字段
    fields = {
        "token": (body.token or "").strip(),
        "cookie": (body.cookie or "").strip(),
        "user_id": (body.user_id or "").strip(),
        "service_token": (body.service_token or "").strip(),
        "xiaomichatbot_ph": (body.xiaomichatbot_ph or "").strip(),
    }
    fields = {k: v for k, v in fields.items() if v}
    if not fields:
        raise HTTPException(
            status_code=400,
            detail="至少需要提供一个非空字段（token / cookie / user_id / service_token / xiaomichatbot_ph）",
        )

    # 读取现有 config.yaml
    import yaml
    from src.core.config import _find_config_path

    config_path = _find_config_path()
    if not config_path.exists():
        raise HTTPException(
            status_code=500,
            detail="config.yaml 不存在",
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # 更新 Provider 配置
    providers = config.setdefault("providers", {})
    provider_entry = providers.setdefault(provider, {})
    provider_entry["enabled"] = True
    accounts = provider_entry.setdefault("accounts", [])

    # 解析账户名（自定义 or 复用 or 自动生成）
    custom_name = (body.account_name or "").strip()
    account = None
    if custom_name:
        # 查找同名账户
        for acc in accounts:
            if acc.get("name") == custom_name:
                account = acc
                break
    if account is None:
        if not accounts:
            # 首次配置 → 用自定义名或默认 account-1
            default_name = custom_name or "account-1"
            accounts.append({
                "name": default_name,
                "models": [],
                "max_concurrent": 5,
                "health_check_interval": 60,
            })
            account = accounts[0]
        elif custom_name:
            # 用户指定了不存在的账户名 → 新建
            accounts.append({
                "name": custom_name,
                "models": [],
                "max_concurrent": 5,
                "health_check_interval": 60,
            })
            account = accounts[-1]
        else:
            # 用户未指定 → 使用第一个
            account = accounts[0]

    # 写入字段（保留加密由 save_config 完成）
    # 这里我们临时不加密：直接写明文，下次 load_config() 会自动加密保存
    # 但为了一致性，立即用 credential_crypto 加密
    from src.utils.crypto import credential_crypto

    for key, value in fields.items():
        # 加密敏感字段（token / cookie / user_id 都视为敏感）
        encrypted = credential_crypto.encrypt(value)
        account[key] = encrypted
        logger.info(
            f"[Admin] Set {provider}.{account.get('name', 'account-1')}.{key} "
            f"({len(value)} chars, encrypted to {len(encrypted)} chars)"
        )

    # models 字段（如指定）直接覆盖
    if body.models is not None:
        # 清洗：去空白、去空项、去重保序
        seen_m: set[str] = set()
        cleaned: list[str] = []
        for m in body.models:
            m = (m or "").strip()
            if not m or m in seen_m:
                continue
            seen_m.add(m)
            cleaned.append(m)
        account["models"] = cleaned
        logger.info(
            f"[Admin] Set {provider}.{account.get('name', 'account-1')}.models = {cleaned}"
        )

    # 写回 config.yaml
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 标记账号 healthy 并重新加载配置（让 UI 立即看到更新）
    from src.core.config import reload_config as _reload_cfg
    _reload_cfg()
    account_pool.register_provider(provider, get_config().providers[provider])
    account_pool.mark_healthy(provider, account.get("name", "account-1"))

    return {
        "status": "ok",
        "provider": provider,
        "account": account.get("name", "account-1"),
        "fields_saved": list(fields.keys()),
        "message": (
            f"✅ {provider} 凭证已保存（字段: {', '.join(fields.keys())}）\n"
            f"凭证已 Fernet 加密后写入 config.yaml。\n"
            f"请重启 WebAPI 服务以加载新凭证。"
        ),
    }


def _select_healthy_accounts(provider: str) -> list[tuple[str, "AccountConfig"]]:
    """获取某 Provider 的所有健康账号（按名称排序）"""
    states = getattr(account_pool, "_accounts", {}).get(provider, [])
    now = time.time()
    result: list[tuple[str, "AccountConfig"]] = []
    for state in states:
        # 冷却期内视为不健康
        if state.cooldown_until > now:
            continue
        if not state.healthy:
            continue
        cfg = account_pool.get_account_config(provider, state.name)
        if cfg is None:
            continue
        result.append((state.name, cfg))
    return result


@router.post("/credentials/{provider}/validate")
async def validate_credential(provider: str):
    """验证 Provider 凭证是否有效

    调用对应 Provider 的 health_check() 方法进行验证。
    """
    from src.provider.base import ProviderRegistry

    providers = ProviderRegistry.list_all()
    if provider not in providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}",
        )

    # 获取所有 healthy 账户
    healthy = _select_healthy_accounts(provider)
    if not healthy:
        return {
            "status": "warning",
            "provider": provider,
            "healthy_count": 0,
            "message": (
                f"⚠️ {provider} 当前没有 healthy 账户，"
                f"请先通过「✏️ 输入」或「🔑 登录」保存凭证并重启服务。"
            ),
        }

    # 尝试 health_check 第一个账户
    account_name, account_cfg = healthy[0]
    forwarder = ProviderRegistry.create(provider, account_cfg)
    if forwarder is None:
        raise HTTPException(status_code=500, detail=f"无法创建 {provider} forwarder")

    try:
        ok = await forwarder.health_check()
        detail = "健康检查通过" if ok else "健康检查未通过"
    except Exception as e:
        ok, detail = False, f"健康检查异常: {e}"

    return {
        "status": "ok" if ok else "error",
        "provider": provider,
        "account": account_name,
        "healthy_count": len(healthy),
        "valid": ok,
        "detail": detail,
        "message": (
            f"✅ {provider}/{account_name} 凭证有效 — {detail}"
            if ok
            else f"❌ {provider}/{account_name} 凭证无效 — {detail}"
        ),
    }


@router.delete("/credentials/{provider}/accounts/{account_name}")
async def delete_account_credential(provider: str, account_name: str):
    """删除指定账户"""
    import yaml
    from src.core.config import _find_config_path

    config_path = _find_config_path()
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="config.yaml 不存在")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    providers = config.get("providers", {})
    provider_entry = providers.get(provider)
    if not provider_entry:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' 不存在")

    accounts = provider_entry.get("accounts", [])
    idx = next(
        (i for i, a in enumerate(accounts) if a.get("name") == account_name),
        None,
    )
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"账户 '{account_name}' 在 {provider} 中不存在",
        )

    removed = accounts.pop(idx)
    # 如果删完了，至少保留一个空账户
    if not accounts:
        accounts.append({
            "name": "account-1",
            "models": [],
            "max_concurrent": 5,
            "health_check_interval": 60,
        })

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 清理账户池
    from src.pool.account_pool import account_pool
    account_pool.mark_unhealthy(provider, account_name)
    # 重置后立即从 healthy 列表移除

    return {
        "status": "ok",
        "provider": provider,
        "account": account_name,
        "message": f"✅ 已删除 {provider}/{account_name}（配置中剩余 {len(accounts)} 个账户）\n请重启服务以加载新配置。",
    }


@router.post("/credentials/{provider}/accounts/{account_name}/clear-chats")
async def clear_conversation_history(provider: str, account_name: str):
    """清除对话历史（仅对支持该操作的 Provider 生效）

    支持的 Provider: deepseek / kimi / qwen / yuanbao
    不支持的 Provider: minimax / glm / doubao（API 层无此能力）
    """
    SUPPORTED = {"deepseek", "kimi", "qwen", "yuanbao"}

    if provider not in SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' 不支持清除对话历史。支持: {', '.join(SUPPORTED)}",
        )

    # 找到该名称的账户（不一定要求 healthy — 也要支持未冷却的）
    target_name, account_cfg = None, None
    for name, cfg in _select_healthy_accounts(provider):
        if name == account_name:
            target_name, account_cfg = name, cfg
            break

    if account_cfg is None:
        # 兜底：直接用配置中的账户（即使 unhealthy）
        account_cfg = account_pool.get_account_config(provider, account_name)
        if account_cfg is None:
            raise HTTPException(
                status_code=404,
                detail=f"账户 '{account_name}' 在 {provider} 中不存在",
            )
        target_name = account_name

    # 异步调用各 Provider 的 clear_chats 实现
    try:
        from src.provider.base import ProviderRegistry

        forwarder = ProviderRegistry.create(provider, account_cfg)
        if forwarder is None:
            raise RuntimeError(f"无法创建 {provider} forwarder")

        result = await forwarder.clear_conversations()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清除失败: {e}")

    if not isinstance(result, dict):
        result = {"ok": False, "deleted_count": 0, "detail": str(result)}

    ok = result.get("ok", True)
    return {
        "status": "ok" if ok else "error",
        "provider": provider,
        "account": target_name,
        "deleted_count": result.get("deleted_count", 0),
        "detail": result.get("detail", ""),
        "message": (
            f"✅ 已清除 {provider}/{target_name} 的对话历史（{result.get('deleted_count', 0)} 个）"
            if ok
            else f"⚠️ {provider}/{target_name} 清除失败: {result.get('detail', '')}"
        ),
    }


# =============================================================================
# OAuth 凭证验证端点（参考 Chat2API OAuth Manager）
# =============================================================================

class OAuthValidateInput(BaseModel):
    """OAuth 凭证验证请求体"""
    token: Optional[str] = None
    cookie: Optional[str] = None
    user_id: Optional[str] = None
    real_user_id: Optional[str] = None
    # MiMo 专用字段
    service_token: Optional[str] = None
    xiaomichatbot_ph: Optional[str] = None


@router.post("/oauth/validate/{provider}")
async def oauth_validate_credentials(provider: str, body: OAuthValidateInput):
    """使用 OAuth 适配器验证凭证

    参考 Chat2API OAuthManager.validateToken:
    - 调用对应 Provider 的 OAuthAdapter.validateToken()
    - 返回账户信息（user_id, name 等）
    """
    from src.login.adapters import get_adapter

    SUPPORTED = {"deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao", "glm", "mimo"}

    if provider not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    adapter = get_adapter(provider)
    if not adapter:
        return {
            "success": False,
            "provider": provider,
            "error": "No OAuth adapter for this provider",
        }

    # 构建凭证
    credentials: dict[str, str] = {}
    if body.token:
        credentials["token"] = body.token
    if body.cookie:
        credentials["cookie"] = body.cookie
    if body.user_id:
        credentials["user_id"] = body.user_id
    if body.real_user_id:
        credentials["realUserID"] = body.real_user_id
    # MiMo 专用字段
    if body.service_token:
        credentials["service_token"] = body.service_token
    if body.xiaomichatbot_ph:
        credentials["xiaomichatbot_ph"] = body.xiaomichatbot_ph

    if not credentials:
        raise HTTPException(status_code=400, detail="No credentials provided")

    result = await adapter.validate_token(credentials)

    return {
        "success": result.valid,
        "provider": provider,
        "token_type": result.token_type,
        "account_info": result.account_info,
        "error": result.error,
        "message": (
            f"✅ {provider} 凭证有效 — {result.account_info or ''}"
            if result.valid
            else f"❌ {provider} 凭证无效 — {result.error}"
        ),
    }


@router.post("/oauth/browser-login/{provider}")
async def oauth_browser_login(provider: str):
    """启动浏览器 OAuth 登录流程

    参考 Chat2API OAuthManager.startLogin + InAppLoginManager.startLogin:
    - 启动 Playwright 浏览器
    - 导航到 Provider 登录页面
    - 拦截网络请求/响应，捕获 Token/Cookie
    - 自动提取并验证凭证
    - 保存到 config.yaml

    这是一个长时间运行的请求（最多 6 分钟）。
    浏览器窗口会显示在前端，用户在浏览器中完成登录后自动提取凭证。
    """
    from src.login.oauth import OAuthManager, TOKEN_EXTRACTION_CONFIGS

    SUPPORTED = {"deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao", "mimo"}

    if provider not in SUPPORTED:
        return {
            "status": "manual_input_required",
            "provider": provider,
            "error": f"Provider '{provider}' 不支持浏览器自动登录，请使用手动输入。",
        }

    # 检查 Playwright
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "status": "error",
            "provider": provider,
            "error": "Playwright 未安装，请运行: pip install playwright && playwright install chromium",
            "fallback": "manual_input",
        }

    # 获取 token 提取配置
    cfg = TOKEN_EXTRACTION_CONFIGS.get(provider)
    if not cfg or not cfg.token_sources:
        return {
            "status": "manual_input_required",
            "provider": provider,
            "login_url": cfg.login_url if cfg else "",
            "error": f"{provider} 需要手动输入凭证，不支持浏览器自动提取。",
            "fallback": "manual_input",
        }

    try:
        oauth_manager = OAuthManager(provider, headless=False)
        result = await asyncio.wait_for(oauth_manager.login(timeout=360.0), timeout=400.0)

        if result.success:
            # 重新加载配置并注册账号池（对齐 accounts.py create_account 流程）
            from src.core.config import reload_config as _reload_cfg
            _reload_cfg()
            cfg = get_config()
            provider_cfg = cfg.providers.get(provider)
            if provider_cfg:
                account_pool.register_provider(provider, provider_cfg)
                # 标记账号健康（对齐 accounts.py）
                account_pool.mark_healthy(provider, "account-1")

            return {
                "status": "ok",
                "provider": provider,
                "account_info": result.account_info,
                "message": f"✅ {provider} 凭证已提取并保存到 config.yaml，请重启服务生效",
            }
        else:
            return {
                "status": "warning",
                "provider": provider,
                "error": result.error or "未提取到有效凭证",
                "fallback": "manual_input",
            }

    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "provider": provider,
            "error": "登录超时（6分钟），请在浏览器中完成登录后重试",
            "fallback": "manual_input",
        }
    except RuntimeError as e:
        return {
            "status": "error",
            "provider": provider,
            "error": str(e),
            "fallback": "manual_input",
        }
    except Exception as e:
        logger.error(f"[Admin] OAuth browser login failed for {provider}: {e}")
        return {
            "status": "error",
            "provider": provider,
            "error": str(e),
            "fallback": "manual_input",
        }
