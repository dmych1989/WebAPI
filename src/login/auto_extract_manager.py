# -*- coding: utf-8 -*-
"""
自动获取凭证管理器 - 统一管理所有Provider的自动提取功能

提供完整的自动获取凭证解决方案，包括：
- 智能提取策略
- 多Provider支持
- 错误处理和重试
- 结果验证
- 配置管理
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import get_config, save_config, AccountConfig
from src.core.logger import logger
from src.login.enhanced_token_extractor import EnhancedTokenExtractor
from src.login.auto_extract import AutoExtractor


class AutoExtractManager:
    """自动提取管理器"""
    
    def __init__(self):
        self.extractors = {
            "kimi": EnhancedTokenExtractor,
            "deepseek": EnhancedTokenExtractor,
            "glm": EnhancedTokenExtractor,
            "qwen": EnhancedTokenExtractor,
            "minimax": EnhancedTokenExtractor,
            "yuanbao": EnhancedTokenExtractor,
            "doubao": EnhancedTokenExtractor,
            "mimo": EnhancedTokenExtractor,
        }
        self.auto_extractors = {
            "kimi": AutoExtractor,
            "deepseek": AutoExtractor,
            "glm": AutoExtractor,
            "qwen": AutoExtractor,
            "minimax": AutoExtractor,
            "yuanbao": AutoExtractor,
        }
    
    async def auto_extract_credentials(self, provider: str, headless: bool = False) -> Dict[str, str]:
        """自动提取凭证"""
        if provider not in self.extractors:
            raise ValueError(f"不支持的Provider: {provider}")
        
        print(f"\n{'='*60}")
        print(f"  开始自动提取 {provider} 凭证...")
        print(f"{'='*60}")
        
        try:
            # 使用增强版提取器
            extractor_class = self.extractors[provider]
            extractor = extractor_class(provider, headless=headless)
            credentials = await extractor.run()
            
            if credentials:
                print(f"\n  [✓] 成功提取到凭证:")
                for key, value in credentials.items():
                    display_value = value[:30] + "..." if len(value) > 30 else value
                    print(f"    {key}: {display_value}")
                
                return credentials
            else:
                print(f"\n  [✗] 未能提取到有效凭证")
                return {}
                
        except Exception as e:
            print(f"\n  [✗] 提取失败: {e}")
            logger.error(f"[AutoExtractManager] Error extracting {provider}: {e}")
            return {}
    
    async def auto_extract_and_save(self, provider: str, account_name: str = None, headless: bool = False) -> bool:
        """自动提取凭证并保存"""
        try:
            # 提取凭证
            credentials = await self.auto_extract_credentials(provider, headless)
            
            if not credentials:
                return False
            
            # 保存到配置
            config = get_config()
            
            if provider not in config.providers:
                from src.core.config import ProviderConfig
                config.providers[provider] = ProviderConfig()
            
            provider_config = config.providers[provider]
            
            # 确定账户名称
            if not account_name:
                account_name = f"account-{len(provider_config.accounts) + 1}"
            
            # 查找是否已存在同名账户
            existing_account = None
            for acc in provider_config.accounts:
                if acc.name == account_name:
                    existing_account = acc
                    break
            
            if existing_account:
                # 更新现有账户
                print(f"\n  [i] 更新现有账户: {account_name}")
                for key, value in credentials.items():
                    if hasattr(existing_account, key):
                        setattr(existing_account, key, value)
                existing_account.enabled = True
            else:
                # 创建新账户
                print(f"\n  [i] 创建新账户: {account_name}")
                new_account = AccountConfig(
                    name=account_name,
                    enabled=True,
                    **credentials
                )
                provider_config.accounts.append(new_account)
            
            # 保存配置
            save_config(config)
            
            print(f"\n  [✓] 凭证已保存到配置文件")
            print(f"  账户: {provider}/{account_name}")
            print(f"  请重启WebAPI服务以加载新配置")
            
            return True
            
        except Exception as e:
            print(f"\n  [✗] 保存失败: {e}")
            logger.error(f"[AutoExtractManager] Error saving credentials: {e}")
            return False
    
    async def batch_auto_extract(self, providers: List[str], headless: bool = False) -> Dict[str, bool]:
        """批量自动提取凭证"""
        results = {}
        
        for provider in providers:
            print(f"\n{'='*60}")
            print(f"  批量提取: {provider}")
            print(f"{'='*60}")
            
            success = await self.auto_extract_and_save(provider, headless=headless)
            results[provider] = success
        
        return results
    
    async def validate_extracted_credentials(self, provider: str, credentials: Dict[str, str]) -> bool:
        """验证提取的凭证"""
        try:
            from src.login.credential_manager import credential_manager
            
            # 创建临时账户配置
            from src.core.config import AccountConfig
            temp_account = AccountConfig(
                name="temp",
                enabled=True,
                **credentials
            )
            
            # 验证凭证
            result = await credential_manager.validate_account_credentials(provider, temp_account)
            
            if result.valid:
                print(f"  [✓] 凭证验证成功")
                return True
            else:
                print(f"  [✗] 凭证验证失败: {result.error}")
                return False
                
        except Exception as e:
            print(f"  [✗] 验证过程出错: {e}")
            return False
    
    def get_supported_providers(self) -> List[str]:
        """获取支持的Provider列表"""
        return list(self.extractors.keys())
    
    def get_provider_info(self, provider: str) -> Dict[str, Any]:
        """获取Provider信息"""
        info = {
            "name": provider,
            "supported": provider in self.extractors,
            "auto_extract": provider in self.auto_extractors,
            "extraction_methods": []
        }
        
        if provider in self.extractors:
            info["extraction_methods"].append("enhanced")
        
        if provider in self.auto_extractors:
            info["extraction_methods"].append("auto")
        
        return info


def main():
    """主函数"""
    import sys
    
    manager = AutoExtractManager()
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  python auto_extract_manager.py <provider> [account_name] [--headless]")
        print("  python auto_extract_manager.py batch [--headless]")
        print()
        print("支持的Provider:")
        for provider in manager.get_supported_providers():
            info = manager.get_provider_info(provider)
            methods = ", ".join(info["extraction_methods"])
            print(f"  {provider}: {methods}")
        sys.exit(1)
    
    headless = "--headless" in sys.argv
    
    if sys.argv[1] == "batch":
        # 批量提取
        providers = manager.get_supported_providers()
        print(f"将批量提取以下Provider的凭证:")
        for provider in providers:
            print(f"  - {provider}")
        
        results = asyncio.run(manager.batch_auto_extract(providers, headless))
        
        print(f"\n{'='*60}")
        print(f"  批量提取完成")
        print(f"{'='*60}")
        
        for provider, success in results.items():
            status = "✓ 成功" if success else "✗ 失败"
            print(f"  {provider}: {status}")
        
    else:
        # 单个Provider提取
        provider = sys.argv[1]
        account_name = sys.argv[2] if len(sys.argv) > 2 else None
        
        if provider not in manager.extractors:
            print(f"不支持的Provider: {provider}")
            sys.exit(1)
        
        success = asyncio.run(manager.auto_extract_and_save(provider, account_name, headless))
        
        if success:
            print(f"\n{'='*60}")
            print(f"  自动提取完成!")
            print(f"{'='*60}")
        else:
            print(f"\n{'='*60}")
            print(f"  自动提取失败!")
            print(f"{'='*60}")
            sys.exit(1)


if __name__ == "__main__":
    main()