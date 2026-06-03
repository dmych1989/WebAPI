#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coze (扣子) PAT 设置助手
帮助用户获取和配置 Personal Access Token
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path.cwd()))

from src.core.config import AccountConfig

def print_coze_instructions():
    """打印 Coze PAT 获取指南"""
    print("=" * 70)
    print("Coze (扣子) Personal Access Token (PAT) 设置指南")
    print("=" * 70)
    print()
    print("获取 PAT 步骤：")
    print("1. 访问 https://www.coze.cn/home/")
    print("2. 登录你的扣子账号")
    print("3. 点击左下角头像 -> 「个人设置」")
    print("4. 点击「访问令牌 (PAT)」")
    print("5. 点击「新建令牌」")
    print("6. 设置名称（如：WebAPI）和过期时间")
    print("7. 点击「创建」")
    print("8. 复制生成的 Token (WARNING 只显示一次！)")
    print()
    print("权限要求：")
    print("- Bot 调用 (chat) 权限")
    print()
    print("注意事项：")
    print("- Token 只显示一次，请妥善保存")
    print("- 不要将 Token 分享给他人")
    print("- 定期更新 Token 以确保安全")
    print()

async def validate_coze_pat(token: str) -> dict:
    """验证 Coze PAT 有效性"""
    import aiohttp
    
    print("正在验证 Token...")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                "https://api.coze.cn/v1/user/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    user_info = data.get("data", data)
                    user_name = user_info.get("name", user_info.get("nick_name", "Unknown"))
                    user_id = user_info.get("id", "")
                    print(f"OK Token 有效！")
                    print(f"  用户名: {user_name}")
                    print(f"  用户ID: {user_id}")
                    return {
                        "valid": True,
                        "user_name": user_name,
                        "user_id": user_id
                    }
                elif resp.status == 401:
                    print("ERROR Token 无效 (401 Unauthorized)")
                    return {"valid": False, "error": "Token 无效"}
                else:
                    text = await resp.text()
                    print(f"WARNING 验证返回 HTTP {resp.status}: {text[:200]}")
                    return {"valid": False, "error": f"HTTP {resp.status}"}
        except aiohttp.ClientError as e:
            print(f"WARNING 网络错误: {e}")
            return {"valid": False, "error": str(e)}

def save_pat_to_config(token: str, user_name: str = ""):
    """保存 PAT 到 config.yaml"""
    config_path = Path("config/config.yaml")
    
    if not config_path.exists():
        print("WARNING config.yaml 不存在，将创建新文件")
    
    try:
        import yaml as yaml_lib
        
        # 读取现有配置
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml_lib.safe_load(f) or {}
        else:
            config = {}
        
        # 更新 Coze 配置
        providers = config.setdefault("providers", {})
        coze_cfg = providers.setdefault("coze", {})
        accounts = coze_cfg.setdefault("accounts", [])
        
        # 更新或添加第一个账号
        if accounts:
            accounts[0]["token"] = token
            accounts[0]["enabled"] = True
            print("OK 已更新现有账号 token")
        else:
            accounts.append({
                "name": "account-1",
                "token": token,
                "models": ["coze-chat"],
                "max_concurrent": 5,
                "health_check_interval": 60,
                "enabled": True,
            })
            print("OK 已添加新账号")
        
        # 保存配置
        with open(config_path, "w", encoding="utf-8") as f:
            yaml_lib.dump(config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"OK 配置已保存到: {config_path}")
        
    except Exception as e:
        print(f"ERROR 保存配置失败: {e}")
        return False
    
    return True

async def main():
    """主函数"""
    print("Coze (扣子) PAT 设置助手")
    print("=" * 40)
    
    # 打印获取指南
    print_coze_instructions()
    
    # 获取用户输入
    token = input("\n请输入你的 Coze PAT: ").strip()
    
    if not token:
        print("ERROR Token 为空，已取消")
        sys.exit(1)
    
    # 验证 Token
    validation_result = await validate_coze_pat(token)
    
    if not validation_result["valid"]:
        print(f"ERROR Token 验证失败: {validation_result.get('error', '未知错误')}")
        print("\n请检查：")
        print("1. Token 是否正确复制")
        print("2. Token 是否已过期")
        print("3. 是否有 Bot 调用权限")
        sys.exit(1)
    
    # 保存 Token
    user_name = validation_result.get("user_name", "")
    if save_pat_to_config(token, user_name):
        print("\nSUCCESS 设置完成！")
        print("\n下一步：")
        print("1. 重启 WebAPI 服务")
        print("2. 测试 Coze 连接")
        print("3. 开始使用 Coze 服务")
    else:
        print("ERROR 设置失败")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())