"""
TTS router for language-based engine selection.

English routing (in priority order):
  1. Kokoro-82M  — local, fast, high-quality English TTS
  2. CosyVoice2  — remote service fallback (slower, heavier)

Japanese routing (in priority order):
  1. VOICEVOX    — local Docker service, natural Japanese
  2. Fish Speech — placeholder fallback (not yet implemented)
"""

from typing import Literal, AsyncIterator
import logging
import asyncio

logger = logging.getLogger(__name__)


class TTSRouter:
    """
    TTS engine router based on language.

    Routes:
    - English  → Kokoro-82M (primary) → CosyVoice2 (fallback)
    - Japanese → VOICEVOX   (primary) → Fish Speech (fallback)
    """

    def __init__(self, config):
        """
        Initialise TTS engines.

        All engines are initialised with graceful fallback — a failure to
        load one engine does not prevent the others from working.

        Args:
            config: Server Config object
        """
        self.config = config

        # ---- English engines ------------------------------------------------
        # Primary: Kokoro-82M (local, in-process)
        try:
            from server.tts.kokoro_tts import KokoroTTS
            self.kokoro = KokoroTTS(config)
            logger.info("KokoroTTS initialised (English primary)")
        except Exception as exc:
            logger.warning(f"Failed to initialise KokoroTTS: {exc}")
            self.kokoro = None

        # Fallback: CosyVoice2 (remote REST service)
        try:
            from server.tts.cosyvoice_tts import CosyVoiceTTS
            self.cosyvoice = CosyVoiceTTS(config)
            logger.info("CosyVoiceTTS initialised (English fallback)")
        except Exception as exc:
            logger.warning(f"Failed to initialise CosyVoiceTTS: {exc}")
            self.cosyvoice = None

        # ---- Japanese engines -----------------------------------------------
        # Primary: VOICEVOX (local Docker service)
        try:
            from server.tts.voicevox_tts import VoicevoxTTS
            self.voicevox = VoicevoxTTS(config)
            logger.info("VoicevoxTTS initialised (Japanese primary)")
        except Exception as exc:
            logger.warning(f"Failed to initialise VoicevoxTTS: {exc}")
            self.voicevox = None

        # Fallback: Fish Speech (placeholder)
        try:
            from server.tts.fish_speech_tts import FishSpeechTTS
            self.fish_speech = FishSpeechTTS(config)
            logger.info("FishSpeechTTS initialised (Japanese fallback)")
        except Exception as exc:
            logger.warning(f"Failed to initialise FishSpeechTTS: {exc}")
            self.fish_speech = None

        logger.info("TTSRouter ready")

    # ------------------------------------------------------------------
    # Engine selection
    # ------------------------------------------------------------------

    def get_engine(self, lang: Literal["en", "ja"]):
        """
        Return the best available TTS engine for the given language.

        English priority:  Kokoro → CosyVoice2
        Japanese priority: VOICEVOX → Fish Speech

        Args:
            lang: Language code ("en" or "ja")

        Returns:
            TTS engine instance with a ``synthesize_stream(text)`` method,
            or None if no engine is available for the language.
        """
        if lang == "en":
            if self.kokoro is not None:
                logger.debug("TTSRouter: English → KokoroTTS")
                return self.kokoro

            if self.cosyvoice is not None:
                logger.info(
                    "TTSRouter: KokoroTTS unavailable — falling back to CosyVoice2 for English"
                )
                return self.cosyvoice

            logger.error("TTSRouter: no English TTS engine available")
            return None

        else:  # "ja"
            if self.voicevox is not None:
                logger.debug("TTSRouter: Japanese → VoicevoxTTS")
                return self.voicevox

            if self.fish_speech is not None:
                logger.info(
                    "TTSRouter: VoicevoxTTS unavailable — falling back to Fish Speech for Japanese"
                )
                return self.fish_speech

            logger.error("TTSRouter: no Japanese TTS engine available")
            return None

    # ------------------------------------------------------------------
    # Health helpers (optional — useful for startup checks / monitoring)
    # ------------------------------------------------------------------

    async def health_check_all(self) -> dict:
        """
        Run health checks on all initialised engines.

        Returns:
            Dict mapping engine name → bool (True = healthy)
        """
        results: dict[str, bool] = {}

        if self.kokoro is not None:
            results["kokoro"] = await self.kokoro.health_check()
        if self.cosyvoice is not None:
            results["cosyvoice"] = await self.cosyvoice.health_check()
        if self.voicevox is not None:
            results["voicevox"] = await self.voicevox.health_check()
        if self.fish_speech is not None:
            results["fish_speech"] = await self.fish_speech.health_check()

        logger.info(f"TTS health: {results}")
        return results


# ---------------------------------------------------------------------------
# Standalone streaming helper (kept for backwards compatibility)
# ---------------------------------------------------------------------------

async def stream_tts_with_sentence_boundaries(
    token_stream: AsyncIterator[str],
    lang: Literal["en", "ja"],
    tts_engine,
    ws_sender,
) -> None:
    """
    Stream TTS audio by synthesising complete sentences.

    This helper is not used by the main pipeline (which handles sentence
    splitting in tts_worker), but is kept for external callers / tests.

    Args:
        token_stream: Async iterator of LLM tokens
        lang:         Language for TTS
        tts_engine:   TTS engine instance
        ws_sender:    WebSocket sender for audio chunks
    """
    SENTENCE_ENDINGS = frozenset(".?!。？！…")
    MIN_SENTENCE_LENGTH = 8

    buffer = ""

    async for token in token_stream:
        buffer += token

        if (
            buffer
            and buffer[-1] in SENTENCE_ENDINGS
            and len(buffer) >= MIN_SENTENCE_LENGTH
        ):
            if tts_engine:
                async for audio_chunk in tts_engine.synthesize_stream(buffer):
                    await ws_sender.send_bytes(audio_chunk)
            buffer = ""

    # Flush remaining buffer
    if buffer.strip() and tts_engine:
        async for audio_chunk in tts_engine.synthesize_stream(buffer):
            await ws_sender.send_bytes(audio_chunk)
