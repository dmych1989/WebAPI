#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版自动提取功能测试脚本
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent / "src"))

def test_config():
    """测试配置"""
    try:
        from src.login.auto_extract_configs import get_supported_providers, get_provider_info
        
        print("测试配置...")
        providers = get_supported_providers()
        print(f"支持的Provider数量: {len(providers)}")
        print(f"支持的Provider列表: {', '.join(providers)}")
        
        for provider in providers:
            info = get_provider_info(provider)
            print(f"{provider}: {info['name']}")
        
        return True
    except Exception as e:
        print(f"配置测试失败: {e}")
        return False

def test_imports():
    """测试导入"""
    try:
        print("测试导入...")
        from src.login.auto_extract_manager import AutoExtractManager
        from src.login.auto_extract import AutoExtractor
        from src.login.enhanced_token_extractor import EnhancedTokenExtractor
        print("所有导入成功")
        return True
    except Exception as e:
        print(f"导入测试失败: {e}")
        return False

def main():
    """主函数"""
    print("WebAPI 自动提取功能测试")
    print("=" * 60)
    
    tests = [
        ("导入测试", test_imports),
        ("配置测试", test_config),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n测试: {test_name}")
        print("-" * 40)
        
        try:
            result = test_func()
            results.append((test_name, result))
            status = "通过" if result else "失败"
            print(f"结果: {status}")
        except Exception as e:
            print(f"异常: {e}")
            results.append((test_name, False))
        
        print("=" * 60)
    
    # 汇总结果
    print("\n测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "通过" if result else "失败"
        print(f"  {test_name}: {status}")
    
    print(f"\n总体结果: {passed}/{total} 测试通过")
    
    if passed == total:
        print("所有测试通过!")
        return 0
    else:
        print("部分测试失败，请检查配置。")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)