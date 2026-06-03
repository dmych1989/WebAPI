# -*- coding: utf-8 -*-
"""WebAPI — 上下文窗口管理

参考 Chat2API 的 contextManagementService。
支持三种策略：
- sliding_window: 滑动窗口，只保留最近 N 条消息
- trim: Token 裁剪，超过 max_tokens 时从最早消息裁剪
- summarize: 超量消息由模型自身总结后注入 system prompt
"""

from __future__ import annotations

from typing import Optional

from src.core.config import get_config
from src.core.models import ChatCompletionRequest, ChatMessage
from src.core.logger import logger


class ContextManager:
    """上下文窗口管理器

    在请求发送到 Provider 之前裁剪消息列表。
    """

    def __init__(self):
        self.config = get_config().context_management

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def trim(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """裁剪消息列表，确保不超过窗口限制

        Args:
            request: 原始请求

        Returns:
            裁剪后的请求（原地修改）
        """
        if not self.enabled:
            return request

        strategy = self.config.strategy

        if strategy == "sliding_window":
            return self._sliding_window(request)
        elif strategy == "trim":
            return self._token_trim(request)
        elif strategy == "summarize":
            return self._summarize(request)
        else:
            logger.warning(f"[Context] Unknown strategy: {strategy}, using sliding_window")
            return self._sliding_window(request)

    # ---- 滑动窗口 ----

    def _sliding_window(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """只保留最近 max_messages 条消息 + 保留所有 system 消息"""
        max_messages = self.config.max_messages
        messages = request.messages

        if len(messages) <= max_messages:
            return request

        # 分离 system 消息和对话消息
        system_msgs = [m for m in messages if m.role == "system"]
        chat_msgs = [m for m in messages if m.role != "system"]

        # 滑动窗口：保留最近的消息 + 足够的 system 消息
        available = max_messages - len(system_msgs)
        if available <= 0:
            # system 消息太多，只保留最后一条
            trimmed = system_msgs[-1:] + chat_msgs[-max(1, max_messages - 1):]
        else:
            trimmed = system_msgs + chat_msgs[-available:]

        skipped = len(messages) - len(trimmed)
        request.messages = trimmed

        logger.info(
            f"[Context] sliding_window: {len(messages)} → {len(trimmed)} "
            f"(skipped {skipped}, max={max_messages})"
        )
        return request

    # ---- Token 裁剪 ----

    def _token_trim(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """按 Token 数裁剪消息，从最早的消息开始移除"""
        max_tokens = self.config.max_tokens
        messages = request.messages

        # 估算 token 数（粗略：中文 ~1.5 char/token，英文 ~4 char/token）
        total = self._estimate_tokens(messages)

        if total <= max_tokens:
            return request

        # 从最早的非 system 消息开始裁剪
        system_msgs = [m for m in messages if m.role == "system"]
        chat_msgs = [m for m in messages if m.role != "system"]

        while chat_msgs and self._estimate_tokens(system_msgs + chat_msgs) > max_tokens:
            chat_msgs.pop(0)

        trimmed = system_msgs + chat_msgs

        if not chat_msgs:
            logger.warning("[Context] trim: all chat messages removed, keeping system + last")
            chat_msgs = [m for m in messages if m.role != "system"][-3:]
            trimmed = system_msgs + chat_msgs

        skipped = len(messages) - len(trimmed)
        request.messages = trimmed

        logger.info(
            f"[Context] trim: {len(messages)} → {len(trimmed)} "
            f"(tokens: {total} → ~{self._estimate_tokens(trimmed)}, skipped {skipped})"
        )
        return request

    # ---- 摘要模式 ----

    def _summarize(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """超量消息：将早期消息替换为摘要

        注意：摘要需要调用 LLM 生成，此处为半自动实现：
        1. 保留最近 max_messages 条
        2. 将更早的消息压缩为一条 summary 注入 system prompt
        """
        max_messages = self.config.max_messages
        messages = request.messages
        total = len(messages)

        if total <= max_messages:
            return request

        # 分离消息
        system_msgs = [m for m in messages if m.role == "system"]
        chat_msgs = [m for m in messages if m.role != "system"]

        # 需要摘要的消息：前 total - max_messages 条
        split_point = total - max_messages
        old_msgs = chat_msgs[:split_point]
        recent_msgs = chat_msgs[split_point:]

        # 生成摘要（简易版：提取对话主题）
        summary = self._generate_simple_summary(old_msgs)

        # 注入 system prompt
        summary_msg = ChatMessage(
            role="system",
            content=f"[历史对话摘要]\n{summary}\n\n--- 以下为近期对话 ---",
        )

        if system_msgs:
            # 在最后一个 system 消息后插入摘要
            insert_idx = len(system_msgs)
            trimmed = system_msgs + [summary_msg] + recent_msgs
        else:
            trimmed = [summary_msg] + recent_msgs

        skipped = total - len(trimmed)
        request.messages = trimmed

        logger.info(
            f"[Context] summarize: {total} → {len(trimmed)} "
            f"(summarized {len(old_msgs)} old messages, kept {len(recent_msgs)})"
        )
        return request

    def _generate_simple_summary(self, messages: list[ChatMessage]) -> str:
        """简易摘要生成（不依赖 LLM）

        提取对话中关键的用户提问和助手回复要点。
        """
        lines = []
        for msg in messages:
            content = self._get_text(msg)
            if not content:
                continue
            # 截取前 80 字符
            snippet = content[:80].replace("\n", " ")
            if msg.role == "user":
                lines.append(f"用户问: {snippet}")
            elif msg.role == "assistant":
                lines.append(f"助手答: {snippet}...")
            elif msg.role == "system":
                lines.append(f"系统: {snippet}")

        if not lines:
            return "（无历史对话）"

        return "\n".join(lines[:20])  # 最多 20 行

    # ---- Token 估算 ----

    @staticmethod
    def _estimate_tokens(messages: list[ChatMessage]) -> int:
        """粗略估算 Token 数"""
        total = 0
        for msg in messages:
            text = ContextManager._get_text(msg)
            # 粗略：中文 ~1.5 char/token，英文 ~4 char/token
            # 保守估计：平均 2 char/token
            total += max(1, len(text) // 2)
        return total

    @staticmethod
    def _get_text(msg: ChatMessage) -> str:
        """从 ChatMessage 提取文本"""
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text", ""))
                else:
                    parts.append(str(item))
            return " ".join(parts)
        if content is None:
            return ""
        return str(content)


# 全局单例
context_manager = ContextManager()