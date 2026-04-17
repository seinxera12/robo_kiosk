"""
CosyVoice2 English TTS engine.

Uses the CosyVoice2-0.5B model for natural English speech synthesis.
Model is loaded from COSYVOICE_MODEL_PATH (HuggingFace repo ID or local path).
Device is controlled by COSYVOICE_DEVICE env var (cuda | cpu).

If the cosyvoice library is not installed, the engine degrades gracefully:
health_check() returns False and synthesize_stream() yields silence,
allowing the rest of the pipeline to continue without crashing.

Installation:
    pip install git+https://github.com/FunAudioLLM/CosyVoice.git
    pip install torch torchaudio

Env vars (read via config object):
    COSYVOICE_MODEL_PATH  — HuggingFace repo ID or local path
                            default: iic/CosyVoice2-0.5B
    COSYVOICE_DEVICE      — cuda | cpu
                            default: cuda
"""

import asyncio
import io
import logging
from typing import AsyncIterator

import numpy as np

logger = logging.getLogger(__name__)

# Silence frame: 0.5s of 22050Hz mono PCM16 (WAVE format)
# Used as fallback when CosyVoice is unavailable
_SILENCE_DURATION_S = 0.5
_SILENCE_SAMPLE_RATE = 22050


def _make_silence_wav(duration_s: float = _SILENCE_DURATION_S,
                      sample_rate: int = _SILENCE_SAMPLE_RATE) -> bytes:
    """Return a minimal valid WAV file containing silence."""
    import struct
    num_samples = int(sample_rate * duration_s)
    pcm = b"\x00\x00" * num_samples          # 16-bit silence
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,           # chunk size
        1,            # PCM
        1,            # mono
        sample_rate,
        sample_rate * 2,
        2,            # block align
        16,           # bits per sample
        b"data",
        data_size,
    )
    return header + pcm


class CosyVoiceTTS:
    """
    CosyVoice2-0.5B English TTS engine.

    Loaded from config.tts_cosyvoice_model (COSYVOICE_MODEL_PATH env var).
    Runs on config.tts_cosyvoice_device (COSYVOICE_DEVICE env var).

    Degrades gracefully when the cosyvoice library is not installed:
    - health_check() → False
    - synthesize_stream() → yields one silence WAV frame so the pipeline
      does not stall waiting for audio that never arrives.
    """

    def __init__(self, config):
        """
        Initialize CosyVoice2 model.

        Args:
            config: Server Config dataclass.
                    Uses config.tts_cosyvoice_model and config.tts_cosyvoice_device.
        """
        self.model_path: str = getattr(config, "tts_cosyvoice_model", "iic/CosyVoice2-0.5B")
        self.device: str = getattr(config, "tts_cosyvoice_device", "cuda")
        self._model = None
        self._available = False

        self._load_model()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """
        Attempt to import and load the CosyVoice2 model.

        Sets self._available = True on success, False on any failure.
        Failures are logged as warnings so the server still starts.
        """
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2  # type: ignore
            logger.info(f"Loading CosyVoice2 from '{self.model_path}' on {self.device} ...")
            self._model = CosyVoice2(self.model_path, load_jit=False, load_trt=False)
            self._available = True
            logger.info("CosyVoice2 loaded successfully")
        except ImportError:
            logger.warning(
                "cosyvoice library not installed — English TTS will produce silence. "
                "Install with: pip install git+https://github.com/FunAudioLLM/CosyVoice.git"
            )
        except Exception as exc:
            logger.warning(f"CosyVoice2 failed to load ({exc}) — English TTS will produce silence.")

    def _synthesize_sync(self, text: str) -> bytes:
        """
        Run CosyVoice2 inference synchronously (called in a thread pool).

        Args:
            text: English text to synthesize.

        Returns:
            WAV bytes of the synthesized audio.
        """
        import soundfile as sf  # type: ignore

        # CosyVoice2 inference_sft uses a built-in speaker preset.
        # 'English' is the default zero-shot English speaker.
        results = list(self._model.inference_sft(text, spk_id="English", stream=False))

        if not results:
            return _make_silence_wav()

        # results[0] is a dict with key 'tts_speech' — a torch.Tensor (1, T)
        audio_tensor = results[0]["tts_speech"]
        sample_rate: int = self._model.sample_rate  # typically 22050

        # Convert tensor → numpy → WAV bytes
        audio_np = audio_tensor.squeeze(0).cpu().numpy().astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.read()

    # ------------------------------------------------------------------
    # Public interface (matches BaseTTSEngine protocol)
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Return True if the CosyVoice2 model is loaded and ready.

        Returns:
            bool: True when available, False when library is missing or load failed.
        """
        return self._available

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesize English text and yield WAV audio bytes.

        Runs the blocking CosyVoice2 inference in a thread pool so the
        asyncio event loop is never blocked.

        Args:
            text: English text to synthesize. Must be non-empty.

        Yields:
            bytes: A single WAV chunk containing the full synthesized audio.
                   (CosyVoice2 non-streaming mode returns one complete buffer.)
                   Falls back to a short silence WAV if the model is unavailable.

        Preconditions:
            - text is a non-empty string
        Postconditions:
            - Always yields at least one bytes object
            - Yielded bytes are valid WAV data
        """
        if not text.strip():
            logger.debug("synthesize_stream called with empty text — skipping")
            return

        if not self._available:
            logger.warning("CosyVoice2 unavailable — yielding silence for: %s", text[:40])
            yield _make_silence_wav()
            return

        try:
            loop = asyncio.get_event_loop()
            wav_bytes: bytes = await loop.run_in_executor(
                None, self._synthesize_sync, text
            )
            yield wav_bytes
        except Exception as exc:
            logger.error("CosyVoice2 synthesis failed: %s", exc, exc_info=True)
            yield _make_silence_wav()
