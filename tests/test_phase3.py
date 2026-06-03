"""Phase 3 E2E test — Auth + Health Check + Fallback + Stats"""
import sys, json, asyncio
import httpx

async def test():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:18080", timeout=10) as c:

        # ===== 1. Health =====
        r = await c.get("/health")
        assert r.status_code == 200
        print(f"[OK] GET /health -> 200")

        # ===== 1.5 Reset stats =====
        r = await c.post("/admin/stats/reset")
        assert r.status_code == 200
        print(f"[OK] POST /admin/stats/reset -> cleared")

        # ===== 2. Stats (initial) =====
        r = await c.get("/stats")
        assert r.status_code == 200
        data = r.json()
        assert "uptime_seconds" in data
        assert "providers" in data
        assert "pool" in data
        assert data["total_requests"] == 0
        print(f"[OK] GET /stats -> total_requests=0, uptime={data['uptime_seconds']:.1f}s")

        # ===== 3. Admin stats =====
        r = await c.get("/admin/stats")
        assert r.status_code == 200
        print(f"[OK] GET /admin/stats -> 200")

        # ===== 4. Admin providers =====
        r = await c.get("/admin/providers")
        data = r.json()
        assert r.status_code == 200
        expected_providers = {"deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao", "glm", "coze"}
        registered_set = set(data["registered"])
        assert registered_set >= {"deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao"}, \
            f"registered providers mismatch: {data['registered']}"
        print(f"[OK] GET /admin/providers -> registered={data['registered']}")

        # ===== 5. Chat with no accounts -> 503 =====
        r = await c.post("/v1/chat/completions", json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        assert r.status_code == 503
        print(f"[OK] POST deepseek -> 503 (no account, stat recorded)")

        # ===== 6. Stats after error =====
        r = await c.get("/stats")
        data = r.json()
        assert data["total_requests"] == 1  # total includes errors too
        assert data["error_requests"] == 1
        print(f"[OK] GET /stats -> total_requests=1, error_requests=1")

        # ===== 7. Auth middleware — API key disabled by default =====
        r = await c.get("/admin/config")
        data = r.json()
        assert data["server"]["api_key_enabled"] is False
        print(f"[OK] API key auth is disabled (default)")

        # ===== 8. Models =====
        r = await c.get("/v1/models")
        assert r.status_code == 200
        print(f"[OK] GET /v1/models -> 200")

        # ===== 9. Admin config reload =====
        r = await c.post("/admin/config/reload")
        assert r.status_code == 200
        print(f"[OK] POST /admin/config/reload -> 200")

        # ===== 10. Admin pool =====
        r = await c.get("/admin/pool")
        assert r.status_code == 200
        print(f"[OK] GET /admin/pool -> 200")

        # ===== 11. Stats reset =====
        r = await c.post("/admin/stats/reset")
        assert r.status_code == 200
        r = await c.get("/stats")
        assert r.json()["total_requests"] == 0
        print(f"[OK] POST /admin/stats/reset -> stats cleared")

        print("\nAll 11 Phase 3 E2E tests PASSED!")

asyncio.run(test())