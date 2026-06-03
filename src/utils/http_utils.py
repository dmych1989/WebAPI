# -*- coding: utf-8 -*-
"""WebAPI — HTTP 工具
"""

import re
from typing import Optional


def extract_token_from_authorization(header_value: str) -> Optional[str]:
    """从 Authorization Header 提取 Token"""
    if header_value.startswith("Bearer "):
        return header_value[7:]
    return header_value


def parse_sse_line(line: str) -> Optional[dict]:
    """解析 SSE data 行 → dict"""
    if not line.startswith("data:"):
        return None

    data_str = line[5:].strip()

    if data_str == "[DONE]":
        return {"_done": True}

    import json
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)
