#!/usr/bin/env python3
"""
Test script for CosyVoice2 TTS Service.

Tests the REST API endpoints and verifies audio synthesis.
"""

import asyncio
import httpx
import sys
import time


async def test_cosyvoice_service():
    """Test CosyVoice TTS service."""
    
    base_url = "http://localhost:5002"
    
    print("=" * 60)
    print("CosyVoice2 TTS Service Test")
    print("=" * 60)
    print()
    
    async with httpx.AsyncClient() as client:
        # Test 1: Root endpoint
        print("Test 1: Root endpoint...")
        try:
            resp = await client.get(f"{base_url}/")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  ✓ Service: {data.get('service')}")
                print(f"  ✓ Status: {data.get('status')}")
            else:
                print(f"  ✗ HTTP {resp.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Connection failed: {e}")
            print("  Make sure the service is running: python app.py")
            return False
        
        print()
        
        # Test 2: Health check
        print("Test 2: Health check...")
        try:
            resp = await client.get(f"{base_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  ✓ Status: {data.get('status')}")
                print(f"  ✓ Model: {data.get('model')}")
                print(f"  ✓ Ready: {data.get('ready')}")
            else:
                print(f"  ✗ Health check failed: HTTP {resp.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Health check error: {e}")
            return False
        
        print()
        
        # Test 3: Synthesis
        test_texts = [
            "Hello, this is a test.",
            "The quick brown fox jumps over the lazy dog.",
            "CosyVoice is working correctly!",
        ]
        
        print("Test 3: Speech synthesis...")
        for i, text in enumerate(test_texts, 1):
            print(f"  Test 3.{i}: {text}")
            
            try:
                start_time = time.time()
                resp = await client.post(
                    f"{base_url}/synthesize",
                    json={"text": text},
                    timeout=30.0
                )
                duration = time.time() - start_time
                
                if resp.status_code == 200:
                    audio_bytes = resp.content
                    print(f"    ✓ Generated {len(audio_bytes)} bytes in {duration:.2f}s")
                    
                    # Save audio file
                    filename = f"test_{i}.wav"
                    with open(filename, "wb") as f:
                        f.write(audio_bytes)
                    print(f"    ✓ Saved as {filename}")
                    
                else:
                    print(f"    ✗ Synthesis failed: HTTP {resp.status_code}")
                    print(f"    Error: {resp.text}")
                    return False
                    
            except httpx.TimeoutException:
                print(f"    ✗ Synthesis timeout (>30s)")
                return False
            except Exception as e:
                print(f"    ✗ Synthesis error: {e}")
                return False
        
        print()
        
        # Test 4: Error handling
        print("Test 4: Error handling...")
        try:
            resp = await client.post(
                f"{base_url}/synthesize",
                json={"text": ""},  # Empty text
                timeout=10.0
            )
            if resp.status_code == 400:
                print("  ✓ Empty text rejected correctly")
            else:
                print(f"  ✗ Expected 400, got {resp.status_code}")
        except Exception as e:
            print(f"  ✗ Error test failed: {e}")
    
    print()
    print("=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)
    print()
    print("CosyVoice2 TTS service is ready for use.")
    print("Generated test files: test_1.wav, test_2.wav, test_3.wav")
    print()
    print("Play test audio:")
    print("  aplay test_1.wav  # Linux")
    print("  afplay test_1.wav  # macOS")
    print()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_cosyvoice_service())
    sys.exit(0 if success else 1)