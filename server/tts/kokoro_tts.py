"""
Kokoro-82M English TTS engine (local, in-process).

Kokoro is a lightweight 82M-parameter TTS model that runs entirely in-process
on CPU or CUDA.  It produces high-quality English speech with very low latency
compared to CosyVoice2, making it the preferred English engine.

CosyVoice2 is kept as a fallback for cases where Kokoro is unavailable or
fails (e.g. model not downloaded, CUDA OOM on a small GPU).

Audio output: WAV bytes at 24 kHz, mono, PCM16 — same format as CosyVoice2
so the rest of the pipeline (audio_output_worker → AudioPlayback) needs no
changes.

Dependencies:
    pip install kokoro>=0.9.4 soundfile numpy

Model download (first run):
    The kokoro library downloads the model weights automatically from
    Hugging Face on first use (~330 MB).  Set HF_HOME or TRANSFORMERS_CACHE
    to control the cache location.

Usage:
    engine = KokoroTTS(config)
    async for wav_bytes in engine.synthesize_stream("Hello world."):
        # wav_bytes is a complete WAV file
        ...
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncIterator, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Single-threaded executor — Kokoro's model is not thread-safe.
# Shared across all KokoroTTS instances (there should only be one).
_kokoro_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kokoro")


def _pcm_to_wav(pcm_float32: np.ndarray, sample_rate: int = 24000) -> bytes:
    """
    Convert a float32 PCM array (range [-1, 1]) to WAV bytes (PCM16).

    Args:
        pcm_float32: 1-D float32 numpy array
        sample_rate: Sample rate of the audio

    Returns:
        Complete WAV file as bytes
    """
    # Clip to [-1, 1] to avoid int16 overflow
    pcm_clipped = np.clip(pcm_float32, -1.0, 1.0)
    pcm_int16 = (pcm_clipped * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int16.tobytes())
    buf.seek(0)
    return buf.read()


class KokoroTTS:
    """
    Kokoro-82M English TTS engine.

    Runs the model in a dedicated thread executor so the asyncio event loop
    is never blocked during inference.  Each call to synthesize_stream()
    splits the text into sentences, synthesises them one at a time, and
    yields each sentence's WAV bytes as soon as it is ready — enabling
    sentence-level streaming that matches the pipeline's tts_worker design.

    Attributes:
        voice:       Kokoro voice name (default "af_heart" — American female)
        sample_rate: Output sample rate (24 000 Hz)
        device:      "cuda" or "cpu"
        speed:       Speech rate multiplier (1.0 = normal)
    """

    # Kokoro's native output sample rate
    SAMPLE_RATE = 24_000

    def __init__(self, config):
        """
        Initialise the Kokoro TTS engine.

        Args:
            config: Server Config object.  Reads:
                - kokoro_voice      (str,   default "af_heart")
                - kokoro_speed      (float, default 1.0)
                - kokoro_device     (str,   default "cpu")
                - kokoro_lang       (str,   default "a")   — "a"=American, "b"=British
        """
        self.voice: str = getattr(config, "kokoro_voice", "af_heart")
        self.speed: float = float(getattr(config, "kokoro_speed", 1.0))
        self.device: str = getattr(config, "kokoro_device", "cpu")
        self.lang: str = getattr(config, "kokoro_lang", "a")
        self.sample_rate: int = self.SAMPLE_RATE

        # Lazy-loaded — model is loaded on first synthesis call so startup is fast.
        self._pipeline = None
        self._load_error: Optional[Exception] = None
        self._loaded = False

        logger.info(
            f"KokoroTTS configured: voice={self.voice}, speed={self.speed}, "
            f"device={self.device}, lang={self.lang}"
        )

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model_sync(self) -> None:
        """
        Load the Kokoro pipeline (blocking — runs in executor thread).

        Sets self._pipeline on success, self._load_error on failure.
        """
        if self._loaded:
            return
        try:
            from kokoro import KPipeline  # type: ignore[import]

            logger.info("Loading Kokoro-82M…")
            self._pipeline = KPipeline(
                lang_code=self.lang,
                repo_id="hexgrad/Kokoro-82M",
                device=self.device,
            )
            self._loaded = True
            logger.info(f"Kokoro-82M ready — voice: {self.voice}, device: {self.device}, speed: {self.speed}x")
        except ImportError as exc:
            self._load_error = exc
            logger.error(
                "kokoro package not installed. "
                "Run: pip install kokoro>=0.9.4  (and: pip install misaki[en])"
            )
        except Exception as exc:
            self._load_error = exc
            logger.error(f"Failed to load Kokoro model: {exc}", exc_info=True)

    async def _ensure_loaded(self) -> bool:
        """
        Ensure the model is loaded, loading it in the executor if needed.

        Returns:
            True if the model is ready, False if loading failed.
        """
        if self._loaded:
            return True
        if self._load_error is not None:
            return False
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_kokoro_executor, self._load_model_sync)
        return self._loaded

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Return True if the Kokoro model is (or can be) loaded.

        Does NOT trigger a download — only checks whether the model is
        already in memory or the kokoro package is importable.
        """
        if self._loaded:
            return True
        try:
            import kokoro  # noqa: F401 — just check importability
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def _synthesize_sentence_sync(self, text: str) -> Optional[bytes]:
        """
        Synthesise a single sentence synchronously (runs in executor thread).

        Args:
            text: Text to synthesise (should be a single sentence for low latency)

        Returns:
            WAV bytes, or None on error.
        """
        if self._pipeline is None:
            return None
        try:
            # KPipeline.__call__ returns a generator of (graphemes, phonemes, audio)
            # tuples.  We collect all audio segments for this text chunk and
            # concatenate them into one WAV file.
            audio_segments = []
            for _, _, audio in self._pipeline(
                text,
                voice=self.voice,
                speed=self.speed,
                split_pattern=None,  # we handle splitting ourselves
            ):
                if audio is not None and len(audio) > 0:
                    audio_segments.append(audio)

            if not audio_segments:
                logger.warning(f"Kokoro returned no audio for: {text[:50]!r}")
                return None

            combined = np.concatenate(audio_segments)
            return _pcm_to_wav(combined, self.SAMPLE_RATE)

        except Exception as exc:
            logger.error(f"Kokoro synthesis error: {exc}", exc_info=True)
            return None

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesise text and yield WAV chunks sentence-by-sentence.

        The pipeline's tts_worker already splits the LLM stream at sentence
        boundaries before calling this method, so ``text`` is typically one
        sentence.  We still split internally on common punctuation so that
        very long inputs (e.g. a paragraph flushed at end-of-stream) start
        playing as quickly as possible.

        Args:
            text: Text to synthesise (one or more sentences)

        Yields:
            Complete WAV file bytes for each synthesised segment.
            Each chunk is ready to pass directly to AudioPlayback.queue_audio().
        """
        if not text or not text.strip():
            logger.warning("KokoroTTS.synthesize_stream called with empty text")
            return

        # Ensure model is loaded before we start
        if not await self._ensure_loaded():
            logger.error("Kokoro model not available — skipping synthesis")
            return

        loop = asyncio.get_event_loop()

        # Split into sentences so we can yield audio incrementally for long inputs.
        sentences = _split_sentences(text)
        logger.debug(f"KokoroTTS synthesising {len(sentences)} segment(s): {text[:80]!r}")

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            wav_bytes = await loop.run_in_executor(
                _kokoro_executor,
                self._synthesize_sentence_sync,
                sentence,
            )

            if wav_bytes:
                logger.debug(f"KokoroTTS yielding {len(wav_bytes)} bytes for: {sentence[:40]!r}")
                yield wav_bytes
            else:
                logger.warning(f"KokoroTTS produced no audio for: {sentence[:40]!r}")


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentence-sized chunks for incremental synthesis.

    Uses a simple punctuation-based heuristic that works well for the
    short, clean sentences produced by the LLM.  A proper sentence
    tokeniser (e.g. NLTK punkt) is not worth the extra dependency here.

    Args:
        text: Input text (may contain multiple sentences)

    Returns:
        List of sentence strings (non-empty, stripped)
    """
    import re

    # Split on sentence-ending punctuation followed by whitespace or end-of-string.
    # Keep the punctuation attached to the preceding sentence.
    parts = re.split(r'(?<=[.!?…])\s+', text.strip())

    # Filter out empty strings and very short fragments (< 3 chars)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 3]
