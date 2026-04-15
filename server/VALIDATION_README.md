# WebSocket Message Validation Module

## Overview

This module implements comprehensive WebSocket message validation and security checks for the voice kiosk chatbot server, fulfilling Requirements 25.2, 25.3, 25.4, and 25.5.

## Files

- **`server/validation.py`**: Core validation module with message schema validation, input sanitization, and rate limiting
- **`server/test_validation.py`**: Comprehensive unit tests (37 tests, all passing)
- **`server/validation_example.py`**: Integration example showing how to use validation in WebSocket handlers

## Features

### 1. Message Schema Validation (Requirement 25.2)

Validates all upstream WebSocket messages against defined schemas:

- **`session_start`**: Requires `kiosk_id` and `kiosk_location`
- **`text_input`**: Requires `text` field, optional `lang` field
- **`interrupt`**: No additional fields required

```python
from server.validation import validate_and_sanitize_input, ValidationError

try:
    validated_msg = validate_and_sanitize_input(raw_message)
    # Process validated message
except ValidationError as e:
    # Handle validation error
    print(f"Validation failed: {e}")
```

### 2. Input Sanitization (Requirements 25.3, 25.4)

Automatically sanitizes and validates input:

- **String fields**: Strips leading/trailing whitespace
- **Length limits**:
  - `kiosk_id`: Max 64 characters (truncated if exceeded)
  - `kiosk_location`: Max 256 characters (truncated if exceeded)
  - `text_input`: Max 1000 characters (raises error if exceeded)
- **Audio length**: Max 30 seconds (raises error if exceeded)

```python
from server.validation import validate_audio_length, ValidationError

try:
    validate_audio_length(audio_bytes, sample_rate=16000)
    # Audio is valid
except ValidationError as e:
    # Audio exceeds 30 seconds
    print(f"Audio too long: {e}")
```

### 3. Rate Limiting (Requirement 25.5)

Implements per-kiosk rate limiting (10 requests/minute):

```python
from server.validation import RateLimiter

# Create rate limiter (shared across connections)
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Check rate limit
if await rate_limiter.check_rate_limit(kiosk_id):
    # Request allowed
    pass
else:
    # Rate limit exceeded
    await websocket.send_json({
        "type": "error",
        "code": "rate_limit_exceeded",
        "message": "Too many requests"
    })
```

## Security Features

1. **Schema Validation**: Rejects malformed messages before processing
2. **Input Length Limits**: Prevents memory exhaustion attacks
3. **Rate Limiting**: Prevents abuse and DoS attacks
4. **String Sanitization**: Removes potentially problematic whitespace
5. **Type Checking**: Ensures all fields have correct types

## Testing

Run the test suite:

```bash
# Run all tests
python -m pytest server/test_validation.py -v

# Run only asyncio tests (exclude trio)
python -m pytest server/test_validation.py -k "not trio" -v
```

### Test Coverage

- **22 tests** for `validate_and_sanitize_input()`:
  - Valid messages (session_start, text_input, interrupt)
  - Whitespace stripping
  - Length truncation
  - Missing/empty fields
  - Invalid types and values
  - Japanese text support

- **6 tests** for `validate_audio_length()`:
  - Valid audio lengths
  - Audio at max duration
  - Audio exceeding max duration
  - Empty and short audio

- **9 tests** for `RateLimiter`:
  - First request allowed
  - Requests within limit
  - Request exceeding limit
  - Multiple kiosks (independent limits)
  - Window reset after expiry
  - Kiosk reset
  - Concurrent requests

## Integration Example

See `server/validation_example.py` for a complete example of integrating validation into the WebSocket endpoint.

Key integration points:

1. **Create global rate limiter** (shared across all connections)
2. **Validate JSON messages** using `validate_and_sanitize_input()`
3. **Validate audio length** using `validate_audio_length()`
4. **Check rate limits** before processing requests
5. **Reset rate limit** when connection closes

## Constants

```python
MAX_AUDIO_DURATION_SECONDS = 30    # Requirement 25.3
MAX_TEXT_LENGTH = 1000              # Requirement 25.4
MAX_KIOSK_ID_LENGTH = 64
MAX_KIOSK_LOCATION_LENGTH = 256
```

## Error Handling

All validation functions raise `ValidationError` with descriptive messages:

```python
try:
    validated = validate_and_sanitize_input(message)
except ValidationError as e:
    # e.args[0] contains human-readable error message
    await websocket.send_json({
        "type": "error",
        "code": "validation_error",
        "message": str(e)
    })
```

## Requirements Mapping

- **Requirement 25.2**: Message schema validation for upstream messages
- **Requirement 25.3**: Audio input length limit (30 seconds max)
- **Requirement 25.4**: Text input length limit (1000 characters max)
- **Requirement 25.5**: Rate limiting (10 requests/minute per kiosk)

## Next Steps

To integrate this module into `server/main.py`:

1. Import validation functions and `RateLimiter`
2. Create global `rate_limiter` instance
3. Add validation calls in WebSocket message handler
4. Handle `ValidationError` exceptions
5. Send error events to client when validation fails

See `server/validation_example.py` for complete integration code.
