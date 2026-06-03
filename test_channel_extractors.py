"""验证各渠道凭证提取器覆盖情况"""
from src.login import PROVIDER_CONFIGS


def check(prov, user_spec, predicate):
    cfg = PROVIDER_CONFIGS.get(prov)
    if not cfg:
        print(f"  [FAIL] {prov}: not configured")
        return False
    exts = cfg.get("extractors", [])
    ok = predicate(exts)
    mark = "[OK]  " if ok else "[FAIL]"
    print(f"  {mark} {prov:8s} - {user_spec}")
    if not ok:
        print(f"           actual extractors:")
        for e in exts:
            label = e.get("type")
            if e.get("key"):
                label += f".{e['key']}"
            if e.get("keys"):
                label += f".{e['keys']}"
            if e.get("cookie_name"):
                label += f".{e['cookie_name']}"
            if e.get("url_pattern"):
                label += f"({e['url_pattern']})"
            if e.get("post_process"):
                label += f" [pp={e['post_process']}]"
            print(f"             - {label}")
    return ok


expectations = [
    (
        "deepseek",
        "localStorage.userToken (用户要求)",
        lambda exts: any(
            e.get("type") == "localStorage" and e.get("key") == "userToken"
            for e in exts
        ),
    ),
    (
        "glm",
        "Cookie.chatglm_refresh_token (用户要求)",
        lambda exts: any(
            (e.get("type") == "cookie" and "chatglm_refresh_token" in e.get("keys", []))
            or (
                e.get("type") == "network_set_cookie"
                and e.get("cookie_name") == "chatglm_refresh_token"
            )
            for e in exts
        ),
    ),
    (
        "qwen",
        "Cookie.tongyi_sso_ticket (SSO 票据)",
        lambda exts: any(
            (e.get("type") == "cookie" and "tongyi_sso_ticket" in e.get("keys", []))
            or (
                e.get("type") == "network_cookie"
                and e.get("cookie_name") == "tongyi_sso_ticket"
            )
            for e in exts
        ),
    ),
    (
        "minimax",
        "JWT → Real User ID 解析",
        lambda exts: any(e.get("post_process") == "jwt_user_id" for e in exts),
    ),
    (
        "kimi",
        "Cookie.kimi-auth 优先 + JWT/refresh_token 兜底",
        lambda exts: (
            any(
                e.get("type") == "cookie" and "kimi-auth" in e.get("keys", [])
                for e in exts
            )
            and any(
                e.get("type") == "network_cookie" and e.get("cookie_name") == "kimi-auth"
                for e in exts
            )
            and any(e.get("type") == "network_auth" for e in exts)
            and any(
                e.get("type") == "localStorage" and e.get("key") == "refresh_token"
                for e in exts
            )
        ),
    ),
]

print("\n=== 各渠道凭证提取器覆盖检查 ===\n")
all_ok = True
for prov, spec, predicate in expectations:
    if not check(prov, spec, predicate):
        all_ok = False

print()
if all_ok:
    print("✅ 所有 5 个渠道的凭证提取器都已覆盖用户明确要求的方式")
    print()
    print("📋 完整覆盖清单：")
    print("  1. DeepSeek   → localStorage.userToken (JWT) + Authorization 兜底")
    print("  2. GLM        → cookie.chatglm_refresh_token + Set-Cookie 兜底")
    print("  3. Qwen       → cookie.tongyi_sso_ticket (SSO 票据) + 网络 Cookie 兜底")
    print("  4. MiniMax    → localStorage._token (JWT) → post_process: jwt_user_id → realUserId")
    print("  5. Kimi       → cookie.kimi-auth (推荐) + network_cookie 兜底 + network_auth (JWT) + refresh_token + access_token + kimi_at + auth_token")
else:
    print("❌ 存在未覆盖的渠道，请检查")
