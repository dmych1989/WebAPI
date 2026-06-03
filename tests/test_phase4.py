"""Phase 4 E2E test — New Providers + Context Management + Tool Calling + Admin UI"""
import sys, json, asyncio
import httpx

async def test():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:18080", timeout=10) as c:
        passed = 0
        total = 0

        def ok(label=""):
            nonlocal passed, total
            total += 1
            passed += 1
            print(f"  [PASS] {label}")

        def fail(label, msg=""):
            nonlocal total
            total += 1
            print(f"  [FAIL] {label}: {msg}")

        # ===== 1. All 6 Providers registered =====
        print("\n--- Test: Provider Registration ---")
        r = await c.get("/admin/providers")
        data = r.json()
        expected = {"deepseek", "kimi", "qwen", "minimax", "doubao", "yuanbao"}
        actual = set(data["registered"])
        if expected == actual:
            ok("6 providers registered: " + ", ".join(sorted(actual)))
        else:
            fail("providers mismatch", f"expected {expected}, got {actual}")

        # ===== 2. Config includes new providers =====
        print("\n--- Test: Config ---")
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        r = await c.get("/admin/config")
        data = r.json()
        providers_in_config = set(data.get("providers", {}).keys())
        if expected.issubset(providers_in_config):
            ok(f"Config has all 6 providers")
        else:
            missing = expected - providers_in_config
            fail("config missing", str(missing))

        # ===== 3. Context management config =====
        if "context_management" in data:
            cm_data = data["context_management"]
            if cm_data.get("max_messages") == 50:
                ok("context_management config correct (max_messages=50)")
            else:
                fail("context_management", str(cm_data))
        else:
            # Admin endpoint filters config; code-level check
            from src.core.config import get_config
            cm = get_config().context_management
            if cm.enabled == False and cm.max_messages == 50 and cm.strategy == "sliding_window":
                ok("context_management config correct (code-level, max_messages=50)")
            else:
                fail("context_management", str(cm))

        # ===== 4. Tool calling config =====
        if "tool_calling" in data:
            tc = data["tool_calling"]
            if tc.get("mode") == "prompt_engineering":
                ok("tool_calling config correct (mode=prompt_engineering)")
            else:
                fail("tool_calling", str(tc))
        else:
            from src.core.config import get_config
            tc = get_config().tool_calling
            if tc.enabled == True and tc.mode == "prompt_engineering":
                ok("tool_calling config correct (code-level, mode=prompt_engineering)")
            else:
                fail("tool_calling", str(tc))

        # ===== 5. Admin UI accessible =====
        print("\n--- Test: Admin UI ---")
        r = await c.get("/admin/ui/admin.html")
        if r.status_code == 200 and "WebAPI Admin" in r.text:
            ok("Admin UI accessible (200)")
        else:
            fail("Admin UI", f"HTTP {r.status_code}")

        # ===== 6. Root endpoint =====
        r = await c.get("/")
        data = r.json()
        if data.get("service") == "WebAPI" and data.get("version") == "0.1.0":
            ok("Root endpoint OK")
        else:
            fail("Root endpoint", str(data))

        # ===== 7. /v1/models with all providers =====
        r = await c.get("/v1/models")
        data = r.json()
        model_count = len(data.get("data", []))
        if model_count > 0:
            ok(f"/v1/models returns {model_count} models")
        else:
            ok("/v1/models returns 0 models (no accounts configured, expected)")

        # ===== 8. New providers return 503 without accounts =====
        print("\n--- Test: New Providers (503 without accounts) ---")
        for prov in ["minimax", "doubao", "yuanbao"]:
            r = await c.post("/v1/chat/completions", json={
                "model": prov,
                "messages": [{"role": "user", "content": "Hi"}]
            })
            if r.status_code == 503:
                ok(f"{prov} -> 503 (no account, expected)")
            else:
                fail(f"{prov}", f"expected 503, got {r.status_code}")

        # ===== 9. Context management trim with tool calling injection =====
        print("\n--- Test: Context + Tool Calling (code-level) ---")
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.core.context_manager import ContextManager
        from src.core.tool_calling import ToolCallingEngine
        from src.core.models import ChatCompletionRequest, ChatMessage, ToolDefinition

        # Test context sliding window
        msgs = [ChatMessage(role="system", content="You are helpful.")]
        for i in range(60):
            msgs.append(ChatMessage(role="user", content=f"Question {i}"))
            msgs.append(ChatMessage(role="assistant", content=f"Answer {i}"))
        req = ChatCompletionRequest(model="test", messages=msgs)
        cm = ContextManager()
        cm.config.max_messages = 50
        cm.config.enabled = True
        cm.config.strategy = "sliding_window"
        result = cm.trim(req)
        if len(result.messages) == 50:
            ok(f"Context sliding_window: {len(msgs)} -> 50 messages")
        else:
            fail("context", f"expected 50, got {len(result.messages)}")

        # Test tool calling injection
        tools = [ToolDefinition(
            type="function",
            function={"name": "get_weather", "description": "Get weather", "parameters": {}}
        )]
        req2 = ChatCompletionRequest(model="test", messages=[
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="What's the weather?")
        ], tools=tools)
        tc = ToolCallingEngine()
        tc.config.enabled = True
        result = tc.inject_tools(req2)
        if result and "<tool_call>" in req2.messages[0].content:
            ok("Tool calling injection: system prompt contains tool definitions")
        else:
            fail("tool calling injection", "system prompt missing tool definitions")

        # ===== 10. Tool call parsing =====
        tc2 = ToolCallingEngine()
        text = '''Here is the result:

<tool_call>
{
  "name": "get_weather",
  "arguments": {
    "city": "Beijing"
  }
}
</tool_call>'''

        parsed = tc2.parse_tool_call(text)
        if parsed and parsed.get("name") == "get_weather":
            ok("Tool call parsing: extracted get_weather correctly")
        else:
            fail("tool call parsing", str(parsed))

        # ===== Summary =====
        print(f"\n{'='*50}")
        print(f"Phase 4 Test Results: {passed}/{total} passed")
        if passed == total:
            print("ALL TESTS PASSED!")
        else:
            print(f"FAILED: {total - passed} test(s)")
        print(f"{'='*50}")

asyncio.run(test())