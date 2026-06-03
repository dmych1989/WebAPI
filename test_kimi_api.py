#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kimi API endpoint"""
import asyncio
import json
import sys
import aiohttp

sys.path.insert(0, r"d:\GitHub\WebAPI")

import aiohttp
from src.core.models import ChatCompletionRequest
from src.provider.kimi import KimiProvider
from src.core.config import AccountConfig

async def test_kimi_api():
    """Test the Kimi API endpoint"""
    print("Testing Kimi API endpoint...")
    
    # Create a test request
    request = ChatCompletionRequest(
        model="Kimi-K2.6",
        messages=[
            {"role": "user", "content": "你好，请回复OK"}
        ],
        max_tokens=10,
        temperature=0.7
    )
    
    # Create provider instance
    account = AccountConfig(
        name="test-account",
        token="dummy_token_for_testing",
        models=["Kimi-K2.6"]
    )
    
    provider = KimiProvider(account)
    
    try:
        # Test the login method
        print("Testing login...")
        token = await provider.login()
        print(f"Login successful, token length: {len(token)}")
        
        # Test the payload building
        print("Testing payload building...")
        content, enable_search, enable_thinking = provider._messages_to_content(request)
        print(f"Content prepared: {len(content)} characters")
        
        # Test the health check
        print("Testing health check...")
        health = await provider.health_check()
        print(f"Health check result: {health}")
        
        print("All tests passed!")
        
    except Exception as e:
        print(f"Test failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_kimi_api())