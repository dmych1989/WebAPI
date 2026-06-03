#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Kimi API fix"""
import asyncio
import json
import sys
import uuid

sys.path.insert(0, r"d:\GitHub\WebAPI")

from src.provider.kimi import _build_kimi_payload, _encode_grpc_frame

def test_payload_structure():
    """Test the updated payload structure"""
    print("Testing Kimi payload structure...")
    
    # Test the new payload structure
    payload = _build_kimi_payload(
        model="Kimi-K2.6",
        content="Hello, this is a test message",
        enable_search=False,
        enable_thinking=False
    )
    
    print(f"Payload length: {len(payload)} bytes")
    print(f"First 20 bytes: {payload[:20]}")
    
    # Check if chat_id is properly included
    # The payload should start with chat_id field (tag 0x0A)
    if payload.startswith(b'\x0a'):
        print("OK: chat_id field is present (tag 0x0A)")
    else:
        print("ERROR: chat_id field is missing")
    
    # Test with different models
    models = ["Kimi-K2.6", "Kimi-K2.6-Think", "Kimi-K2.6-Search"]
    for model in models:
        payload = _build_kimi_payload(
            model=model,
            content="Test message",
            enable_search="Search" in model,
            enable_thinking="Think" in model
        )
        print(f"Model {model}: payload length = {len(payload)}")
    
    print("\nPayload structure test completed successfully!")

if __name__ == "__main__":
    test_payload_structure()