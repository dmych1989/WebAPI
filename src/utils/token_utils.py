# -*- coding: utf-8 -*-
"""WebAPI — Token 计数工具

使用 tiktoken 近似计算消息的 token 数。
"""

from typing import Any


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """估算消息列表的 token 数

    使用字符数 / 3 的粗略估算。
    更精确的计数需要知道具体模型的 tokenizer。
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            # 多模态内容
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total_chars += len(part["text"])
    # 粗略估算：1 token ≈ 3 字符
    return max(1, total_chars // 3)


def trim_messages(
    messages: list[dict[str, Any]],
    max_tokens: int,
    strategy: str = "sliding_window",
) -> list[dict[str, Any]]:
    """按 token 限制裁剪消息

    Args:
        messages: 消息列表
        max_tokens: 最大 token 数
        strategy: 裁剪策略

    Returns:
        裁剪后的消息列表
    """
    if strategy == "sliding_window":
        return _trim_sliding_window(messages, max_tokens)
    elif strategy == "trim":
        return _trim_from_start(messages, max_tokens)
    return messages


def _trim_sliding_window(
    messages: list[dict[str, Any]], max_tokens: int
) -> list[dict[str, Any]]:
    """滑动窗口裁剪 — 保留 system prompt + 最近的消息"""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    # 保留 system prompt
    system_tokens = estimate_tokens(system_msgs)
    remaining = max_tokens - system_tokens

    # 从最新的消息开始保留
    result = list(system_msgs)
    current_tokens = 0

    for msg in reversed(other_msgs):
        msg_tokens = estimate_tokens([msg])
        if current_tokens + msg_tokens > remaining:
            break
        result.insert(len(system_msgs), msg)
        current_tokens += msg_tokens

    return result


def _trim_from_start(
    messages: list[dict[str, Any]], max_tokens: int
) -> list[dict[str, Any]]:
    """从开头裁剪 — 去掉最早的消息"""
    result = []
    current_tokens = 0

    # 保留 system prompt
    system_msgs = [m for m in messages if m.get("role") == "system"]
    result.extend(system_msgs)
    current_tokens = estimate_tokens(system_msgs)

    for msg in messages:
        if msg.get("role") == "system":
            continue
        msg_tokens = estimate_tokens([msg])
        if current_tokens + msg_tokens > max_tokens:
            break
        result.append(msg)
        current_tokens += msg_tokens

    return result
