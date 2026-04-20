"""
TTS router for language-based engine selection.

Routes English to CosyVoice2 and Japanese to VOICEVOX with fallback.
"""

from typing import Literal, AsyncIterator
import logging
import asyncio

logger = logging.getLogger(__name__)


class TTSRouter:
    """
    TTS engine router based on language.
    
    Routes:
    - English → CosyVoice2
    - Japanese → VOICEVOX (fallback to Fish Speech)
    """
    
    def __init__(self, config):
        """
        Initialize TTS engines.
        
        Args:
            config: Configuration object with TTS settings
        """
        self.config = config
        
        # Initialize engines with graceful fallback
        from server.tts.cosyvoice_tts import CosyVoiceTTS
        from server.tts.voicevox_tts import VoicevoxTTS
        from server.tts.fish_speech_tts import FishSpeechTTS
        
        try:
            self.cosyvoice = CosyVoiceTTS(config)
        except Exception as e:
            logger.warning(f"Failed to initialize CosyVoice TTS: {e}")
            self.cosyvoice = None
        
        try:
            self.voicevox = VoicevoxTTS(config)
        except Exception as e:
            logger.warning(f"Failed to initialize VOICEVOX TTS: {e}")
            self.voicevox = None
        
        try:
            self.fish_speech = FishSpeechTTS(config)
        except Exception as e:
            logger.warning(f"Failed to initialize Fish Speech TTS: {e}")
            self.fish_speech = None
        
        logger.info("Initialized TTS router")
    
    def get_engine(self, lang: Literal["en", "ja"]):
        """
        Get TTS engine for language.
        
        Args:
            lang: Language code ("en" or "ja")
            
        Returns:
            TTS engine instance, or None if unavailable
        """
        if lang == "en":
            # Return CosyVoice2 engine for English
            if self.cosyvoice is not None:
                logger.info("Routing to CosyVoice2 for English")
                return self.cosyvoice
            else:
                logger.warning("CosyVoice2 not available for English TTS")
                return None
        else:
            # Return VOICEVOX for Japanese, fall back to Fish Speech
            if self.voicevox is not None:
                logger.info("Routing to VOICEVOX for Japanese")
                return self.voicevox
            elif self.fish_speech is not None:
                logger.warning("VOICEVOX unavailable — falling back to Fish Speech")
                return self.fish_speech
            else:
                logger.warning("No TTS engine available for Japanese")
                return None


async def stream_tts_with_sentence_boundaries(
    token_stream: AsyncIterator[str],
    lang: Literal["en", "ja"],
    tts_engine,
    ws_sender
) -> None:
    """
    Stream TTS audio by synthesizing complete sentences.
    
    Args:
        token_stream: Async iterator of LLM tokens
        lang: Language for TTS
        tts_engine: TTS engine instance
        ws_sender: WebSocket sender for audio chunks
        
    Preconditions:
        - token_stream is valid async iterator
        - tts_engine is initialized
        
    Postconditions:
        - All tokens processed
        - All complete sentences synthesized
        - Remaining buffer flushed
    """
    SENTENCE_ENDINGS = frozenset('.?!。？！…')
    MIN_SENTENCE_LENGTH = 8
    
    buffer = ""
    
    async for token in token_stream:
        buffer += token
        
        # Check for sentence boundary
        if (buffer and 
            buffer[-1] in SENTENCE_ENDINGS and 
            len(buffer) >= MIN_SENTENCE_LENGTH):
            
            # Synthesize complete sentence
            if tts_engine:
                async for audio_chunk in tts_engine.synthesize_stream(buffer):
                    await ws_sender.send_bytes(audio_chunk)
            
            buffer = ""  # Reset for next sentence
    
    # Flush remaining buffer
    if buffer.strip() and tts_engine:
        async for audio_chunk in tts_engine.synthesize_stream(buffer):
            await ws_sender.send_bytes(audio_chunk)
