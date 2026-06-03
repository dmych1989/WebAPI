"""
上下文管理器

集成了真实的 LLM 摘要功能，支持多种上下文管理策略。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Union

from src.core.logger import logger
from src.core.exceptions import ValidationError
from src.context.llm_summarizer import get_summarization_manager, summarize_messages
from src.provider.base import BaseProvider


class ContextMessage:
    """上下文消息"""
    
    def __init__(self, role: str, content: str, timestamp: float = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or time.time()
    
    def to_dict(self) -> Dict[str, str]:
        """转换为字典格式"""
        return {
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContextMessage':
        """从字典创建消息"""
        return cls(
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            timestamp=data.get('timestamp', time.time())
        )


class ContextManager:
    """上下文管理器"""
    
    def __init__(self, config):
        self.config = config
        self.enabled = config.enabled if hasattr(config, 'enabled') else False
        self.max_messages = config.max_messages if hasattr(config, 'max_messages') else 50
        self.max_tokens = config.max_tokens if hasattr(config, 'max_tokens') else 128000
        self.strategy = config.strategy if hasattr(config, 'strategy') else 'sliding_window'
        
        # 消息存储
        self.conversations: Dict[str, List[ContextMessage]] = {}
        self.conversation_metadata: Dict[str, Dict[str, Any]] = {}
        
        # 摘要配置
        self.summarize_enabled = getattr(config, 'summarize_enabled', True)
        self.summarize_threshold = getattr(config, 'summarize_threshold', 0.8)  # 当使用率达到80%时触发摘要
        self.summarize_strategy = getattr(config, 'summarize_strategy', 'default')
        
        # 统计信息
        self.stats = {
            'total_conversations': 0,
            'total_messages': 0,
            'total_summaries': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        logger.info(f"[ContextManager] 初始化完成 - 策略: {self.strategy}, 最大消息数: {self.max_messages}")
    
    async def initialize(self):
        """初始化上下文管理器"""
        if self.enabled:
            # 初始化摘要管理器
            await get_summarization_manager()
            logger.info("[ContextManager] 上下文管理器已启用")
        else:
            logger.info("[ContextManager] 上下文管理器已禁用")
    
    def get_conversation(self, conversation_id: str) -> List[ContextMessage]:
        """获取对话消息列表"""
        return self.conversations.get(conversation_id, [])
    
    def get_conversation_metadata(self, conversation_id: str) -> Dict[str, Any]:
        """获取对话元数据"""
        return self.conversation_metadata.get(conversation_id, {})
    
    async def add_message(
        self, 
        conversation_id: str, 
        role: str, 
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ContextMessage:
        """
        添加消息到对话
        
        Args:
            conversation_id: 对话 ID
            role: 消息角色
            content: 消息内容
            metadata: 消息元数据
            
        Returns:
            添加的消息对象
        """
        if not self.enabled:
            raise ValidationError("上下文管理器已禁用")
        
        # 创建消息对象
        message = ContextMessage(role, content)
        
        # 初始化对话（如果不存在）
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []
            self.conversation_metadata[conversation_id] = {
                'created_at': time.time(),
                'last_updated': time.time(),
                'message_count': 0,
                'total_tokens': 0,
                'summary': None,
                'last_summary_time': None
            }
            self.stats['total_conversations'] += 1
        
        # 添加消息
        self.conversations[conversation_id].append(message)
        
        # 更新元数据
        metadata = self.conversation_metadata[conversation_id]
        metadata['last_updated'] = time.time()
        metadata['message_count'] += 1
        metadata['total_tokens'] += len(content) // 4  # 简单的 token 估算
        
        # 更新统计
        self.stats['total_messages'] += 1
        
        # 检查是否需要触发摘要
        if self.summarize_enabled:
            await self._check_summarize_need(conversation_id)
        
        logger.info(f"[ContextManager] 添加消息 - 对话: {conversation_id}, 角色: {role}")
        return message
    
    async def _check_summarize_need(self, conversation_id: str):
        """检查是否需要触发摘要"""
        messages = self.get_conversation(conversation_id)
        metadata = self.get_conversation_metadata(conversation_id)
        
        # 计算当前使用率
        usage_rate = metadata['total_tokens'] / self.max_tokens
        
        if usage_rate >= self.summarize_threshold:
            logger.info(f"[ContextManager] 触发摘要 - 对话: {conversation_id}, 使用率: {usage_rate:.2f}")
            
            # 执行摘要
            await self._summarize_conversation(conversation_id)
    
    async def _summarize_conversation(self, conversation_id: str):
        """摘要对话"""
        messages = self.get_conversation(conversation_id)
        metadata = self.get_conversation_metadata(conversation_id)
        
        try:
            # 生成摘要
            summary = await summarize_messages(
                [msg.to_dict() for msg in messages],
                strategy=self.summarize_strategy
            )
            
            # 更新元数据
            metadata['summary'] = summary
            metadata['last_summary_time'] = time.time()
            metadata['total_tokens'] = len(summary) // 4  # 摘要的 token 估算
            
            # 保留最近的几条消息
            keep_messages = min(5, len(messages))
            self.conversations[conversation_id] = messages[-keep_messages:]
            
            # 更新统计
            self.stats['total_summaries'] += 1
            
            logger.info(f"[ContextManager] 摘要完成 - 对话: {conversation_id}, 摘要长度: {len(summary)}")
            
        except Exception as e:
            logger.error(f"[ContextManager] 摘要失败 - 对话: {conversation_id}, 错误: {e}")
    
    async def get_trimmed_messages(
        self, 
        conversation_id: str, 
        max_tokens: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        获取修剪后的消息列表
        
        Args:
            conversation_id: 对话 ID
            max_tokens: 最大 token 数量
            
        Returns:
            修剪后的消息列表
        """
        if not self.enabled:
            return []
        
        messages = self.get_conversation(conversation_id)
        metadata = self.get_conversation_metadata(conversation_id)
        
        # 如果没有指定最大 token 数量，使用配置值
        if max_tokens is None:
            max_tokens = self.max_tokens
        
        # 如果有摘要，优先使用摘要
        if metadata.get('summary'):
            return [
                {'role': 'system', 'content': f"对话摘要：{metadata['summary']}"},
                {'role': 'user', 'content': messages[-1].content if messages else ''}
            ]
        
        # 计算当前消息的 token 使用量
        current_tokens = sum(len(msg.content) // 4 for msg in messages)
        
        # 如果超出限制，进行修剪
        if current_tokens > max_tokens:
            # 从后向前保留消息
            trimmed_messages = []
            remaining_tokens = max_tokens
            
            for msg in reversed(messages):
                msg_tokens = len(msg.content) // 4
                if msg_tokens <= remaining_tokens:
                    trimmed_messages.insert(0, msg.to_dict())
                    remaining_tokens -= msg_tokens
                else:
                    break
            
            # 如果还是超出限制，触发摘要
            if remaining_tokens < max_tokens * 0.5:
                await self._summarize_conversation(conversation_id)
                return await self.get_trimmed_messages(conversation_id, max_tokens)
            
            return trimmed_messages
        
        return [msg.to_dict() for msg in messages]
    
    async def get_conversation_summary(self, conversation_id: str) -> Optional[str]:
        """获取对话摘要"""
        if not self.enabled:
            return None
        
        metadata = self.get_conversation_metadata(conversation_id)
        return metadata.get('summary')
    
    async def clear_conversation(self, conversation_id: str):
        """清空对话"""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
            del self.conversation_metadata[conversation_id]
            logger.info(f"[ContextManager] 清空对话: {conversation_id}")
    
    async def get_conversation_stats(self, conversation_id: str) -> Dict[str, Any]:
        """获取对话统计信息"""
        messages = self.get_conversation(conversation_id)
        metadata = self.get_conversation_metadata(conversation_id)
        
        return {
            'message_count': len(messages),
            'total_tokens': metadata.get('total_tokens', 0),
            'summary_available': metadata.get('summary') is not None,
            'last_updated': metadata.get('last_updated'),
            'created_at': metadata.get('created_at')
        }
    
    async def get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计信息"""
        return {
            **self.stats,
            'active_conversations': len(self.conversations),
            'summarize_enabled': self.summarize_enabled,
            'summarize_threshold': self.summarize_threshold,
            'summarize_strategy': self.summarize_strategy
        }
    
    async def cleanup_old_conversations(self, max_age_hours: int = 24):
        """清理旧的对话"""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        conversations_to_remove = []
        
        for conversation_id, metadata in self.conversation_metadata.items():
            age = current_time - metadata.get('last_updated', 0)
            if age > max_age_seconds:
                conversations_to_remove.append(conversation_id)
        
        for conversation_id in conversations_to_remove:
            await self.clear_conversation(conversation_id)
        
        logger.info(f"[ContextManager] 清理完成 - 删除 {len(conversations_to_remove)} 个旧对话")
    
    async def export_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """导出对话数据"""
        messages = self.get_conversation(conversation_id)
        metadata = self.get_conversation_metadata(conversation_id)
        
        return {
            'conversation_id': conversation_id,
            'metadata': metadata,
            'messages': [msg.to_dict() for msg in messages],
            'exported_at': time.time()
        }
    
    async def import_conversation(self, conversation_data: Dict[str, Any]):
        """导入对话数据"""
        conversation_id = conversation_data['conversation_id']
        messages_data = conversation_data['messages']
        metadata = conversation_data.get('metadata', {})
        
        # 创建消息对象
        messages = [ContextMessage.from_dict(msg_data) for msg_data in messages_data]
        
        # 更新对话
        self.conversations[conversation_id] = messages
        self.conversation_metadata[conversation_id] = metadata
        
        # 更新统计
        self.stats['total_messages'] += len(messages)
        self.stats['total_conversations'] += 1
        
        logger.info(f"[ContextManager] 导入完成 - 对话: {conversation_id}, 消息数: {len(messages)}")


# 全局上下文管理器实例
_context_manager: Optional[ContextManager] = None


async def get_context_manager() -> ContextManager:
    """获取全局上下文管理器"""
    global _context_manager
    
    if _context_manager is None:
        # 从配置中加载上下文管理配置
        from src.core.config import get_config
        config = get_config()
        context_config = config.context_management
        
        _context_manager = ContextManager(context_config)
        await _context_manager.initialize()
    
    return _context_manager


async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
) -> ContextMessage:
    """
    便捷函数：添加消息到上下文
    
    Args:
        conversation_id: 对话 ID
        role: 消息角色
        content: 消息内容
        metadata: 消息元数据
        
    Returns:
        添加的消息对象
    """
    manager = await get_context_manager()
    return await manager.add_message(conversation_id, role, content, metadata)


async def get_trimmed_messages(
    conversation_id: str,
    max_tokens: Optional[int] = None
) -> List[Dict[str, str]]:
    """
    便捷函数：获取修剪后的消息列表
    
    Args:
        conversation_id: 对话 ID
        max_tokens: 最大 token 数量
        
    Returns:
        修剪后的消息列表
    """
    manager = await get_context_manager()
    return await manager.get_trimmed_messages(conversation_id, max_tokens)