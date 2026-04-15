"""
Example integration of validation module with WebSocket endpoint.

This demonstrates how to use the validation functions in server/main.py.
"""

import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

from server.validation import (
    validate_and_sanitize_input,
    validate_audio_length,
    ValidationError,
    RateLimiter,
)

logger = logging.getLogger(__name__)


# Global rate limiter instance (shared across all connections)
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


async def handle_websocket_connection(websocket: WebSocket):
    """
    Example WebSocket handler with validation integration.
    
    This shows how to integrate the validation module into the
    WebSocket endpoint in server/main.py.
    """
    await websocket.accept()
    
    # Track kiosk_id for rate limiting
    kiosk_id = None
    
    try:
        while True:
            # Receive message (binary or text)
            message = await websocket.receive()
            
            if "bytes" in message:
                # Binary audio frame
                audio_data = message["bytes"]
                
                try:
                    # Validate audio length (Requirement 25.3)
                    validate_audio_length(audio_data, sample_rate=16000)
                    
                    # Check rate limit if kiosk_id is known
                    if kiosk_id:
                        if not await rate_limiter.check_rate_limit(kiosk_id):
                            # Rate limit exceeded
                            await websocket.send_json({
                                "type": "error",
                                "code": "rate_limit_exceeded",
                                "message": "Too many requests. Please wait before sending more audio."
                            })
                            continue
                    
                    # Process audio in pipeline
                    logger.info(f"Received valid audio: {len(audio_data)} bytes")
                    # TODO: Send to STT pipeline
                
                except ValidationError as e:
                    # Send error to client
                    await websocket.send_json({
                        "type": "error",
                        "code": "validation_error",
                        "message": str(e)
                    })
                    logger.warning(f"Audio validation failed: {e}")
            
            elif "text" in message:
                # JSON control message
                text_data = message["text"]
                
                try:
                    # Parse JSON
                    raw_message = json.loads(text_data)
                    
                    # Validate and sanitize message (Requirements 25.2, 25.4)
                    validated_message = validate_and_sanitize_input(raw_message)
                    
                    # Handle message by type
                    if validated_message["type"] == "session_start":
                        kiosk_id = validated_message["kiosk_id"]
                        logger.info(
                            f"Session started: {kiosk_id} at "
                            f"{validated_message['kiosk_location']}"
                        )
                        
                        # Send acknowledgment
                        await websocket.send_json({
                            "type": "status",
                            "state": "listening"
                        })
                    
                    elif validated_message["type"] == "text_input":
                        # Check rate limit (Requirement 25.5)
                        if kiosk_id:
                            if not await rate_limiter.check_rate_limit(kiosk_id):
                                await websocket.send_json({
                                    "type": "error",
                                    "code": "rate_limit_exceeded",
                                    "message": "Too many requests. Please wait."
                                })
                                continue
                        
                        logger.info(
                            f"Text input: {validated_message['text'][:50]}... "
                            f"(lang: {validated_message['lang']})"
                        )
                        # TODO: Process text through pipeline
                    
                    elif validated_message["type"] == "interrupt":
                        logger.info("Interrupt received")
                        # TODO: Handle interrupt in pipeline
                
                except json.JSONDecodeError as e:
                    await websocket.send_json({
                        "type": "error",
                        "code": "invalid_json",
                        "message": f"Invalid JSON: {str(e)}"
                    })
                    logger.warning(f"JSON decode error: {e}")
                
                except ValidationError as e:
                    # Send validation error to client
                    await websocket.send_json({
                        "type": "error",
                        "code": "validation_error",
                        "message": str(e)
                    })
                    logger.warning(f"Message validation failed: {e}")
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {kiosk_id}")
        
        # Reset rate limit for this kiosk
        if kiosk_id:
            await rate_limiter.reset_kiosk(kiosk_id)
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason=f"Server error: {str(e)}")
        except Exception:
            pass


# Example usage in server/main.py:
#
# from server.validation import (
#     validate_and_sanitize_input,
#     validate_audio_length,
#     ValidationError,
#     RateLimiter,
# )
#
# # Create global rate limiter
# rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
#
# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     await handle_websocket_connection(websocket)
