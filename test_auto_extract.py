#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动提取功能测试脚本

用于测试WebAPI的自动获取凭证功能。
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent / "src"))

from src.login.auto_extract_manager import AutoExtractManager
from src.login.auto_extract_configs import get_supported_providers, get_provider_info


async def test_provider_info():
    """测试Provider信息"""
    print("🔍 测试Provider信息...")
    print("=" * 60)
    
    providers = get_supported_providers()
    print(f"支持的Provider数量: {len(providers)}")
    print(f"支持的Provider列表: {', '.join(providers)}")
    print()
    
    for provider in providers:
        info = get_provider_info(provider)
        print(f"📋 {provider}:")
        print(f"  名称: {info['name']}")
        print(f"  登录URL: {info['login_url']}")
        print(f"  认证类型: {info['auth_type']}")
        print(f"  提取方法: {', '.join(info['extraction_methods'])}")
        print()


async def test_single_provider():
    """测试单个Provider提取"""
    provider = "kimi"  # 使用kimi作为测试Provider
    
    print(f"🧪 测试单个Provider提取: {provider}")
    print("=" * 60)
    
    manager = AutoExtractManager()
    
    try:
        # 测试凭证提取
        print("📤 开始提取凭证...")
        credentials = await manager.auto_extract_credentials(provider, headless=True)
        
        if credentials:
            print("✅ 提取成功!")
            print("📋 提取到的凭证:")
            for key, value in credentials.items():
                display_value = value[:30] + "..." if len(value) > 30 else value
                print(f"  {key}: {display_value}")
            
            # 测试凭证验证
            print("\n🔍 验证提取的凭证...")
            is_valid = await manager.validate_extracted_credentials(provider, credentials)
            print(f"验证结果: {'✅ 通过' if is_valid else '❌ 失败'}")
            
            return True
        else:
            print("❌ 提取失败!")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_batch_extract():
    """测试批量提取"""
    print("🧪 测试批量提取...")
    print("=" * 60)
    
    manager = AutoExtractManager()
    
    # 选择3个Provider进行测试
    test_providers = ["kimi", "deepseek", "glm"]
    
    try:
        print(f"📋 将测试以下Provider: {', '.join(test_providers)}")
        print("📤 开始批量提取...")
        
        results = await manager.batch_auto_extract(test_providers, headless=True)
        
        print("📊 批量提取结果:")
        success_count = 0
        for provider, success in results.items():
            status = "✅ 成功" if success else "❌ 失败"
            print(f"  {provider}: {status}")
            if success:
                success_count += 1
        
        print(f"\n📈 成功率: {success_count}/{len(test_providers)} ({success_count/len(test_providers)*100:.1f}%)")
        
        return success_count > 0
        
    except Exception as e:
        print(f"❌ 批量测试失败: {e}")
        return False


async def test_config_validation():
    """测试配置验证"""
    print("🔍 测试配置验证...")
    print("=" * 60)
    
    from src.login.auto_extract_configs import validate_all_configs
    
    results = validate_all_configs()
    
    print(f"📊 配置验证结果:")
    print(f"  总配置数: {results['total']}")
    print(f"  有效配置: {results['valid']}")
    print(f"  无效配置: {results['invalid']}")
    
    if results['errors']:
        print("❌ 错误信息:")
        for error in results['errors']:
            print(f"  - {error}")
    
    success = results['invalid'] == 0
    print(f"验证状态: {'✅ 通过' if success else '❌ 失败'}")
    
    return success


async def test_error_handling():
    """测试错误处理"""
    print("🔍 测试错误处理...")
    print("=" * 60)
    
    manager = AutoExtractManager()
    
    # 测试不存在的Provider
    try:
        print("📤 测试不存在的Provider...")
        credentials = await manager.auto_extract_credentials("nonexistent_provider", headless=True)
        print(f"结果: {credentials}")
        return False  # 应该抛出异常
    except ValueError as e:
        print(f"✅ 正确捕获异常: {e}")
        return True
    except Exception as e:
        print(f"❌ 意外异常: {e}")
        return False


async def main():
    """主函数"""
    print("🚀 WebAPI 自动提取功能测试")
    print("=" * 60)
    
    tests = [
        ("Provider信息测试", test_provider_info),
        ("配置验证测试", test_config_validation),
        ("错误处理测试", test_error_handling),
        ("单个Provider提取测试", test_single_provider),
        ("批量提取测试", test_batch_extract),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🧪 {test_name}")
        print("-" * 40)
        
        try:
            result = await test_func()
            results.append((test_name, result))
            status = "✅ 通过" if result else "❌ 失败"
            print(f"\n{test_name}: {status}")
        except Exception as e:
            print(f"\n{test_name}: ❌ 异常 - {e}")
            results.append((test_name, False))
        
        print("=" * 60)
    
    # 汇总结果
    print("\n📊 测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {test_name}: {status}")
    
    print(f"\n📈 总体结果: {passed}/{total} 测试通过 ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 所有测试通过! 自动提取功能正常工作。")
        return 0
    else:
        print("⚠️  部分测试失败，请检查配置和网络连接。")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)