"""
LLM 集成的上下文摘要器

使用真实的 LLM 调用进行上下文摘要，替代原有的模拟摘要功能。
支持多种提供商和摘要策略。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Union

from src.core.logger import logger
from src.core.exceptions import ProviderError, RateLimitError
from src.provider.registry import get_provider, model_mapper, ProviderRegistry
from src.provider.base import BaseProvider

# 确保所有 Provider 都被注册
import src.provider.registration


class LLMContextSummarizer:
    """LLM 集成的上下文摘要器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_name = config.get('provider', 'deepseek')
        self.model_name = config.get('model', 'deepseek-chat')
        self.max_summary_length = config.get('max_summary_length', 1000)
        self.max_context_length = config.get('max_context_length', 8000)
        self.summary_prompt = config.get('summary_prompt', self._get_default_summary_prompt())
        self.temperature = config.get('temperature', 0.3)
        self.max_retries = config.get('max_retries', 3)
        
        # 缓存
        self.summary_cache: Dict[str, str] = {}
        self.cache_ttl = config.get('cache_ttl', 3600)  # 1小时
        
        # 获取提供商
        self.provider = None
        
    async def initialize(self):
        """初始化摘要器"""
        try:
            # 获取模型映射
            provider_type, actual_model = model_mapper.map(self.model_name)
            # 如果提供商被禁用，使用默认的 deepseek
            if provider_type == 'qwen' and not self._is_provider_enabled(provider_type):
                provider_type = 'deepseek'
            # 使用 get_provider 函数获取 provider 实例
            self.provider = get_provider(provider_type)
            
            logger.info(f"[LLMSummarizer] 初始化完成 - 提供商: {provider_type}, 模型: {actual_model}")
            
        except Exception as e:
            logger.error(f"[LLMSummarizer] 初始化失败: {e}")
            raise ProviderError(f"LLM 摘要器初始化失败: {e}")
    
    def _is_provider_enabled(self, provider_name: str) -> bool:
        """检查提供商是否启用"""
        try:
            from src.core.config import get_config
            config = get_config()
            provider_config = config.providers.get(provider_name)
            return provider_config and provider_config.enabled
        except:
            return False
    
    def _get_default_summary_prompt(self) -> str:
        """获取默认的摘要提示词"""
        return """你是一个专业的文本摘要助手。请对以下对话内容进行简洁的摘要，保留重要信息。

要求：
1. 摘要长度控制在 {max_length} 字符以内
2. 保留关键信息和上下文
3. 语言简洁明了
4. 保持对话的逻辑连贯性

对话内容：
{messages}

摘要："""
    
    def _get_cache_key(self, messages: List[Dict[str, str]]) -> str:
        """生成缓存键"""
        # 简单的消息哈希
        message_str = json.dumps(messages, sort_keys=True)
        import hashlib
        return hashlib.md5(message_str.encode()).hexdigest()
    
    def _is_cache_valid(self, timestamp: float) -> bool:
        """检查缓存是否有效"""
        return time.time() - timestamp < self.cache_ttl
    
    async def _generate_summary(self, messages: List[Dict[str, str]]) -> str:
        """生成摘要"""
        if not self.provider:
            await self.initialize()
        
        # 构建摘要提示
        summary_prompt = self.summary_prompt.format(
            max_length=self.max_summary_length,
            messages=self._format_messages_for_summary(messages)
        )
        
        # 发送摘要请求
        try:
            response = await self.provider.chat_completion(
                [{"role": "user", "content": summary_prompt}],
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_summary_length
            )
            
            summary = response['choices'][0]['message']['content'].strip()
            logger.info(f"[LLMSummarizer] 生成摘要成功，长度: {len(summary)}")
            return summary
            
        except Exception as e:
            logger.error(f"[LLMSummarizer] 生成摘要失败: {e}")
            raise ProviderError(f"LLM 摘要生成失败: {e}")
    
    def _format_messages_for_summary(self, messages: List[Dict[str, str]]) -> str:
        """格式化消息用于摘要"""
        formatted_messages = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            formatted_messages.append(f"{role}: {content}")
        
        return '\n'.join(formatted_messages)
    
    async def summarize_messages(
        self, 
        messages: List[Dict[str, str]], 
        force_refresh: bool = False
    ) -> str:
        """
        摘要消息列表
        
        Args:
            messages: 要摘要的消息列表
            force_refresh: 是否强制刷新缓存
            
        Returns:
            摘要文本
        """
        cache_key = self._get_cache_key(messages)
        
        # 检查缓存
        if not force_refresh and cache_key in self.summary_cache:
            cache_data = self.summary_cache[cache_key]
            if isinstance(cache_data, dict) and self._is_cache_valid(cache_data['timestamp']):
                logger.info(f"[LLMSummarizer] 使用缓存摘要")
                return cache_data['summary']
        
        # 生成新摘要
        logger.info(f"[LLMSummarizer] 生成新摘要，消息数: {len(messages)}")
        
        # 如果消息太多，先进行分段摘要
        if len(messages) > 20:
            summary = await self._summarize_large_messages(messages)
        else:
            summary = await self._generate_summary(messages)
        
        # 更新缓存
        self.summary_cache[cache_key] = {
            'summary': summary,
            'timestamp': time.time()
        }
        
        return summary
    
    async def _summarize_large_messages(self, messages: List[Dict[str, str]]) -> str:
        """处理大量消息的摘要"""
        logger.info(f"[LLMSummarizer] 处理大量消息，分段摘要")
        
        # 分段处理
        chunk_size = 10
        chunks = []
        
        for i in range(0, len(messages), chunk_size):
            chunk = messages[i:i + chunk_size]
            chunk_summary = await self._generate_summary(chunk)
            chunks.append(chunk_summary)
        
        # 对摘要进行最终摘要
        final_summary = await self._generate_summary([
            {"role": "system", "content": "以下是对话的多个摘要片段，请将它们合并成一个连贯的摘要："},
            {"role": "user", "content": '\n\n'.join(chunks)}
        ])
        
        return final_summary
    
    async def summarize_conversation(
        self, 
        conversation_id: str, 
        messages: List[Dict[str, str]],
        max_tokens: int = 128000
    ) -> str:
        """
        摘要整个对话
        
        Args:
            conversation_id: 对话 ID
            messages: 对话消息列表
            max_tokens: 最大 token 数量
            
        Returns:
            对话摘要
        """
        logger.info(f"[LLMSummarizer] 摘要对话: {conversation_id}")
        
        # 检查消息长度
        total_tokens = sum(len(msg.get('content', '')) for msg in messages) // 4
        
        if total_tokens <= max_tokens:
            # 直接摘要
            return await self.summarize_messages(messages)
        else:
            # 需要截断或分段处理
            logger.info(f"[LLMSummarizer] 对话过长，进行分段处理")
            return await self._summarize_large_messages(messages)
    
    async def get_summary_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return {
            'cache_size': len(self.summary_cache),
            'cache_ttl': self.cache_ttl,
            'providers_used': [self.provider_name],
            'model_used': self.model_name
        }
    
    async def clear_cache(self):
        """清除缓存"""
        self.summary_cache.clear()
        logger.info("[LLMSummarizer] 缓存已清除")
    
    async def close(self):
        """关闭摘要器"""
        if self.provider:
            await self.provider.close()
        logger.info("[LLMSummarizer] 摘要器已关闭")


class ContextSummarizationManager:
    """上下文摘要管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.summarizers: Dict[str, LLMContextSummarizer] = {}
        self.default_summarizer = None
        
    async def initialize(self):
        """初始化摘要管理器"""
        # 创建默认摘要器
        self.default_summarizer = LLMContextSummarizer(self.config)
        await self.default_summarizer.initialize()
        
        # 创建特定策略的摘要器
        for strategy_name, strategy_config in self.config.get('strategies', {}).items():
            summarizer = LLMContextSummarizer(strategy_config)
            await summarizer.initialize()
            self.summarizers[strategy_name] = summarizer
        
        logger.info("[ContextSummarizationManager] 初始化完成")
    
    async def get_summarizer(self, strategy: str = "default") -> LLMContextSummarizer:
        """获取指定策略的摘要器"""
        if strategy == "default":
            return self.default_summarizer
        else:
            return self.summarizers.get(strategy)
    
    async def summarize(
        self,
        messages: List[Dict[str, str]],
        strategy: str = "default",
        force_refresh: bool = False
    ) -> str:
        """
        摘要消息
        
        Args:
            messages: 要摘要的消息列表
            strategy: 摘要策略
            force_refresh: 是否强制刷新缓存
            
        Returns:
            摘要文本
        """
        summarizer = await self.get_summarizer(strategy)
        if not summarizer:
            raise ProviderError(f"未找到摘要策略: {strategy}")
        
        return await summarizer.summarize_messages(messages, force_refresh)
    
    async def get_cache_info(self) -> Dict[str, Any]:
        """获取所有摘要器的缓存信息"""
        cache_info = {}
        
        if self.default_summarizer:
            cache_info['default'] = await self.default_summarizer.get_summary_cache_info()
        
        for strategy_name, summarizer in self.summarizers.items():
            cache_info[strategy_name] = await summarizer.get_summary_cache_info()
        
        return cache_info
    
    async def clear_all_cache(self):
        """清除所有缓存"""
        if self.default_summarizer:
            await self.default_summarizer.clear_cache()
        
        for summarizer in self.summarizers.values():
            await summarizer.clear_cache()
        
        logger.info("[ContextSummarizationManager] 所有缓存已清除")
    
    async def close(self):
        """关闭摘要管理器"""
        if self.default_summarizer:
            await self.default_summarizer.close()
        
        for summarizer in self.summarizers.values():
            await summarizer.close()
        
        logger.info("[ContextSummarizationManager] 摘要管理器已关闭")


# 全局摘要管理器实例
_summarization_manager: Optional[ContextSummarizationManager] = None


async def get_summarization_manager() -> ContextSummarizationManager:
    """获取全局摘要管理器"""
    global _summarization_manager
    
    if _summarization_manager is None:
        config = {
            'provider': 'deepseek',
            'model': 'deepseek-chat',
            'max_summary_length': 1000,
            'max_context_length': 8000,
            'temperature': 0.3,
            'max_retries': 3,
            'cache_ttl': 3600,
            'summary_prompt': """你是一个专业的文本摘要助手。请对以下对话内容进行简洁的摘要，保留重要信息。

要求：
1. 摘要长度控制在 {max_length} 字符以内
2. 保留关键信息和上下文
3. 语言简洁明了
4. 保持对话的逻辑连贯性

对话内容：
{messages}

摘要：""",
            'strategies': {
                'detailed': {
                    'provider': 'qwen',
                    'model': 'qwen-max',
                    'max_summary_length': 1500,
                    'temperature': 0.5
                },
                'concise': {
                    'provider': 'deepseek',
                    'model': 'deepseek-chat',
                    'max_summary_length': 500,
                    'temperature': 0.2
                }
            }
        }
        
        _summarization_manager = ContextSummarizationManager(config)
        await _summarization_manager.initialize()
    
    return _summarization_manager


async def summarize_messages(
    messages: List[Dict[str, str]],
    strategy: str = "default",
    force_refresh: bool = False
) -> str:
    """
    便捷函数：摘要消息
    
    Args:
        messages: 要摘要的消息列表
        strategy: 摘要策略
        force_refresh: 是否强制刷新缓存
        
    Returns:
        摘要文本
    """
    manager = await get_summarization_manager()
    return await manager.summarize(messages, strategy, force_refresh)