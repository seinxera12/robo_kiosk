"""
CosyVoice2 English TTS engine via REST API.

Connects to CosyVoice service running on separate server/container.
"""

from typing import AsyncIterator
import logging
import httpx

logger = logging.getLogger(__name__)


class CosyVoiceTTS:
    """
    CosyVoice2 English TTS engine via REST API.
    
    Connects to CosyVoice service for synthesis.
    """
    
    def __init__(self, config):
        """
        Initialize CosyVoice2 TTS client.

        Args:
            config: Server config object
        """
        self.base_url = getattr(config, "cosyvoice_url", "http://localhost:5002")
        self.timeout = 30.0  # Synthesis can take time
        
        logger.info(f"Initialized CosyVoice2 TTS client at {self.base_url}")
    
    async def health_check(self) -> bool:
        """
        Check if CosyVoice service is healthy.
        
        Returns:
            True if service is ready
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/health", timeout=5.0)
                if resp.status_code == 200:
                    logger.debug("CosyVoice service health check passed")
                    return True
                else:
                    logger.warning(f"CosyVoice service health check failed: HTTP {resp.status_code}")
                    return False
        except httpx.TimeoutException:
            logger.warning("CosyVoice health check timed out")
            return False
        except Exception as e:
            logger.warning(f"CosyVoice health check failed: {e}")
            return False
    
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesize English text to audio via REST API.
        
        Args:
            text: English text to synthesize
            
        Yields:
            WAV audio bytes
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for synthesis")
            return
        
        try:
            logger.debug(f"Synthesizing with CosyVoice service: {text[:50]}...")
            
            async with httpx.AsyncClient() as client:
                # Call synthesis endpoint
                resp = await client.post(
                    f"{self.base_url}/synthesize",
                    json={"text": text},
                    timeout=self.timeout
                )
                resp.raise_for_status()
                
                # Yield WAV bytes
                wav_bytes = resp.content
                if wav_bytes:
                    yield wav_bytes
                    logger.debug(f"CosyVoice synthesis complete: {len(wav_bytes)} bytes")
                else:
                    logger.warning("CosyVoice service returned empty audio")
                    
        except httpx.TimeoutException:
            logger.error(f"CosyVoice synthesis timeout after {self.timeout}s")
        except httpx.HTTPStatusError as e:
            logger.error(f"CosyVoice synthesis HTTP error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"CosyVoice synthesis error: {e}", exc_info=True)
