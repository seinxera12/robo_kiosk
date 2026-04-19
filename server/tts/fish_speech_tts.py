"""
Fish Speech Japanese TTS fallback.

Placeholder for Fish Speech v1.5 model integration.
Used as fallback when VOICEVOX is unavailable.
"""

from typing import AsyncIterator
import logging

logger = logging.getLogger(__name__)


class FishSpeechTTS:
    """
    Fish Speech v1.5 Japanese TTS fallback.
    
    TODO: Implement when Fish Speech library is available.
    Used as fallback when VOICEVOX is unavailable.
    """
    
    def __init__(self, model_path: str, device: str = "cuda"):
        """
        Initialize Fish Speech model.
        
        Args:
            model_path: Path to model weights
            device: Device for inference ("cuda" or "cpu")
        """
        self.model_path = model_path
        self.device = device
        
        # TODO: Load Fish Speech model
        logger.info(f"Initialized Fish Speech TTS (placeholder)")
    
    async def health_check(self) -> bool:
        """
        Check if model is loaded.
        
        Returns:
            True if model is ready
        """
        # TODO: Implement actual health check
        return False  # Placeholder
    
    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesize Japanese text to audio.
        
        Args:
            text: Japanese text to synthesize
            
        Yields:
            Audio chunks as generated
            
        TODO: Implement actual synthesis
        """
        logger.warning("Fish Speech TTS not yet implemented")
        
        # Placeholder - yield empty bytes
        if False:
            yield b""
