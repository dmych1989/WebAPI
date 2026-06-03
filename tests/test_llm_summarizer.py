"""
LLM 摘要功能测试

测试真实的 LLM 集成上下文摘要功能。
"""

import asyncio
import json
import time
import sys
from typing import List, Dict, Any

import pytest
from src.context.llm_summarizer import get_summarization_manager, summarize_messages
from src.context.manager import get_context_manager, ContextMessage
from src.core.config import get_config


class TestLLMSummarizer:
    """LLM 摘要器测试类"""
    
    @pytest.fixture
    async def summarizer(self):
        """创建摘要器实例"""
        manager = await get_summarization_manager()
        return manager
    
    @pytest.fixture
    async def context_manager(self):
        """创建上下文管理器实例"""
        manager = await get_context_manager()
        return manager
    
    @pytest.mark.asyncio
    async def test_summarization_manager_initialization(self, summarizer):
        """测试摘要管理器初始化"""
        assert summarizer is not None
        assert len(summarizer.summarizers) > 0
        
        # 检查缓存信息
        cache_info = await summarizer.get_cache_info()
        assert 'default' in cache_info
        assert cache_info['default']['cache_size'] == 0
    
    @pytest.mark.asyncio
    async def test_basic_summarization(self, summarizer):
        """测试基本摘要功能"""
        # 测试消息
        messages = [
            {"role": "user", "content": "你好，我想学习机器学习。"},
            {"role": "assistant", "content": "机器学习是人工智能的一个重要分支，它让计算机能够从数据中学习模式。"},
            {"role": "user", "content": "能推荐一些入门书籍吗？"},
            {"role": "assistant", "content": "我推荐《机器学习》周志华教授的《西瓜书》，还有《深度学习》伊恩·古德费洛的书。"}
        ]
        
        # 生成摘要
        summary = await summarizer.summarize_messages(messages)
        
        assert summary is not None
        assert len(summary) > 0
        assert "机器学习" in summary
        
        print(f"原始消息数: {len(messages)}")
        print(f"摘要内容: {summary}")
    
    @pytest.mark.asyncio
    async def test_summarization_caching(self, summarizer):
        """测试摘要缓存功能"""
        messages = [
            {"role": "user", "content": "什么是人工智能？"},
            {"role": "assistant", "content": "人工智能是计算机科学的一个分支，致力于创建能够执行通常需要人类智能的任务的系统。"}
        ]
        
        # 第一次摘要（应该生成）
        summary1 = await summarizer.summarize_messages(messages)
        assert summary1 is not None
        
        # 第二次摘要（应该使用缓存）
        summary2 = await summarizer.summarize_messages(messages)
        assert summary2 == summary1
        
        # 检查缓存信息
        cache_info = await summarizer.get_cache_info()
        assert cache_info['default']['cache_size'] > 0
    
    @pytest.mark.asyncio
    async def test_force_refresh_summary(self, summarizer):
        """测试强制刷新摘要"""
        messages = [
            {"role": "user", "content": "请解释一下区块链技术。"},
            {"role": "assistant", "content": "区块链是一种分布式账本技术，它允许多方在没有中央权威的情况下安全地记录交易。"}
        ]
        
        # 第一次摘要
        summary1 = await summarizer.summarize_messages(messages)
        
        # 强制刷新第二次摘要
        summary2 = await summarizer.summarize_messages(messages, force_refresh=True)
        
        # 应该生成新的摘要
        assert summary1 != summary2  # 可能不同，取决于 LLM 的随机性
    
    @pytest.mark.asyncio
    async def test_multiple_strategies(self, summarizer):
        """测试多种摘要策略"""
        messages = [
            {"role": "user", "content": "什么是量子计算？"},
            {"role": "assistant", "content": "量子计算是一种利用量子力学现象进行计算的技术。与经典计算机使用位（0或1）不同，量子计算机使用量子位（qubit），可以同时处于多个状态。"},
            {"role": "user", "content": "量子计算有什么优势？"},
            {"role": "assistant", "content": "量子计算在处理某些特定问题时具有指数级的速度优势，比如大数分解、搜索算法和模拟量子系统。"}
        ]
        
        # 测试不同策略
        detailed_summary = await summarizer.summarize(messages, strategy='detailed')
        concise_summary = await summarizer.summarize(messages, strategy='concise')
        default_summary = await summarizer.summarize(messages, strategy='default')
        
        assert len(detailed_summary) > len(concise_summary)
        assert len(default_summary) > 0
        
        print(f"详细摘要: {detailed_summary}")
        print(f"简洁摘要: {concise_summary}")
        print(f"默认摘要: {default_summary}")
    
    @pytest.mark.asyncio
    async def test_large_message_summarization(self, summarizer):
        """测试大量消息的摘要"""
        # 创建大量消息
        messages = []
        for i in range(25):  # 超过20条消息，应该触发分段摘要
            messages.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"这是第 {i} 条消息，讨论人工智能的发展和应用。"
            })
        
        summary = await summarizer.summarize_messages(messages)
        
        assert summary is not None
        assert len(summary) > 0
        assert "人工智能" in summary
        
        print(f"大量消息摘要: {summary}")
    
    @pytest.mark.asyncio
    async def test_context_manager_integration(self, context_manager):
        """测试上下文管理器集成"""
        conversation_id = "test_conversation_001"
        
        # 添加消息
        await context_manager.add_message(conversation_id, "user", "你好，我想了解机器学习。")
        await context_manager.add_message(conversation_id, "assistant", "机器学习是AI的重要分支。")
        await context_manager.add_message(conversation_id, "user", "能推荐一些学习资源吗？")
        await context_manager.add_message(conversation_id, "assistant", "我推荐吴恩达的机器学习课程。")
        
        # 获取修剪后的消息
        trimmed_messages = await context_manager.get_trimmed_messages(conversation_id)
        
        assert len(trimmed_messages) > 0
        assert trimmed_messages[-1]['role'] == 'assistant'
        
        # 获取对话摘要
        summary = await context_manager.get_conversation_summary(conversation_id)
        
        # 由于我们还没有达到摘要阈值，摘要应该为空
        # assert summary is not None  # 这个测试可能需要调整
        
        print(f"修剪后的消息: {trimmed_messages}")
        print(f"对话摘要: {summary}")
    
    @pytest.mark.asyncio
    async def test_context_manager_summarization_trigger(self, context_manager):
        """测试上下文管理器摘要触发"""
        conversation_id = "test_conversation_002"
        
        # 添加大量消息以触发摘要
        for i in range(15):
            await context_manager.add_message(
                conversation_id, 
                "user" if i % 2 == 0 else "assistant", 
                f"这是第 {i} 条很长的消息，用来测试上下文管理器的摘要功能。这条消息包含了大量的文本内容，以便达到摘要触发的阈值。"
            )
        
        # 获取对话统计
        stats = await context_manager.get_conversation_stats(conversation_id)
        
        print(f"对话统计: {stats}")
        print(f"摘要: {await context_manager.get_conversation_summary(conversation_id)}")
    
    @pytest.mark.asyncio
    async def test_conversation_export_import(self, context_manager):
        """测试对话导出导入"""
        conversation_id = "test_conversation_003"
        
        # 添加消息
        await context_manager.add_message(conversation_id, "user", "测试消息1")
        await context_manager.add_message(conversation_id, "assistant", "测试回复1")
        await context_manager.add_message(conversation_id, "user", "测试消息2")
        await context_manager.add_message(conversation_id, "assistant", "测试回复2")
        
        # 导出对话
        exported_data = await context_manager.export_conversation(conversation_id)
        
        assert exported_data['conversation_id'] == conversation_id
        assert len(exported_data['messages']) == 4
        
        # 清空对话
        await context_manager.clear_conversation(conversation_id)
        
        # 重新导入
        await context_manager.import_conversation(exported_data)
        
        # 验证导入成功
        messages = context_manager.get_conversation(conversation_id)
        assert len(messages) == 4
        
        print(f"导出的数据: {exported_data}")
        print(f"导入后的消息数: {len(messages)}")
    
    @pytest.mark.asyncio
    async def test_cache_management(self, summarizer):
        """测试缓存管理"""
        # 添加一些摘要到缓存
        messages = [
            {"role": "user", "content": "什么是云计算？"},
            {"role": "assistant", "content": "云计算是通过互联网提供计算服务的技术。"}
        ]
        
        await summarizer.summarize_messages(messages)
        
        # 检查缓存
        cache_info = await summarizer.get_cache_info()
        assert cache_info['default']['cache_size'] > 0
        
        # 清除缓存
        await summarizer.clear_cache()
        
        # 再次检查缓存
        cache_info = await summarizer.get_cache_info()
        assert cache_info['default']['cache_size'] == 0
    
    @pytest.mark.asyncio
    async def test_error_handling(self, summarizer):
        """测试错误处理"""
        # 测试空消息列表
        empty_messages = []
        summary = await summarizer.summarize_messages(empty_messages)
        assert summary is not None
        
        # 测试只有一条消息
        single_message = [{"role": "user", "content": "只有一条消息"}]
        summary = await summarizer.summarize_messages(single_message)
        assert summary is not None
        
        # 测试非常长的消息
        long_message = [{"role": "user", "content": "a" * 10000}]
        summary = await summarizer.summarize_messages(long_message)
        assert summary is not None
    
    @pytest.mark.asyncio
    async def test_performance_benchmark(self, summarizer):
        """性能基准测试"""
        messages = [
            {"role": "user", "content": f"这是第 {i} 条测试消息。"}
            for i in range(10)
        ]
        
        # 测试多次摘要的性能
        start_time = time.time()
        
        for i in range(5):
            summary = await summarizer.summarize_messages(messages)
            assert summary is not None
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"5次摘要耗时: {duration:.2f}秒")
        print(f"平均每次耗时: {duration/5:.2f}秒")
        
        # 检查性能是否在合理范围内（每次摘要应该在10秒内完成）
        assert duration < 50  # 5次摘要应该在50秒内完成


async def run_tests():
    """运行测试"""
    print("🧪 开始 LLM 摘要功能测试...")
    
    # 创建测试实例
    summarizer = await get_summarization_manager()
    context_manager = await get_context_manager()
    
    try:
        # 运行基本摘要测试
        print("\n📝 测试基本摘要功能...")
        await test_basic_summarization(summarizer)
        
        # 测试缓存功能
        print("\n🗃️ 测试缓存功能...")
        await test_summarization_caching(summarizer)
        
        # 测试多种策略
        print("\n🎯 测试多种摘要策略...")
        await test_multiple_strategies(summarizer)
        
        # 测试大量消息摘要
        print("\n📚 测试大量消息摘要...")
        await test_large_message_summarization(summarizer)
        
        # 测试上下文管理器集成
        print("\n🔗 测试上下文管理器集成...")
        await test_context_manager_integration(context_manager)
        
        # 测试摘要触发
        print("\n⚡ 测试摘要触发...")
        await test_context_manager_summarization_trigger(context_manager)
        
        # 测试导出导入
        print("\n📤 测试对话导出导入...")
        await test_conversation_export_import(context_manager)
        
        # 测试缓存管理
        print("\n🗄️ 测试缓存管理...")
        await test_cache_management(summarizer)
        
        # 测试错误处理
        print("\n🛡️ 测试错误处理...")
        await test_error_handling(summarizer)
        
        # 性能基准测试
        print("\n⏱️ 性能基准测试...")
        await test_performance_benchmark(summarizer)
        
        print("\n🎉 所有测试通过！")
        return True
        
    except Exception as e:
        print(f"\n💥 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # 清理资源
        await summarizer.close()
        await context_manager.close()


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)