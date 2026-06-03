"""E2E API test for WebAPI"""
import sys, json, asyncio
import httpx

async def test():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:18080", timeout=10) as c:
        # 1. Health
        r = await c.get("/health")
        assert r.status_code == 200
        print(f"[OK] GET /health -> 200 | providers={r.json()['providers']}")

        # 2. Admin providers
        r = await c.get("/admin/providers")
        data = r.json()
        assert r.status_code == 200
        assert set(data["registered"]) == {
            "deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao"
        }, f"registered providers mismatch: {data['registered']}"
        print(f"[OK] GET /admin/providers -> registered={data['registered']}")

        # 3. Models
        r = await c.get("/v1/models")
        assert r.status_code == 200
        print(f"[OK] GET /v1/models -> 200")

        # 4. Chat - deepseek (no account configured -> 503)
        r = await c.post("/v1/chat/completions", json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        assert r.status_code == 503
        print(f"[OK] POST deepseek -> 503 (expected: no account)")

        # 5. Chat - kimi
        r = await c.post("/v1/chat/completions", json={
            "model": "Kimi-K2.6",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        assert r.status_code == 503
        print(f"[OK] POST kimi -> 503 (expected: no account)")

        # 6. Chat - qwen
        r = await c.post("/v1/chat/completions", json={
            "model": "qwen-max",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        assert r.status_code == 503
        print(f"[OK] POST qwen -> 503 (expected: no account)")

        # 7. Chat - unknown model (inferred from name)
        r = await c.post("/v1/chat/completions", json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        assert r.status_code == 503
        print(f"[OK] POST deepseek-v4-flash -> 503 (model inference works)")

        # 8. Admin config
        r = await c.get("/admin/config")
        assert r.status_code == 200
        print(f"[OK] GET /admin/config -> 200")

        print("\nAll E2E tests PASSED!")

asyncio.run(test())