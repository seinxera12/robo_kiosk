"""
WebSocket message validation and sanitization.

Implements schema validation, input sanitization, and security checks
for all upstream WebSocket messages.

Requirements: 25.2, 25.3, 25.4, 25.5
"""

import logging
from typing import Literal, TypedDict, Union, Any
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

logger = logging.getLogger(__name__)


# Message Type Definitions (Requirements 25.2)
class SessionStartMessage(TypedDict):
    """Session initialization message from client."""
    type: Literal["session_start"]
    kiosk_id: str
    kiosk_location: str


class TextInputMessage(TypedDict):
    """Text input message from client."""
    type: Literal["text_input"]
    text: str
    lang: Literal["auto", "en", "ja"]


class InterruptMessage(TypedDict):
    """Interrupt/barge-in message from client."""
    type: Literal["interrupt"]


# Union type for all valid upstream messages
UpstreamMessage = Union[SessionStartMessage, TextInputMessage, InterruptMessage]


# Validation Constants (Requirements 25.3, 25.4)
MAX_AUDIO_DURATION_SECONDS = 30
MAX_TEXT_LENGTH = 1000
MAX_KIOSK_ID_LENGTH = 64
MAX_KIOSK_LOCATION_LENGTH = 256


class ValidationError(Exception):
    """Raised when message validation fails."""
    pass


def validate_and_sanitize_input(message: Any) -> UpstreamMessage:
    """
    Validate and sanitize incoming WebSocket messages (Requirements 25.2, 25.3, 25.4).
    
    Performs comprehensive validation:
    - Schema validation (correct structure and types)
    - Input length limits (text: 1000 chars, audio: 30s)
    - String sanitization (strip whitespace, limit lengths)
    - Type checking and coercion
    
    Args:
        message: Raw message dict from WebSocket JSON
    
    Returns:
        Validated and sanitized UpstreamMessage
    
    Raises:
        ValidationError: If message fails validation with descriptive error
    
    Preconditions:
    - message is a dict (JSON object)
    
    Postconditions:
    - Returns valid UpstreamMessage if validation passes
    - Raises ValidationError with descriptive message if invalid
    - No side effects on input message
    - All string fields are sanitized (stripped, length-limited)
    
    Loop Invariants:
    - All required fields are checked sequentially
    - Validation state remains consistent
    """
    # Check basic structure
    if not isinstance(message, dict):
        raise ValidationError("Message must be a JSON object")
    
    if "type" not in message:
        raise ValidationError("Message must have 'type' field")
    
    msg_type = message["type"]
    
    # Validate by message type
    if msg_type == "session_start":
        return _validate_session_start(message)
    
    elif msg_type == "text_input":
        return _validate_text_input(message)
    
    elif msg_type == "interrupt":
        return _validate_interrupt(message)
    
    else:
        raise ValidationError(f"Unknown message type: {msg_type}")


def _validate_session_start(message: dict) -> SessionStartMessage:
    """
    Validate session_start message.
    
    Args:
        message: Raw message dict
    
    Returns:
        Validated SessionStartMessage
    
    Raises:
        ValidationError: If validation fails
    """
    # Check required fields
    if "kiosk_id" not in message:
        raise ValidationError("session_start requires 'kiosk_id' field")
    
    if "kiosk_location" not in message:
        raise ValidationError("session_start requires 'kiosk_location' field")
    
    # Sanitize and validate kiosk_id
    kiosk_id = str(message["kiosk_id"]).strip()
    if not kiosk_id:
        raise ValidationError("kiosk_id must be non-empty")
    
    if len(kiosk_id) > MAX_KIOSK_ID_LENGTH:
        logger.warning(f"kiosk_id exceeds max length, truncating: {kiosk_id[:20]}...")
        kiosk_id = kiosk_id[:MAX_KIOSK_ID_LENGTH]
    
    # Sanitize and validate kiosk_location
    kiosk_location = str(message["kiosk_location"]).strip()
    if not kiosk_location:
        raise ValidationError("kiosk_location must be non-empty")
    
    if len(kiosk_location) > MAX_KIOSK_LOCATION_LENGTH:
        logger.warning(f"kiosk_location exceeds max length, truncating")
        kiosk_location = kiosk_location[:MAX_KIOSK_LOCATION_LENGTH]
    
    return SessionStartMessage(
        type="session_start",
        kiosk_id=kiosk_id,
        kiosk_location=kiosk_location
    )


def _validate_text_input(message: dict) -> TextInputMessage:
    """
    Validate text_input message (Requirement 25.4).
    
    Args:
        message: Raw message dict
    
    Returns:
        Validated TextInputMessage
    
    Raises:
        ValidationError: If validation fails
    """
    # Check required fields
    if "text" not in message:
        raise ValidationError("text_input requires 'text' field")
    
    # Sanitize and validate text
    text = str(message["text"]).strip()
    if not text:
        raise ValidationError("text_input text must be non-empty")
    
    # Enforce maximum text length (Requirement 25.4)
    if len(text) > MAX_TEXT_LENGTH:
        raise ValidationError(
            f"text_input text exceeds maximum length of {MAX_TEXT_LENGTH} characters"
        )
    
    # Validate language hint
    lang = message.get("lang", "auto")
    if lang not in ("auto", "en", "ja"):
        raise ValidationError("text_input lang must be 'auto', 'en', or 'ja'")
    
    return TextInputMessage(
        type="text_input",
        text=text,
        lang=lang  # type: ignore
    )


def _validate_interrupt(message: dict) -> InterruptMessage:
    """
    Validate interrupt message.
    
    Args:
        message: Raw message dict
    
    Returns:
        Validated InterruptMessage
    
    Raises:
        ValidationError: If validation fails
    """
    # Interrupt message has no additional fields
    return InterruptMessage(type="interrupt")


def validate_audio_length(audio_bytes: bytes, sample_rate: int = 16000) -> None:
    """
    Validate audio input length (Requirement 25.3).
    
    Ensures audio does not exceed maximum duration to prevent
    memory exhaustion attacks.
    
    Args:
        audio_bytes: Raw PCM16 audio data
        sample_rate: Audio sample rate in Hz (default: 16000)
    
    Raises:
        ValidationError: If audio exceeds maximum duration
    
    Preconditions:
    - audio_bytes is PCM16 audio data (2 bytes per sample)
    - sample_rate > 0
    
    Postconditions:
    - Returns None if audio length is valid
    - Raises ValidationError if audio exceeds MAX_AUDIO_DURATION_SECONDS
    """
    # Calculate audio duration
    # PCM16 = 2 bytes per sample, mono channel
    num_samples = len(audio_bytes) // 2
    duration_seconds = num_samples / sample_rate
    
    # Check against maximum duration (Requirement 25.3)
    if duration_seconds > MAX_AUDIO_DURATION_SECONDS:
        raise ValidationError(
            f"Audio duration ({duration_seconds:.1f}s) exceeds maximum "
            f"of {MAX_AUDIO_DURATION_SECONDS}s"
        )
    
    logger.debug(f"Audio validation passed: {duration_seconds:.2f}s duration")


class RateLimiter:
    """
    Rate limiter for WebSocket requests (Requirement 25.5).
    
    Implements token bucket algorithm with per-kiosk tracking.
    Limits requests to 10 per minute per kiosk to prevent abuse.
    
    Attributes:
        max_requests: Maximum requests per window
        window_seconds: Time window in seconds
        _request_counts: Dict tracking request counts per kiosk
        _window_start: Dict tracking window start times per kiosk
        _lock: Async lock for thread-safe access
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests per window (default: 10)
            window_seconds: Time window in seconds (default: 60)
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        
        # Per-kiosk tracking
        self._request_counts: dict[str, int] = defaultdict(int)
        self._window_start: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
    
    async def check_rate_limit(self, kiosk_id: str) -> bool:
        """
        Check if request is within rate limit (Requirement 25.5).
        
        Args:
            kiosk_id: Unique kiosk identifier
        
        Returns:
            True if request is allowed, False if rate limit exceeded
        
        Preconditions:
        - kiosk_id is non-empty string
        
        Postconditions:
        - Updates request count for kiosk
        - Resets window if expired
        - Returns True if within limit, False otherwise
        
        Loop Invariants:
        - Request counts are non-negative
        - Window start times are in the past
        """
        async with self._lock:
            now = datetime.now()
            
            # Initialize or reset window if expired
            if kiosk_id not in self._window_start:
                self._window_start[kiosk_id] = now
                self._request_counts[kiosk_id] = 0
            
            else:
                window_age = (now - self._window_start[kiosk_id]).total_seconds()
                
                if window_age >= self.window_seconds:
                    # Reset window
                    self._window_start[kiosk_id] = now
                    self._request_counts[kiosk_id] = 0
            
            # Check rate limit
            current_count = self._request_counts[kiosk_id]
            
            if current_count >= self.max_requests:
                logger.warning(
                    f"Rate limit exceeded for kiosk {kiosk_id}: "
                    f"{current_count}/{self.max_requests} requests"
                )
                return False
            
            # Increment count
            self._request_counts[kiosk_id] += 1
            
            logger.debug(
                f"Rate limit check passed for kiosk {kiosk_id}: "
                f"{self._request_counts[kiosk_id]}/{self.max_requests} requests"
            )
            
            return True
    
    async def reset_kiosk(self, kiosk_id: str) -> None:
        """
        Reset rate limit for a specific kiosk.
        
        Useful when a kiosk disconnects or session ends.
        
        Args:
            kiosk_id: Unique kiosk identifier
        """
        async with self._lock:
            if kiosk_id in self._request_counts:
                del self._request_counts[kiosk_id]
            if kiosk_id in self._window_start:
                del self._window_start[kiosk_id]
            
            logger.debug(f"Rate limit reset for kiosk {kiosk_id}")
