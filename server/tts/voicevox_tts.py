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
    
    def __init__(self, config, speaker: int = 1):
        """
        Initialize VOICEVOX client.

        Args:
            config: Server config object (or base_url string for backwards compat)
            speaker: Speaker ID (default: 1)
        """
        if isinstance(config, str):
            self.base_url = config
        else:
            self.base_url = getattr(config, "tts_jp_url", "http://localhost:50021")
        self.speaker = speaker
        logger.info(f"Initialized VOICEVOX TTS at {self.base_url}")
    
    async def health_check(self) -> bool:
        """
        Check if VOICEVOX is responsive.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/speakers", timeout=3.0)
                if resp.status_code == 200:
                    logger.debug("VOICEVOX service health check passed")
                    return True
                else:
                    logger.warning(f"VOICEVOX service health check failed: HTTP {resp.status_code}")
                    return False
        except httpx.TimeoutException:
            logger.warning("VOICEVOX health check timed out")
            return False
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
