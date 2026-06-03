# -*- coding: utf-8 -*-
"""WebAPI — 服务器测试"""

import pytest
from httpx import AsyncClient, ASGITransport

from src.server.app import app


@pytest.mark.asyncio
async def test_root_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "WebAPI"


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_models_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"


@pytest.mark.asyncio
async def test_chat_no_providers():
    """无可用 Provider 时应返回 503"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 503


@pytest.mark.asyncio
async def test_stats_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/stats")
        assert response.status_code == 200
