# -*- coding: utf-8 -*-
"""WebAPI — Provider Registration

在 import 时自动注册所有内置 Provider。
从 provider 子目录导入每个 Provider 模块，触发 @ProviderRegistry.register 装饰器。
"""

# Import each provider module to trigger @ProviderRegistry.register decorators
from src.provider.deepseek import DeepSeekProvider
from src.provider.kimi import KimiProvider
from src.provider.qwen import QwenProvider
from src.provider.minimax import MiniMaxProvider
from src.provider.doubao import DoubaoProvider
from src.provider.yuanbao import YuanbaoProvider
from src.provider.glm import GLMProvider
from src.provider.coze import CozeProvider

__all__ = [
    "DeepSeekProvider", "KimiProvider", "QwenProvider",
    "MiniMaxProvider", "DoubaoProvider", "YuanbaoProvider",
    "GLMProvider", "CozeProvider",
]