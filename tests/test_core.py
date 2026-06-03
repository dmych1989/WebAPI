# -*- coding: utf-8 -*-
"""WebAPI — 核心模块测试"""

import pytest
from src.core.config import AppConfig, ServerConfig, load_config
from src.core.models import ChatCompletionRequest, ChatMessage, StreamChunk
from src.core.exceptions import WebAPIError, ProviderError, AuthError, RateLimitError


class TestConfig:
    """配置模块测试"""

    def test_default_config(self):
        config = AppConfig()
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 8080
        assert config.proxy.timeout == 120

    def test_server_config(self):
        srv = ServerConfig(host="0.0.0.0", port=3000)
        assert srv.host == "0.0.0.0"
        assert srv.port == 3000


class TestModels:
    """数据模型测试"""

    def test_chat_request(self):
        req = ChatCompletionRequest(
            model="deepseek-v4-flash",
            messages=[
                ChatMessage(role="user", content="Hello!")
            ],
        )
        assert req.model == "deepseek-v4-flash"
        assert req.stream is False
        assert len(req.messages) == 1

    def test_stream_chunk(self):
        chunk = StreamChunk(content="你好", model="test-model")
        assert chunk.content == "你好"
        assert chunk.finish_reason is None

    def test_chat_message_multimodal(self):
        msg = ChatMessage(
            role="user",
            content=[{"type": "text", "text": "Describe this"}],
        )
        assert isinstance(msg.content, list)


class TestExceptions:
    """异常测试"""

    def test_base_exception(self):
        e = WebAPIError("test error")
        assert str(e) == "test error"

    def test_provider_error(self):
        e = ProviderError("provider down", provider="test", status_code=500)
        assert e.provider == "test"
        assert e.status_code == 500

    def test_auth_error(self):
        e = AuthError("bad token")
        assert e.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])