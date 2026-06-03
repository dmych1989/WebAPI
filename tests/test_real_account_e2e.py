"""
Real Account E2E API Test for WebAPI

这个测试使用真实的账号凭证进行端到端测试，验证所有提供商在实际环境下的表现。
"""

import asyncio
import json
import logging
import sys
import time
from typing import Dict, Any, List

import httpx
from src.core.exceptions import ProviderError, RateLimitError

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RealAccountE2ETester:
    """真实账号 E2E 测试器"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: int = 60):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"}
        )
        self.results = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": [],
            "provider_results": {}
        }
        
        # 测试配置
        self.test_messages = [
            {"role": "user", "content": "你好，请用一句话介绍你自己。"},
            {"role": "user", "content": "什么是人工智能？请简单解释一下。"},
            {"role": "user", "content": "请写一个Python函数来计算斐波那契数列。"}
        ]
        
        # 流式测试消息
        self.streaming_message = {
            "role": "user", 
            "content": "请详细解释一下机器学习的基本概念，要求分点说明。"
        }

    async def setup(self):
        """测试前准备"""
        logger.info("🚀 开始真实账号 E2E 测试...")
        logger.info(f"📡 测试服务器: {self.base_url}")
        logger.info(f"⏱️  超时设置: {self.timeout}秒")
        
        # 检查服务状态
        try:
            response = await self.client.get("/health")
            if response.status_code == 200:
                health_data = response.json()
                logger.info(f"✅ 服务状态健康 | 提供商数量: {len(health_data.get('providers', []))}")
                logger.info(f"📊 提供商列表: {list(health_data.get('providers', {}).keys())}")
            else:
                logger.error(f"❌ 服务状态异常: {response.status_code}")
                raise Exception(f"服务状态异常: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ 无法连接到服务: {e}")
            raise

    async def teardown(self):
        """测试后清理"""
        await self.client.aclose()
        
        # 输出测试结果
        logger.info("\n" + "="*60)
        logger.info("📊 测试结果汇总")
        logger.info("="*60)
        logger.info(f"📝 总测试数: {self.results['total_tests']}")
        logger.info(f"✅ 通过数: {self.results['passed']}")
        logger.info(f"❌ 失败数: {self.results['failed']}")
        logger.info(f"📊 成功率: {self.results['passed']/self.results['total_tests']*100:.1f}%")
        
        if self.results['errors']:
            logger.error(f"❌ 错误详情:")
            for error in self.results['errors']:
                logger.error(f"   - {error}")
        
        # 各提供商测试结果
        logger.info("\n🏢 各提供商测试结果:")
        for provider, result in self.results['provider_results'].items():
            status = "✅" if result['passed'] > 0 else "❌"
            logger.info(f"   {status} {provider}: {result['passed']}/{result['total']} 测试通过")

    async def test_provider_basic_chat(self, provider_name: str, model_name: str) -> bool:
        """测试提供商基本聊天功能"""
        test_name = f"{provider_name}_{model_name}_basic_chat"
        
        try:
            logger.info(f"🧪 测试: {test_name}")
            self.results['total_tests'] += 1
            
            payload = {
                "model": model_name,
                "messages": self.test_messages[0:1],  # 只用第一条消息进行测试
                "temperature": 0.7,
                "max_tokens": 500
            }
            
            start_time = time.time()
            response = await self.client.post("/v1/chat/completions", json=payload)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                
                # 验证响应结构
                if 'choices' not in result or len(result['choices']) == 0:
                    error_msg = f"{test_name}: 响应缺少 choices 字段"
                    logger.error(f"❌ {error_msg}")
                    self.results['errors'].append(error_msg)
                    self.results['failed'] += 1
                    return False
                
                choice = result['choices'][0]
                if 'message' not in choice or 'content' not in choice['message']:
                    error_msg = f"{test_name}: 响应缺少 message.content 字段"
                    logger.error(f"❌ {error_msg}")
                    self.results['errors'].append(error_msg)
                    self.results['failed'] += 1
                    return False
                
                content = choice['message']['content']
                if not content.strip():
                    error_msg = f"{test_name}: 响应内容为空"
                    logger.error(f"❌ {error_msg}")
                    self.results['errors'].append(error_msg)
                    self.results['failed'] += 1
                    return False
                
                # 验证使用情况统计
                if 'usage' not in result:
                    logger.warning(f"⚠️ {test_name}: 响应缺少 usage 字段")
                else:
                    usage = result['usage']
                    logger.info(f"📊 Token 使用: {usage.get('total_tokens', 0)} | 耗时: {duration:.2f}s")
                
                logger.info(f"✅ {test_name}: 成功 | 内容长度: {len(content)}")
                self.results['passed'] += 1
                return True
                
            elif response.status_code == 429:
                error_msg = f"{test_name}: 速率限制 ({response.status_code})"
                logger.error(f"❌ {error_msg}")
                self.results['errors'].append(error_msg)
                self.results['failed'] += 1
                return False
                
            elif response.status_code == 503:
                error_msg = f"{test_name}: 服务不可用 ({response.status_code})"
                logger.error(f"❌ {error_msg}")
                self.results['errors'].append(error_msg)
                self.results['failed'] += 1
                return False
                
            else:
                error_msg = f"{test_name}: HTTP {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                self.results['errors'].append(error_msg)
                self.results['failed'] += 1
                return False
                
        except Exception as e:
            error_msg = f"{test_name}: 异常 - {str(e)}"
            logger.error(f"❌ {error_msg}")
            self.results['errors'].append(error_msg)
            self.results['failed'] += 1
            return False

    async def test_provider_streaming_chat(self, provider_name: str, model_name: str) -> bool:
        """测试提供商流式聊天功能"""
        test_name = f"{provider_name}_{model_name}_streaming_chat"
        
        try:
            logger.info(f"🌊 测试: {test_name}")
            self.results['total_tests'] += 1
            
            payload = {
                "model": model_name,
                "messages": [self.streaming_message],
                "temperature": 0.7,
                "max_tokens": 1000,
                "stream": True
            }
            
            start_time = time.time()
            response = await self.client.post("/v1/chat/completions", json=payload)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                content_received = ""
                chunk_count = 0
                
                # 处理流式响应
                async for line in response.aiter_lines():
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            if 'choices' in data and len(data['choices']) > 0:
                                delta = data['choices'][0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    content_received += content
                                    chunk_count += 1
                        except json.JSONDecodeError:
                            pass
                
                if not content_received.strip():
                    error_msg = f"{test_name}: 流式响应内容为空"
                    logger.error(f"❌ {error_msg}")
                    self.results['errors'].append(error_msg)
                    self.results['failed'] += 1
                    return False
                
                logger.info(f"✅ {test_name}: 成功 | 内容长度: {len(content_received)} | 块数: {chunk_count} | 耗时: {duration:.2f}s")
                self.results['passed'] += 1
                return True
                
            else:
                error_msg = f"{test_name}: HTTP {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                self.results['errors'].append(error_msg)
                self.results['failed'] += 1
                return False
                
        except Exception as e:
            error_msg = f"{test_name}: 异常 - {str(e)}"
            logger.error(f"❌ {error_msg}")
            self.results['errors'].append(error_msg)
            self.results['failed'] += 1
            return False

    async def test_provider_models(self, provider_name: str) -> bool:
        """测试提供商模型列表"""
        test_name = f"{provider_name}_models"
        
        try:
            logger.info(f"📋 测试: {test_name}")
            self.results['total_tests'] += 1
            
            response = await self.client.get("/v1/models")
            
            if response.status_code == 200:
                data = response.json()
                if 'data' not in data or len(data['data']) == 0:
                    error_msg = f"{test_name}: 模型列表为空"
                    logger.error(f"❌ {error_msg}")
                    self.results['errors'].append(error_msg)
                    self.results['failed'] += 1
                    return False
                
                models = [model['id'] for model in data['data']]
                logger.info(f"✅ {test_name}: 成功 | 模型数量: {len(models)}")
                logger.info(f"📝 模型列表: {models}")
                self.results['passed'] += 1
                return True
                
            else:
                error_msg = f"{test_name}: HTTP {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                self.results['errors'].append(error_msg)
                self.results['failed'] += 1
                return False
                
        except Exception as e:
            error_msg = f"{test_name}: 异常 - {str(e)}"
            logger.error(f"❌ {error_msg}")
            self.results['errors'].append(error_msg)
            self.results['failed'] += 1
            return False

    async def test_provider_health(self, provider_name: str) -> bool:
        """测试提供商健康状态"""
        test_name = f"{provider_name}_health"
        
        try:
            logger.info(f"🏥 测试: {test_name}")
            self.results['total_tests'] += 1
            
            response = await self.client.get("/admin/providers")
            
            if response.status_code == 200:
                data = response.json()
                if provider_name not in data.get('registered', []):
                    error_msg = f"{test_name}: 提供商未注册"
                    logger.error(f"❌ {error_msg}")
                    self.results['errors'].append(error_msg)
                    self.results['failed'] += 1
                    return False
                
                logger.info(f"✅ {test_name}: 成功 | 提供商已注册")
                self.results['passed'] += 1
                return True
                
            else:
                error_msg = f"{test_name}: HTTP {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                self.results['errors'].append(error_msg)
                self.results['failed'] += 1
                return False
                
        except Exception as e:
            error_msg = f"{test_name}: 异常 - {str(e)}"
            logger.error(f"❌ {error_msg}")
            self.results['errors'].append(error_msg)
            self.results['failed'] += 1
            return False

    async def test_provider_comprehensive(self, provider_name: str, model_name: str) -> Dict[str, Any]:
        """对单个提供商进行综合测试"""
        logger.info(f"\n🔬 开始对 {provider_name} 进行综合测试...")
        
        provider_results = {
            "provider": provider_name,
            "model": model_name,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "tests": {}
        }
        
        # 基本聊天测试
        basic_result = await self.test_provider_basic_chat(provider_name, model_name)
        provider_results["total"] += 1
        provider_results["tests"]["basic_chat"] = basic_result
        if basic_result:
            provider_results["passed"] += 1
        else:
            provider_results["failed"] += 1
        
        # 流式聊天测试
        streaming_result = await self.test_provider_streaming_chat(provider_name, model_name)
        provider_results["total"] += 1
        provider_results["tests"]["streaming_chat"] = streaming_result
        if streaming_result:
            provider_results["passed"] += 1
        else:
            provider_results["failed"] += 1
        
        # 模型列表测试
        models_result = await self.test_provider_models(provider_name)
        provider_results["total"] += 1
        provider_results["tests"]["models"] = models_result
        if models_result:
            provider_results["passed"] += 1
        else:
            provider_results["failed"] += 1
        
        # 健康状态测试
        health_result = await self.test_provider_health(provider_name)
        provider_results["total"] += 1
        provider_results["tests"]["health"] = health_result
        if health_result:
            provider_results["passed"] += 1
        else:
            provider_results["failed"] += 1
        
        # 更新总体结果
        self.results['provider_results'][provider_name] = provider_results
        
        # 输出提供商测试结果
        status = "✅" if provider_results["passed"] > 0 else "❌"
        logger.info(f"\n{status} {provider_name} 测试完成: {provider_results['passed']}/{provider_results['total']} 通过")
        
        return provider_results

    async def run_all_tests(self):
        """运行所有测试"""
        enabled_providers = {
            "deepseek": "deepseek-chat",
            "kimi": "Kimi-K2.6",
            "doubao": "doubao-pro-32k",
            "yuanbao": "hunyuan-pro"
        }
        
        # 对每个启用的提供商进行测试
        for provider_name, model_name in enabled_providers.items():
            try:
                await self.test_provider_comprehensive(provider_name, model_name)
                
                # 在提供商之间添加延迟，避免速率限制
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"❌ 测试 {provider_name} 时发生异常: {e}")
                self.results['errors'].append(f"{provider_name}: {str(e)}")
                self.results['failed'] += 1
                self.results['total'] += 1
        
        # 输出最终结果
        await self.teardown()
        
        # 判断测试是否通过
        success_rate = self.results['passed'] / self.results['total_tests'] if self.results['total_tests'] > 0 else 0
        if success_rate >= 0.8:  # 80% 成功率视为通过
            logger.info(f"\n🎉 总体测试通过! 成功率: {success_rate*100:.1f}%")
            return True
        else:
            logger.error(f"\n💥 总体测试失败! 成功率: {success_rate*100:.1f}%")
            return False


async def main():
    """主函数"""
    tester = RealAccountE2ETester()
    
    try:
        await tester.setup()
        success = await tester.run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ 测试运行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())