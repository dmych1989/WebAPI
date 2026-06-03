# -*- coding: utf-8 -*-
"""WebAPI — 工具调用引擎 (Tool Calling)

通过 Prompt Engineering 方式实现工具调用，参考 Chat2API 的 ToolCallingEngine。
在不支持原生 function calling 的网页版模型上，通过 system prompt 注入工具定义，
从流式响应中解析工具调用 JSON。

工作流程：
1. 在 system prompt 中注入工具定义
2. 模型返回包含 <tool_call> 标记的文本
3. 解析标记，提取 function name + arguments
4. 客户端执行工具后，将结果作为 tool 消息发回
5. 模型基于工具结果生成最终回复
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from src.core.logger import logger
from src.core.models import ChatCompletionRequest, ToolDefinition


class ToolCallingEngine:
    """工具调用引擎（Prompt Engineering 模式）"""

    TOOL_CALL_START = "<tool_call>"
    TOOL_CALL_END = "</tool_call>"

    SYSTEM_PROMPT_TEMPLATE = """## 可用工具

你可以调用以下工具来获取信息或执行操作。需要调用工具时，请使用以下格式：

<tool_call>
{{
  "name": "工具名称",
  "arguments": {{
    "参数名": "参数值"
  }}
}}
</tool_call>

调用工具后，用户会返回工具的执行结果。你可以继续对话或调用其他工具。

{tool_definitions}

## 重要规则

1. 一次只调用一个工具
2. 工具调用必须放在 <tool_call></tool_call> 标签内
3. 工具调用的 JSON 必须是有效的 JSON 格式
4. 不需要使用工具时，直接回复用户即可
"""

    def __init__(self):
        from src.core.config import get_config
        self.config = get_config().tool_calling

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self.config.mode == "prompt_engineering"

    def inject_tools(
        self, request: ChatCompletionRequest
    ) -> Optional[str]:
        """在 system prompt 中注入工具定义

        Args:
            request: 请求（会被原地修改）

        Returns:
            注入的工具定义文本，或 None（无工具时）
        """
        if not self.enabled:
            return None

        tools = request.tools
        if not tools:
            return None

        # 格式化工具定义
        definitions = self._format_tool_definitions(tools)
        tool_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            tool_definitions=definitions,
        )

        # 找到或创建 system 消息
        if request.messages and request.messages[0].role == "system":
            # 追加到现有 system prompt
            existing = self._get_text(request.messages[0])
            request.messages[0].content = existing + "\n\n" + tool_prompt
        else:
            # 插入 system 消息到开头
            from src.core.models import ChatMessage
            request.messages.insert(0, ChatMessage(
                role="system",
                content=tool_prompt,
            ))

        logger.info(
            f"[ToolCalling] Injected {len(tools)} tool(s): "
            f"{[t.function.get('name', '?') for t in tools]}"
        )
        return tool_prompt

    def _format_tool_definitions(self, tools: list[ToolDefinition]) -> str:
        """格式化工具定义为可读文本"""
        lines = []
        for tool in tools:
            func = tool.function
            name = func.get("name", "unknown")
            desc = func.get("description", "无描述")
            params = func.get("parameters", {}).get("properties", {})

            lines.append(f"### {name}")
            lines.append(f"描述: {desc}")

            if params:
                lines.append("参数:")
                for param_name, param_info in params.items():
                    param_type = param_info.get("type", "string")
                    param_desc = param_info.get("description", "")
                    required = param_name in func.get("parameters", {}).get("required", [])
                    req_mark = "（必填）" if required else "（可选）"
                    lines.append(f"  - {param_name} ({param_type}) {req_mark}: {param_desc}")

            lines.append("")  # 空行分隔

        return "\n".join(lines)

    def parse_tool_call(self, text: str) -> Optional[dict[str, Any]]:
        """从模型响应中解析工具调用

        Args:
            text: 模型输出的文本

        Returns:
            {"name": "工具名", "arguments": {...}} 或 None
        """
        # 方法 1: <tool_call> 标签
        pattern = re.compile(
            r"<tool_call>\s*(.*?)\s*</tool_call>",
            re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"[ToolCalling] Invalid JSON in tool_call: {e}")
                # 尝试修复常见格式问题
                return self._attempt_fix(match.group(1))

        # 方法 2: 纯 JSON 块（```json ... ```)
        pattern2 = re.compile(
            r"```(?:json)?\s*\n?\s*(\{.*?\})\s*\n?\s*```",
            re.DOTALL,
        )
        match2 = pattern2.search(text)
        if match2:
            try:
                data = json.loads(match2.group(1))
                if "name" in data and "arguments" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # 方法 3: 裸 JSON（以 { 开头且包含 name 和 arguments）
        pattern3 = re.compile(
            r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:',
        )
        if pattern3.search(text):
            # 尝试找到完整的 JSON 对象
            brace_idx = text.find(pattern3.pattern[:5])
            if brace_idx >= 0:
                depth = 0
                for i in range(brace_idx, len(text)):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[brace_idx:i+1])
                            except json.JSONDecodeError:
                                break

        return None

    def _attempt_fix(self, json_str: str) -> Optional[dict[str, Any]]:
        """尝试修复常见 JSON 格式问题"""
        # 移除注释
        cleaned = re.sub(r"//.*$", "", json_str, flags=re.MULTILINE)
        # 修复单引号
        cleaned = cleaned.replace("'", '"')
        # 移除尾部逗号
        cleaned = re.sub(r",\s*}", "}", cleaned)
        cleaned = re.sub(r",\s*]", "]", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    def build_tool_result_message(
        self,
        tool_call_id: str,
        tool_name: str,
        result: Any,
    ) -> dict:
        """构建工具结果消息"""
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, ensure_ascii=False)
        else:
            result_str = str(result)

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result_str,
        }

    def has_tool_call_pending(self, text: str) -> bool:
        """检查文本中是否有待完成的工具调用"""
        if self.TOOL_CALL_START in text and self.TOOL_CALL_END not in text:
            return True
        return False

    @staticmethod
    def _get_text(msg) -> str:
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
tool_calling = ToolCallingEngine()