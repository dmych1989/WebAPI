# -*- coding: utf-8 -*-
"""探测 minimax (MiniMax) 真实 API 端点"""
import asyncio
import aiohttp

PROBES = [
    ("https://hailuoai.com/api/chat/completion_prod", "POST"),
    ("https://hailuoai.com/api/chat/completion", "POST"),
    ("https://agent.minimaxi.com/api/chat/completion_prod", "POST"),
    ("https://agent.minimaxi.com/api/chat/completion", "POST"),
    ("https://agent.minimaxi.com/api/v1/chat", "POST"),
    ("https://agent.minimaxi.com/api/v1/chat/completions", "POST"),
    ("https://api.minimaxi.com/v1/text/chatcompletion_v2", "POST"),
    ("https://api.minimaxi.com/v1/text/chat", "POST"),
    ("https://hailuoai.com/api/user/info", "GET"),
    ("https://agent.minimaxi.com/api/user/info", "GET"),
]


async def probe():
    async with aiohttp.ClientSession() as sess:
        for url, method in PROBES:
            try:
                async with sess.request(
                    method, url,
                    json={"test": "hi"} if method == "POST" else None,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    text = await resp.text()
                    print(f"{method} {url[:65]}... -> HTTP {resp.status}  {text[:80]}")
            except Exception as e:
                print(f"{method} {url[:65]}... -> EXC {type(e).__name__}: {e}")


asyncio.run(probe())
