"""
Unit tests for WebSocket message validation.

Tests schema validation, input sanitization, and rate limiting.
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from server.validation import (
    validate_and_sanitize_input,
    validate_audio_length,
    ValidationError,
    RateLimiter,
    MAX_TEXT_LENGTH,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_KIOSK_ID_LENGTH,
    MAX_KIOSK_LOCATION_LENGTH,
)


class TestValidateAndSanitizeInput:
    """Test suite for validate_and_sanitize_input function."""
    
    def test_valid_session_start(self):
        """Test valid session_start message."""
        message = {
            "type": "session_start",
            "kiosk_id": "kiosk-01",
            "kiosk_location": "Floor 1 Lobby"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["type"] == "session_start"
        assert result["kiosk_id"] == "kiosk-01"
        assert result["kiosk_location"] == "Floor 1 Lobby"
    
    def test_session_start_strips_whitespace(self):
        """Test that session_start strips leading/trailing whitespace."""
        message = {
            "type": "session_start",
            "kiosk_id": "  kiosk-01  ",
            "kiosk_location": "  Floor 1 Lobby  "
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["kiosk_id"] == "kiosk-01"
        assert result["kiosk_location"] == "Floor 1 Lobby"
    
    def test_session_start_truncates_long_kiosk_id(self):
        """Test that kiosk_id is truncated to MAX_KIOSK_ID_LENGTH."""
        long_id = "k" * (MAX_KIOSK_ID_LENGTH + 50)
        message = {
            "type": "session_start",
            "kiosk_id": long_id,
            "kiosk_location": "Floor 1"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert len(result["kiosk_id"]) == MAX_KIOSK_ID_LENGTH
        assert result["kiosk_id"] == long_id[:MAX_KIOSK_ID_LENGTH]
    
    def test_session_start_truncates_long_location(self):
        """Test that kiosk_location is truncated to MAX_KIOSK_LOCATION_LENGTH."""
        long_location = "L" * (MAX_KIOSK_LOCATION_LENGTH + 50)
        message = {
            "type": "session_start",
            "kiosk_id": "kiosk-01",
            "kiosk_location": long_location
        }
        
        result = validate_and_sanitize_input(message)
        
        assert len(result["kiosk_location"]) == MAX_KIOSK_LOCATION_LENGTH
        assert result["kiosk_location"] == long_location[:MAX_KIOSK_LOCATION_LENGTH]
    
    def test_session_start_missing_kiosk_id(self):
        """Test that missing kiosk_id raises ValidationError."""
        message = {
            "type": "session_start",
            "kiosk_location": "Floor 1"
        }
        
        with pytest.raises(ValidationError, match="kiosk_id"):
            validate_and_sanitize_input(message)
    
    def test_session_start_missing_kiosk_location(self):
        """Test that missing kiosk_location raises ValidationError."""
        message = {
            "type": "session_start",
            "kiosk_id": "kiosk-01"
        }
        
        with pytest.raises(ValidationError, match="kiosk_location"):
            validate_and_sanitize_input(message)
    
    def test_session_start_empty_kiosk_id(self):
        """Test that empty kiosk_id raises ValidationError."""
        message = {
            "type": "session_start",
            "kiosk_id": "   ",
            "kiosk_location": "Floor 1"
        }
        
        with pytest.raises(ValidationError, match="non-empty"):
            validate_and_sanitize_input(message)
    
    def test_valid_text_input(self):
        """Test valid text_input message."""
        message = {
            "type": "text_input",
            "text": "Where is the cafeteria?",
            "lang": "en"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["type"] == "text_input"
        assert result["text"] == "Where is the cafeteria?"
        assert result["lang"] == "en"
    
    def test_text_input_default_lang(self):
        """Test that text_input defaults to 'auto' language."""
        message = {
            "type": "text_input",
            "text": "Where is the cafeteria?"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["lang"] == "auto"
    
    def test_text_input_strips_whitespace(self):
        """Test that text_input strips leading/trailing whitespace."""
        message = {
            "type": "text_input",
            "text": "  Where is the cafeteria?  ",
            "lang": "en"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["text"] == "Where is the cafeteria?"
    
    def test_text_input_exceeds_max_length(self):
        """Test that text exceeding MAX_TEXT_LENGTH raises ValidationError."""
        long_text = "a" * (MAX_TEXT_LENGTH + 1)
        message = {
            "type": "text_input",
            "text": long_text,
            "lang": "en"
        }
        
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_and_sanitize_input(message)
    
    def test_text_input_at_max_length(self):
        """Test that text at exactly MAX_TEXT_LENGTH is valid."""
        max_text = "a" * MAX_TEXT_LENGTH
        message = {
            "type": "text_input",
            "text": max_text,
            "lang": "en"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert len(result["text"]) == MAX_TEXT_LENGTH
    
    def test_text_input_empty_text(self):
        """Test that empty text raises ValidationError."""
        message = {
            "type": "text_input",
            "text": "   ",
            "lang": "en"
        }
        
        with pytest.raises(ValidationError, match="non-empty"):
            validate_and_sanitize_input(message)
    
    def test_text_input_missing_text(self):
        """Test that missing text field raises ValidationError."""
        message = {
            "type": "text_input",
            "lang": "en"
        }
        
        with pytest.raises(ValidationError, match="text"):
            validate_and_sanitize_input(message)
    
    def test_text_input_invalid_lang(self):
        """Test that invalid lang value raises ValidationError."""
        message = {
            "type": "text_input",
            "text": "Hello",
            "lang": "fr"
        }
        
        with pytest.raises(ValidationError, match="lang must be"):
            validate_and_sanitize_input(message)
    
    def test_text_input_japanese(self):
        """Test text_input with Japanese text."""
        message = {
            "type": "text_input",
            "text": "カフェテリアはどこですか？",
            "lang": "ja"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["text"] == "カフェテリアはどこですか？"
        assert result["lang"] == "ja"
    
    def test_valid_interrupt(self):
        """Test valid interrupt message."""
        message = {
            "type": "interrupt"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["type"] == "interrupt"
    
    def test_interrupt_with_extra_fields(self):
        """Test that interrupt message ignores extra fields."""
        message = {
            "type": "interrupt",
            "extra_field": "ignored"
        }
        
        result = validate_and_sanitize_input(message)
        
        assert result["type"] == "interrupt"
        assert "extra_field" not in result
    
    def test_missing_type_field(self):
        """Test that missing type field raises ValidationError."""
        message = {
            "kiosk_id": "kiosk-01"
        }
        
        with pytest.raises(ValidationError, match="type"):
            validate_and_sanitize_input(message)
    
    def test_unknown_message_type(self):
        """Test that unknown message type raises ValidationError."""
        message = {
            "type": "unknown_type"
        }
        
        with pytest.raises(ValidationError, match="Unknown message type"):
            validate_and_sanitize_input(message)
    
    def test_non_dict_message(self):
        """Test that non-dict message raises ValidationError."""
        message = "not a dict"
        
        with pytest.raises(ValidationError, match="JSON object"):
            validate_and_sanitize_input(message)
    
    def test_none_message(self):
        """Test that None message raises ValidationError."""
        with pytest.raises(ValidationError, match="JSON object"):
            validate_and_sanitize_input(None)


class TestValidateAudioLength:
    """Test suite for validate_audio_length function."""
    
    def test_valid_audio_length(self):
        """Test that valid audio length passes validation."""
        # 5 seconds of audio at 16kHz, PCM16
        audio_bytes = b"\x00\x00" * (16000 * 5)
        
        # Should not raise
        validate_audio_length(audio_bytes, sample_rate=16000)
    
    def test_audio_at_max_duration(self):
        """Test that audio at exactly max duration passes."""
        # 30 seconds of audio at 16kHz, PCM16
        audio_bytes = b"\x00\x00" * (16000 * MAX_AUDIO_DURATION_SECONDS)
        
        # Should not raise
        validate_audio_length(audio_bytes, sample_rate=16000)
    
    def test_audio_exceeds_max_duration(self):
        """Test that audio exceeding max duration raises ValidationError."""
        # 31 seconds of audio at 16kHz, PCM16
        audio_bytes = b"\x00\x00" * (16000 * (MAX_AUDIO_DURATION_SECONDS + 1))
        
        with pytest.raises(ValidationError, match="exceeds maximum"):
            validate_audio_length(audio_bytes, sample_rate=16000)
    
    def test_audio_slightly_over_max(self):
        """Test that audio slightly over max duration raises ValidationError."""
        # 30.5 seconds of audio at 16kHz, PCM16
        audio_bytes = b"\x00\x00" * int(16000 * 30.5)
        
        with pytest.raises(ValidationError, match="exceeds maximum"):
            validate_audio_length(audio_bytes, sample_rate=16000)
    
    def test_empty_audio(self):
        """Test that empty audio passes validation."""
        audio_bytes = b""
        
        # Should not raise (0 seconds is valid)
        validate_audio_length(audio_bytes, sample_rate=16000)
    
    def test_short_audio(self):
        """Test that very short audio passes validation."""
        # 0.1 seconds of audio
        audio_bytes = b"\x00\x00" * int(16000 * 0.1)
        
        # Should not raise
        validate_audio_length(audio_bytes, sample_rate=16000)


class TestRateLimiter:
    """Test suite for RateLimiter class."""
    
    @pytest.mark.anyio
    async def test_first_request_allowed(self):
        """Test that first request is always allowed."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        result = await limiter.check_rate_limit("kiosk-01")
        
        assert result is True
    
    @pytest.mark.anyio
    async def test_requests_within_limit(self):
        """Test that requests within limit are allowed."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        # Make 10 requests (at limit)
        for i in range(10):
            result = await limiter.check_rate_limit("kiosk-01")
            assert result is True, f"Request {i+1} should be allowed"
    
    @pytest.mark.anyio
    async def test_request_exceeds_limit(self):
        """Test that request exceeding limit is blocked."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        # Make 10 requests (at limit)
        for _ in range(10):
            await limiter.check_rate_limit("kiosk-01")
        
        # 11th request should be blocked
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is False
    
    @pytest.mark.anyio
    async def test_multiple_kiosks_independent(self):
        """Test that different kiosks have independent rate limits."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        
        # Kiosk 1: Make 5 requests (at limit)
        for _ in range(5):
            result = await limiter.check_rate_limit("kiosk-01")
            assert result is True
        
        # Kiosk 1: 6th request blocked
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is False
        
        # Kiosk 2: First request allowed (independent limit)
        result = await limiter.check_rate_limit("kiosk-02")
        assert result is True
    
    @pytest.mark.anyio
    async def test_window_reset_after_expiry(self):
        """Test that rate limit resets after window expires."""
        limiter = RateLimiter(max_requests=3, window_seconds=1)
        
        # Make 3 requests (at limit)
        for _ in range(3):
            await limiter.check_rate_limit("kiosk-01")
        
        # 4th request blocked
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is False
        
        # Wait for window to expire
        await asyncio.sleep(1.1)
        
        # Request should be allowed after window reset
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is True
    
    @pytest.mark.anyio
    async def test_reset_kiosk(self):
        """Test that reset_kiosk clears rate limit for specific kiosk."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        
        # Make 3 requests (at limit)
        for _ in range(3):
            await limiter.check_rate_limit("kiosk-01")
        
        # 4th request blocked
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is False
        
        # Reset kiosk
        await limiter.reset_kiosk("kiosk-01")
        
        # Request should be allowed after reset
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is True
    
    @pytest.mark.anyio
    async def test_reset_nonexistent_kiosk(self):
        """Test that resetting nonexistent kiosk doesn't raise error."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        # Should not raise
        await limiter.reset_kiosk("nonexistent-kiosk")
    
    @pytest.mark.anyio
    async def test_concurrent_requests(self):
        """Test that rate limiter handles concurrent requests correctly."""
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        # Make 10 concurrent requests
        tasks = [
            limiter.check_rate_limit("kiosk-01")
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)
        
        # All 10 should be allowed
        assert all(results)
        
        # 11th request should be blocked
        result = await limiter.check_rate_limit("kiosk-01")
        assert result is False
    
    @pytest.mark.anyio
    async def test_custom_limits(self):
        """Test rate limiter with custom limits."""
        limiter = RateLimiter(max_requests=2, window_seconds=5)
        
        # Make 2 requests (at limit)
        assert await limiter.check_rate_limit("kiosk-01") is True
        assert await limiter.check_rate_limit("kiosk-01") is True
        
        # 3rd request blocked
        assert await limiter.check_rate_limit("kiosk-01") is False
