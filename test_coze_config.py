#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 Coze Provider 配置
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path.cwd()))

from src.core.config import AccountConfig
from src.provider.coze import CozeProvider

async def test_coze_config():
    """测试 Coze 配置"""
    print("Coze Provider 配置测试")
    print("=" * 40)
    
    # 检查配置文件
    config_path = Path("config/config.yaml")
    if not config_path.exists():
        print("ERROR: config.yaml 不存在")
        return False
    
    # 读取配置
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"ERROR: 读取配置失败 - {e}")
        return False
    
    # 检查 Coze 配置
    coze_config = config.get("providers", {}).get("coze", {})
    if not coze_config:
        print("ERROR: Coze 配置不存在")
        return False
    
    accounts = coze_config.get("accounts", [])
    if not accounts:
        print("ERROR: Coze 账号配置不存在")
        return False
    
    account = accounts[0]
    token = account.get("token", "")
    
    if not token:
        print("ERROR: Coze Token 为空")
        print("\n解决方案:")
        print("1. 运行 python setup_coze_pat.py 设置 PAT")
        print("2. 或手动在 config.yaml 中添加 token")
        return False
    
    print(f"OK: 找到 Coze Token: {token[:20]}...")
    
    # 创建 Provider 实例
    try:
        account_config = AccountConfig(
            name=account.get("name", "account-1"),
            token=token,
            models=account.get("models", ["coze-chat"]),
            max_concurrent=account.get("max_concurrent", 5),
            health_check_interval=account.get("health_check_interval", 60),
            enabled=account.get("enabled", True)
        )
        
        provider = CozeProvider(account_config)
        print(f"OK: Coze Provider 创建成功")
        print(f"OK: Base URL: {provider._base_url}")
        
        # 测试健康检查
        print("\n1. 测试健康检查...")
        try:
            is_healthy = await provider.health_check()
            print(f"OK: 健康检查 {'通过' if is_healthy else '失败'}")
        except Exception as e:
            print(f"ERROR: 健康检查失败 - {e}")
        
        # 测试模型列表
        print("\n2. 测试模型列表...")
        try:
            models = await provider.list_models()
            print(f"OK: 可用模型: {models}")
        except Exception as e:
            print(f"ERROR: 获取模型列表失败 - {e}")
        
        # 测试 Bot ID 解析
        print("\n3. 测试 Bot ID 解析...")
        try:
            bot_id = await provider._resolve_bot_id("coze-chat")
            print(f"OK: Bot ID 解析成功: {bot_id}")
        except Exception as e:
            print(f"ERROR: Bot ID 解析失败 - {e}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: 创建 Provider 失败 - {e}")
        return False

async def main():
    """主函数"""
    success = await test_coze_config()
    
    if success:
        print("\nSUCCESS: Coze 配置测试通过")
    else:
        print("\nERROR: Coze 配置测试失败")
        print("\n请确保：")
        print("1. config.yaml 中有正确的 Coze 配置")
        print("2. Token 不为空且有效")
        print("3. 网络连接正常")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())