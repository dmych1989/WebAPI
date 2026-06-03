#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的 WebAPI 登录模块集成检查
"""

import sys
import os

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

def check_improved_login_syntax():
    """检查改进版登录器语法"""
    print("\n检查改进版登录器语法...")
    
    try:
        # 尝试编译文件
        with open("src/login/improved_login.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        compile(code, "src/login/improved_login.py", "exec")
        print("OK: 改进版登录器语法正确")
        
        # 检查关键类
        if "class ImprovedTokenExtractor" in code:
            print("OK: ImprovedTokenExtractor 类存在")
        else:
            print("ERROR: ImprovedTokenExtractor 类不存在")
            return False
        
        if "class TokenMonitor" in code:
            print("OK: TokenMonitor 类存在")
        else:
            print("ERROR: TokenMonitor 类不存在")
            return False
        
        if "TOKEN_EXTRACTION_CONFIGS" in code:
            print("OK: TOKEN_EXTRACTION_CONFIGS 存在")
        else:
            print("ERROR: TOKEN_EXTRACTION_CONFIGS 不存在")
            return False
        
        return True
        
    except SyntaxError as e:
        print(f"ERROR: 语法错误 - {e}")
        return False
    except Exception as e:
        print(f"ERROR: 检查失败 - {e}")
        return False

def check_test_file():
    """检查测试文件"""
    print("\n检查测试文件...")
    
    try:
        with open("test_improved_login.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        compile(code, "test_improved_login.py", "exec")
        print("OK: 测试文件语法正确")
        
        return True
        
    except SyntaxError as e:
        print(f"ERROR: 测试文件语法错误 - {e}")
        return False
    except Exception as e:
        print(f"ERROR: 测试文件检查失败 - {e}")
        return False

def main():
    """主函数"""
    if not check_files():
        print("\nERROR: 文件检查失败")
        sys.exit(1)
    
    if not check_improved_login_syntax():
        print("\nERROR: 改进版登录器检查失败")
        sys.exit(1)
    
    if not check_test_file():
        print("\nERROR: 测试文件检查失败")
        sys.exit(1)
    
    print("\nSUCCESS: 所有检查通过！")
    print("\nNEXT STEPS:")
    print("1. 运行 python test_improved_login.py 验证功能")
    print("2. 查看 MIGRATION_GUIDE.md 了解集成步骤")
    print("3. 按照 MIGRATION_GUIDE.md 逐步集成")

if __name__ == "__main__":
    main()