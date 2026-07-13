"""
Remote Whisper STT adapter.

Routes transcription to an existing faster-whisper HTTP service instead of
loading the model in-process. Presents the *same* interface as
``WhisperSTT`` (``async transcribe(audio_bytes) -> TranscriptionResult``) so the
pipeline is unchanged.

Target endpoint: OpenAI-compatible ``POST /v1/audio/transcriptions`` returning
``verbose_json``:

    {
      "task": "transcribe",
      "language": "en",
      "text": "...",
      "segments": [ { "no_speech_prob": 0.02, ... }, ... ]
    }

Capabilities preserved vs. the local implementation:
- short-audio guard (<0.5 s) runs client-side, before any network call
- per-segment ``no_speech_prob`` warnings (endpoint returns them in verbose_json)
- en/ja routing via ``detect_language`` (Option A: trust the server's language)

The endpoint returns ``language`` but no ``language_probability``; per the chosen
policy we trust the server's detection (pass confidence=1.0 to detect_language).
"""

import asyncio
import io
import logging
import time
from typing import Optional

import numpy as np
import soundfile as sf

from server.stt.types import TranscriptionResult

logger = logging.getLogger(__name__)

# 16 kHz mono PCM16 is what the pipeline feeds us.
_SAMPLE_RATE = 16000
# 8000 samples = 0.5 s — matches the local guard (STT-BUG-004).
_MIN_SAMPLES = 8000
# Confidence passed to detect_language when trusting the server's language.
_TRUST_CONFIDENCE = 1.0


class RemoteWhisperSTT:
    """faster-whisper HTTP client with the WhisperSTT interface."""

    def __init__(
        self,
        remote_url: str,
        model_size: str = "large-v3",
        timeout: float = 30.0,
    ):
        """
        Args:
            remote_url: Full transcription endpoint URL
                (e.g. http://stt-fastwhisper:8000/v1/audio/transcriptions).
            model_size: Advertised only; the remote service owns the real model.
            timeout: Per-request HTTP timeout in seconds.
        """
        self.remote_url = remote_url
        self.model = model_size
        self.timeout = timeout
        logger.info(
            f"Initialized RemoteWhisperSTT: endpoint={remote_url}, "
            f"model={model_size} (served remotely)"
        )

    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe PCM16 (16 kHz mono) audio via the remote service."""
        start_time = time.time()

        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)

        # Short-audio guard — identical to the local path. Avoids a pointless
        # round-trip and Whisper hallucination on sub-0.5 s clips.
        if len(audio_np) < _MIN_SAMPLES:
            logger.warning(
                f"Audio too short for transcription: {len(audio_np)} samples"
            )
            return TranscriptionResult(text="", language="en", confidence=0.0, duration_ms=0)

        # Build an in-memory WAV — the endpoint expects a file upload, not raw PCM.
        wav_buf = io.BytesIO()
        sf.write(wav_buf, audio_np, _SAMPLE_RATE, format="WAV", subtype="PCM_16")
        wav_bytes = wav_buf.getvalue()

        try:
            response_json = await asyncio.get_event_loop().run_in_executor(
                None, self._post_sync, wav_bytes
            )
        except Exception as e:
            logger.error(f"Remote STT request failed: {e}")
            # Surface as empty transcript rather than crashing the pipeline turn.
            return TranscriptionResult(text="", language="en", confidence=0.0, duration_ms=0)

        text = (response_json.get("text") or "").strip()

        # Per-segment no_speech_prob warnings (verbose_json). Preserved from local.
        for seg in response_json.get("segments") or []:
            nsp = seg.get("no_speech_prob")
            if nsp is not None and nsp > 0.4:
                logger.warning(
                    f"[RemoteWhisper] high no_speech_prob={nsp:.3f} "
                    f"for segment: {seg.get('text')!r}"
                )

        # Language routing — Option A: trust the server's detected language.
        from server.lang.detector import detect_language
        server_lang = response_json.get("language")
        language = detect_language(
            text=text,
            whisper_lang=server_lang,
            whisper_confidence=_TRUST_CONFIDENCE if server_lang else 0.0,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Transcription complete (remote): text='{text[:50]}...', "
            f"language={language}, duration={duration_ms}ms"
        )

        return TranscriptionResult(
            text=text,
            language=language,
            confidence=_TRUST_CONFIDENCE if server_lang else 0.0,
            duration_ms=duration_ms,
        )

    def _post_sync(self, wav_bytes: bytes) -> dict:
        """Blocking multipart POST — runs in the executor thread."""
        import httpx

        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"response_format": "verbose_json"}
        with httpx.Client(timeout=httpx.Timeout(self.timeout)) as client:
            resp = client.post(self.remote_url, files=files, data=data)
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> bool:
        """Best-effort readiness probe against the service /health route."""
        import httpx

        # Derive base URL from the transcription endpoint.
        base = self.remote_url.split("/v1/")[0].rstrip("/")
        try:
            def _ping() -> bool:
                with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                    return client.get(f"{base}/health").status_code == 200
            return await asyncio.get_event_loop().run_in_executor(None, _ping)
        except Exception as e:
            logger.warning(f"Remote STT health check failed: {e}")
            return False
