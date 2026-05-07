"""
TTS router for language-based engine selection.

English routing (in priority order):
  1. Kokoro-82M  -- local, fast, high-quality English TTS

Japanese routing (in priority order):
  1. KokoCloneTTS        -- zero-shot voice cloning (when configured)
  2. Kokoro-82M Japanese -- local, fast, in-process Japanese TTS
"""

from typing import Literal, AsyncIterator
import logging
import asyncio

logger = logging.getLogger(__name__)


class TTSRouter:
    """
    TTS engine router based on language.

    Routes:
    - English  -> Kokoro-82M
    - Japanese -> KokoCloneTTS (primary, when configured) -> Kokoro-82M JP
    """

    def __init__(self, config):
        """
        Initialise TTS engines.

        All engines are initialised with graceful fallback -- a failure to
        load one engine does not prevent the others from working.

        Args:
            config: Server Config object
        """
        self.config = config

        # ---- English engine -------------------------------------------------
        # Primary: Kokoro-82M (local, in-process)
        try:
            from server.tts.kokoro_tts import KokoroTTS
            self.kokoro = KokoroTTS(config)
            logger.info("KokoroTTS initialised (English primary)")
        except Exception as exc:
            logger.warning(f"Failed to initialise KokoroTTS: {exc}")
            self.kokoro = None

        # ---- Japanese engines -----------------------------------------------
        # Primary: KokoCloneTTS (zero-shot voice cloning) -- when enabled and configured
        kokoclone_enabled = getattr(config, "kokoclone_enabled", False)
        kokoclone_ref_audio = getattr(config, "kokoclone_ref_audio", None)
        logger.info(
            f"[KokoClone] config check -- "
            f"kokoclone_enabled={kokoclone_enabled!r}, "
            f"kokoclone_ref_audio={kokoclone_ref_audio!r}"
        )
        if kokoclone_enabled and kokoclone_ref_audio:
            try:
                from server.tts.kokoclone_tts import KokoCloneTTS
                self.kokoclone = KokoCloneTTS(config)
                # Only keep the engine if it is actually available (ref audio exists).
                if not self.kokoclone._available:
                    logger.warning(
                        "[KokoClone] engine initialised but _available=False "
                        "(ref audio missing) -- setting to None so KokoroJP is used"
                    )
                    self.kokoclone = None
                else:
                    logger.info(
                        f"[KokoClone] KokoCloneTTS initialised (Japanese primary) -- "
                        f"url={getattr(self.kokoclone, '_url', '?')!r}"
                    )
            except Exception as exc:
                logger.warning(f"[KokoClone] Failed to initialise KokoCloneTTS: {exc}", exc_info=True)
                self.kokoclone = None
        else:
            if not kokoclone_enabled:
                logger.info("[KokoClone] skipped -- kokoclone_enabled is False")
            elif not kokoclone_ref_audio:
                logger.info("[KokoClone] skipped -- KOKOCLONE_REF_AUDIO is not set or empty")
            self.kokoclone = None

        # Secondary: Kokoro-82M Japanese (local, in-process)
        kokoro_jp_enabled = getattr(config, "kokoro_jp_enabled", True)
        if kokoro_jp_enabled:
            try:
                from server.tts.kokoro_tts import KokoroJapaneseTTS
                self.kokoro_jp = KokoroJapaneseTTS(config)
                logger.info("KokoroJapaneseTTS initialised (Japanese secondary)")
            except Exception as exc:
                logger.warning(f"Failed to initialise KokoroJapaneseTTS: {exc}")
                self.kokoro_jp = None
        else:
            logger.info("KokoroJapaneseTTS disabled via config (kokoro_jp_enabled=False)")
            self.kokoro_jp = None

        logger.info("TTSRouter ready")

    # ------------------------------------------------------------------
    # Engine selection
    # ------------------------------------------------------------------

    def get_engine(self, lang: Literal["en", "ja"]):
        """
        Return the best available TTS engine for the given language.

        English priority:  Kokoro
        Japanese priority: KokoCloneTTS -> KokoroJP

        Note: for Japanese, prefer synthesize_stream() on this router directly
        so that per-request fallback works when KokoClone service is down.
        """
        if lang == "en":
            if self.kokoro is not None:
                logger.debug("TTSRouter: English -> KokoroTTS")
                return self.kokoro

            logger.error("TTSRouter: no English TTS engine available")
            return None

        else:  # "ja"
            if self.kokoclone is not None:
                logger.info("TTSRouter: Japanese -> KokoCloneTTS")
                return self.kokoclone

            logger.info(
                "TTSRouter: KokoCloneTTS not available (self.kokoclone is None) -- "
                "trying KokoroJapaneseTTS"
            )
            if self.kokoro_jp is not None:
                logger.info("TTSRouter: Japanese -> KokoroJapaneseTTS")
                return self.kokoro_jp

            logger.error("TTSRouter: no Japanese TTS engine available")
            return None

    async def synthesize_stream(self, text: str, lang: Literal["en", "ja"]):
        """
        Synthesise text with automatic per-request engine fallback.

        For English this is equivalent to get_engine("en").synthesize_stream(text).

        For Japanese, tries KokoCloneTTS first and falls back to KokoroJP if the
        service yields no audio (e.g. KokoClone service is down).

        Yields:
            WAV audio bytes chunks.
        """
        if lang == "en":
            engine = self.get_engine("en")
            if engine is None:
                logger.error("TTSRouter.synthesize_stream: no English engine available")
                return
            async for chunk in engine.synthesize_stream(text):
                yield chunk
            return

        # Japanese -- try each engine in order, fall back if none yielded
        ja_engines = []
        if self.kokoclone is not None:
            ja_engines.append(("KokoCloneTTS", self.kokoclone))
        if self.kokoro_jp is not None:
            ja_engines.append(("KokoroJapaneseTTS", self.kokoro_jp))

        if not ja_engines:
            logger.error("TTSRouter.synthesize_stream: no Japanese engine available")
            return

        for name, engine in ja_engines:
            logger.info(f"TTSRouter: Japanese synthesis attempt -> {name}")
            chunks_yielded = 0
            try:
                async for chunk in engine.synthesize_stream(text):
                    chunks_yielded += 1
                    yield chunk
            except asyncio.CancelledError:
                raise  # always propagate cancellation
            except Exception as exc:
                logger.error(f"TTSRouter: {name} raised exception: {exc}", exc_info=True)

            if chunks_yielded > 0:
                logger.debug(f"TTSRouter: {name} succeeded ({chunks_yielded} chunk(s))")
                return

            # Zero chunks -- engine failed silently (service down, etc.)
            idx = ja_engines.index((name, engine))
            if idx + 1 < len(ja_engines):
                next_name = ja_engines[idx + 1][0]
                logger.warning(
                    f"TTSRouter: {name} produced no audio -- "
                    f"falling back to {next_name}"
                )

        logger.error(
            f"TTSRouter: all Japanese engines failed to produce audio for: {text[:80]!r}"
        )

    # ------------------------------------------------------------------
    # Health helpers
    # ------------------------------------------------------------------

    async def health_check_all(self) -> dict:
        """
        Run health checks on all initialised engines.

        Returns:
            Dict mapping engine name -> bool (True = healthy)
        """
        results: dict[str, bool] = {}

        if self.kokoro is not None:
            results["kokoro"] = await self.kokoro.health_check()
        if self.kokoclone is not None:
            results["kokoclone"] = await self.kokoclone.health_check()
        if self.kokoro_jp is not None:
            results["kokoro_jp"] = await self.kokoro_jp.health_check()

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