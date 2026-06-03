#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的 WebAPI 登录模块集成检查
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

def check_files():
    """检查文件存在性"""
    print("WebAPI 登录模块集成检查")
    print("=" * 40)
    
    # 检查文件
    files_to_check = [
        "src/login/improved_login.py",
        "src/login/__init__.py",
        "test_improved_login.py"
    ]
    
    all_ok = True
    for file_path in files_to_check:
        if os.path.exists(file_path):
            print(f"OK: {file_path}")
        else:
            print(f"ERROR: {file_path} 不存在")
            all_ok = False
    
    return all_ok

def check_improved_login():
    """检查改进版登录器"""
    print("\n检查改进版登录器...")
    try:
        from src.login.improved_login import TOKEN_EXTRACTION_CONFIGS, ImprovedTokenExtractor
        
        # 检查 Provider 配置
        expected_providers = ["deepseek", "kimi", "qwen", "minimax", "doubao", "glm", "yuanbao"]
        for provider in expected_providers:
            if provider in TOKEN_EXTRACTION_CONFIGS:
                config = TOKEN_EXTRACTION_CONFIGS[provider]
                print(f"OK: {provider} - {len(config.token_sources)} 个 token 源")
            else:
                print(f"ERROR: {provider} - 缺少配置")
                return False
        
        # 测试创建
        try:
            extractor = ImprovedTokenExtractor('kimi')
            print("OK: 改进版 TokenExtractor 创建成功")
        except Exception as e:
            print(f"ERROR: 创建失败 - {e}")
            return False
        
        return True
        
    except Exception as e:
        print(f"ERROR: 导入失败 - {e}")
        return False

def main():
    """主函数"""
    if not check_files():
        print("\nERROR: 文件检查失败")
        sys.exit(1)
    
    if not check_improved_login():
        print("\nERROR: 改进版登录器检查失败")
        sys.exit(1)
    
    print("\nSUCCESS: 所有检查通过！")
    print("\nNEXT STEPS:")
    print("1. 运行 python test_improved_login.py 验证功能")
    print("2. 查看 MIGRATION_GUIDE.md 了解集成步骤")
    print("3. 按照 MIGRATION_GUIDE.md 逐步集成")

if __name__ == "__main__":
    main()