"""
VOICEVOX Japanese TTS via REST API.

Interfaces with VOICEVOX Docker container for Japanese speech synthesis.
"""

import httpx
import json
from typing import AsyncIterator
import logging

logger = logging.getLogger(__name__)


class VoicevoxTTS:
    """
    VOICEVOX Japanese TTS via REST API.
    
    Uses two-step API: audio_query → synthesis
    """
    
    def __init__(self, base_url: str = "http://voicevox:50021", speaker: int = 1):
        """
        Initialize VOICEVOX client.
        
        Args:
            base_url: VOICEVOX API base URL
            speaker: Speaker ID (default: 1)
        """
        self.base_url = base_url
        self.speaker = speaker
        logger.info(f"Initialized VOICEVOX TTS at {base_url}")
    
    async def health_check(self) -> bool:
        """
        Check if VOICEVOX is responsive.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/speakers", timeout=2.0)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"VOICEVOX health check failed: {e}")
            return False
    
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesize Japanese text to audio.
        
        Args:
            text: Japanese text to synthesize
            
        Yields:
            WAV audio bytes (to be encoded to Opus upstream)
            
        Preconditions:
            - text is non-empty Japanese string
            - VOICEVOX service is healthy
            
        Postconditions:
            - Yields WAV audio bytes
            - Audio matches input text
        """
        async with httpx.AsyncClient() as client:
            # Step 1: Create audio query
            query_resp = await client.post(
                f"{self.base_url}/audio_query",
                params={"text": text, "speaker": self.speaker},
                timeout=5.0
            )
            query_resp.raise_for_status()
            audio_query = query_resp.json()
            
            # Step 2: Synthesize audio
            synthesis_resp = await client.post(
                f"{self.base_url}/synthesis",
                params={"speaker": self.speaker},
                content=json.dumps(audio_query),
                headers={"Content-Type": "application/json"},
                timeout=10.0
            )
            synthesis_resp.raise_for_status()
            
            # Yield WAV bytes
            yield synthesis_resp.content
