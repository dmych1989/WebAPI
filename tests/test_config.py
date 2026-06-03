"""
测试配置管理器

管理不同环境的测试配置，包括真实账号、测试数据等。
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class TestAccount:
    """测试账号配置"""
    provider: str
    name: str
    enabled: bool = True
    models: List[str] = None
    max_concurrent: int = 5
    health_check_interval: int = 60
    credentials: Dict[str, str] = None
    
    def __post_init__(self):
        if self.models is None:
            self.models = []
        if self.credentials is None:
            self.credentials = {}


class TestConfigManager:
    """测试配置管理器"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.test_accounts = self._load_test_accounts()
        
    def _load_config(self) -> Dict[str, Any]:
        """加载主配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件未找到: {self.config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"配置文件格式错误: {e}")
    
    def _load_test_accounts(self) -> Dict[str, TestAccount]:
        """加载测试账号配置"""
        accounts = {}
        
        providers_config = self.config.get('providers', {})
        
        for provider_name, provider_config in providers_config.items():
            if not provider_config.get('enabled', False):
                continue
                
            accounts_config = provider_config.get('accounts', [])
            for account_config in accounts_config:
                account = TestAccount(
                    provider=provider_name,
                    name=account_config.get('name', 'account-1'),
                    enabled=account_config.get('enabled', True),
                    models=account_config.get('models', []),
                    max_concurrent=account_config.get('max_concurrent', 5),
                    health_check_interval=account_config.get('health_check_interval', 60),
                    credentials=account_config.get('credentials', {})
                )
                accounts[f"{provider_name}_{account.name}"] = account
        
        return accounts
    
    def get_enabled_providers(self) -> List[str]:
        """获取启用的提供商列表"""
        return [
            provider for provider, config in self.config.get('providers', {}).items()
            if config.get('enabled', False)
        ]
    
    def get_provider_models(self, provider_name: str) -> List[str]:
        """获取提供商的模型列表"""
        provider_config = self.config.get('providers', {}).get(provider_name, {})
        if not provider_config.get('enabled', False):
            return []
        
        accounts = provider_config.get('accounts', [])
        models = []
        for account in accounts:
            account_models = account.get('models', [])
            models.extend(account_models)
        
        return list(set(models))  # 去重
    
    def get_test_scenarios(self) -> Dict[str, Any]:
        """获取测试场景配置"""
        return {
            "basic_chat": {
                "description": "基本聊天功能测试",
                "messages": [
                    {"role": "user", "content": "你好，请用一句话介绍你自己。"},
                    {"role": "user", "content": "什么是人工智能？请简单解释一下。"}
                ],
                "temperature": 0.7,
                "max_tokens": 500
            },
            "detailed_explanation": {
                "description": "详细解释测试",
                "messages": [
                    {"role": "user", "content": "请详细解释一下机器学习的基本概念，要求分点说明。"}
                ],
                "temperature": 0.7,
                "max_tokens": 1000
            },
            "code_generation": {
                "description": "代码生成测试",
                "messages": [
                    {"role": "user", "content": "请写一个Python函数来计算斐波那契数列，要求包含详细的注释。"}
                ],
                "temperature": 0.3,
                "max_tokens": 800
            },
            "creative_writing": {
                "description": "创意写作测试",
                "messages": [
                    {"role": "user", "content": "请写一个关于人工智能的科幻短篇故事，不少于500字。"}
                ],
                "temperature": 0.9,
                "max_tokens": 1200
            }
        }
    
    def get_test_timeout(self) -> int:
        """获取测试超时时间"""
        return self.config.get('proxy', {}).get('timeout', 60)
    
    def get_retry_config(self) -> Dict[str, int]:
        """获取重试配置"""
        proxy_config = self.config.get('proxy', {})
        return {
            'retry_count': proxy_config.get('retry_count', 3),
            'retry_delay': proxy_config.get('retry_delay', 5)
        }
    
    def get_rate_limit_config(self) -> Dict[str, Any]:
        """获取速率限制配置"""
        load_balance_config = self.config.get('load_balance', {})
        return {
            'rate_limit_cooldown': load_balance_config.get('rate_limit_cooldown', 60),
            'default_strategy': load_balance_config.get('default_strategy', 'round_robin')
        }
    
    def validate_config(self) -> List[str]:
        """验证配置有效性"""
        errors = []
        
        # 检查必需的配置项
        required_sections = ['providers', 'server']
        for section in required_sections:
            if section not in self.config:
                errors.append(f"缺少必需的配置节: {section}")
        
        # 检查提供商配置
        for provider_name, provider_config in self.config.get('providers', {}).items():
            if provider_config.get('enabled', False):
                if 'accounts' not in provider_config or not provider_config['accounts']:
                    errors.append(f"启用的提供商 {provider_name} 没有配置账号")
                
                for account in provider_config.get('accounts', []):
                    if not account.get('models'):
                        errors.append(f"提供商 {provider_name} 的账号没有配置模型")
        
        return errors
    
    def get_env_overrides(self) -> Dict[str, str]:
        """获取环境变量覆盖配置"""
        env_overrides = {}
        
        # 从配置中读取环境变量引用
        for provider_name, provider_config in self.config.get('providers', {}).items():
            if 'api_key' in provider_config and provider_config['api_key'].startswith('${'):
                env_key = provider_config['api_key'][2:-1]  # 去掉 ${ 和 }
                env_value = os.getenv(env_key)
                if env_value:
                    env_overrides[env_key] = env_value
        
        return env_overrides
    
    def create_test_report(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建测试报告"""
        report = {
            'timestamp': results.get('timestamp'),
            'config_summary': {
                'total_providers': len(self.config.get('providers', {})),
                'enabled_providers': len(self.get_enabled_providers()),
                'total_accounts': len(self.test_accounts),
                'total_test_scenarios': len(self.get_test_scenarios())
            },
            'test_results': results,
            'config_validation': self.validate_config()
        }
        
        return report


# 全局配置管理器实例
test_config = TestConfigManager()


def get_test_config() -> TestConfigManager:
    """获取测试配置管理器实例"""
    return test_config


def get_enabled_providers() -> List[str]:
    """获取启用的提供商列表"""
    return test_config.get_enabled_providers()


def get_provider_models(provider_name: str) -> List[str]:
    """获取提供商的模型列表"""
    return test_config.get_provider_models(provider_name)