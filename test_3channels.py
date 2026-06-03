# -*- coding: utf-8 -*-
"""快速测试 3 个渠道修复"""
import asyncio
import json
import sys

sys.path.insert(0, r"d:\GitHub\WebAPI")

import aiohttp


async def test(model: str, stream: bool = False):
    url = "http://127.0.0.1:18080/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "回复1个字符OK"}],
        "stream": stream,
        "max_tokens": 5,
    }
    print(f"\n=== Test: {model} (stream={stream}) ===")
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.post(url, json=payload) as resp:
                body = await resp.text()
                print(f"HTTP {resp.status}")
                print(f"Body: {body[:500]}")
                if resp.status != 200:
                    return False
                if not stream:
                    obj = json.loads(body)
                    content = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
                    print(f"Content: {content!r}")
                return True
    except Exception as e:
        print(f"EXC: {type(e).__name__}: {e}")
        return False


async def main():
    results = {}
    for m in ["deepseek-chat", "deepseek-v4-flash", "kimi", "Kimi-K2.6", "glm-4-plus"]:
        results[m] = await test(m, stream=False)
    print("\n=== Summary ===")
    for m, ok in results.items():
        print(f"  {m}: {'OK' if ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
