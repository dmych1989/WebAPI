#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebAPI 登录模块集成脚本 - 简化版
"""

import sys
from pathlib import Path

def check_integration_readiness():
    """检查集成准备情况"""
    print("WebAPI 登录模块集成检查")
    print("=" * 40)
    
    # 检查改进版登录器
    print("\n1. 检查改进版登录器...")
    improved_path = Path("src/login/improved_login.py")
    if improved_path.exists():
        print("OK: 改进版登录器存在")
    else:
        print("ERROR: 改进版登录器不存在")
        return False
    
    # 检查配置一致性
    print("\n2. 检查配置一致性...")
    try:
        sys.path.insert(0, str(Path.cwd()))
        from src.login.improved_login import TOKEN_EXTRACTION_CONFIGS
        
        # 验证所有 Provider 都有配置
        expected_providers = ["deepseek", "kimi", "qwen", "minimax", "doubao", "glm", "yuanbao"]
        for provider in expected_providers:
            if provider in TOKEN_EXTRACTION_CONFIGS:
                config = TOKEN_EXTRACTION_CONFIGS[provider]
                print(f"OK: {provider}: {len(config.token_sources)} 个 token 源")
            else:
                print(f"ERROR: {provider}: 缺少配置")
                return False
        
        print("OK: 所有 Provider 配置完整")
        
    except Exception as e:
        print(f"ERROR: 配置检查失败: {e}")
        return False
    
    # 检测现有登录模块
    print("\n3. 检测现有登录模块...")
    original_path = Path("src/login/__init__.py")
    if original_path.exists():
        print("OK: 原始登录模块存在")
    else:
        print("ERROR: 原始登录模块不存在")
        return False
    
    return True

def main():
    """主函数"""
    print("WebAPI 登录模块集成工具")
    print("=" * 40)
    
    if check_integration_readiness():
        print("\nSUCCESS: 集成准备完成！")
        print("\nNEXT STEPS:")
        print("1. 查看 MIGRATION_GUIDE.md")
        print("2. 运行 test_improved_login.py 验证功能")
        print("3. 按照迁移指南逐步集成")
        sys.exit(0)
    else:
        print("\nERROR: 集成准备失败")
        sys.exit(1)

if __name__ == "__main__":
    main()