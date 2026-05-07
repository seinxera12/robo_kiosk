"""
KokoClone TTS client — zero-shot voice cloning for Japanese.

Calls the KokoClone microservice (kokoclone/server.py) over HTTP.
The microservice runs in a separate Python 3.12 venv to avoid version
conflicts with the main server (Python 3.11).

Service API:
    POST /synthesize_stream  (primary — low-latency chunked streaming)
        Body: { "text": "...", "lang": "ja", "reference_audio": "/abs/path.wav" }
        Returns: chunked binary stream of length-prefixed WAV frames.
                 Wire format: 4-byte LE uint32 length + WAV bytes, repeated.
                 First chunk arrives in ~0.5–1 s (one phoneme batch).

    POST /synthesize  (fallback — returns complete WAV after full synthesis)
        Body: { "text": "...", "lang": "ja", "reference_audio": "/abs/path.wav" }
        Returns: audio/wav bytes

    GET /health
        Returns: { "status": "ok", "sample_rate": 24000 }

Configuration (via server Config object or env vars):
    kokoclone_url       — base URL of the microservice (default: http://localhost:5003)
    kokoclone_ref_audio — absolute path to a 3–10 s reference WAV file
    kokoclone_enabled   — bool toggle (default: True)
"""

import logging
import os
import struct
import time
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# Timeouts (seconds)
_HEALTH_TIMEOUT = 3.0
_SYNTH_CONNECT_TIMEOUT = 5.0
_SYNTH_READ_TIMEOUT = 60.0  # voice cloning can take a few seconds on CPU


class KokoCloneTTS:
    """
    HTTP client wrapper around the KokoClone microservice.

    Attributes:
        _url:       Base URL of the running KokoClone service.
        _ref_audio: Absolute path to the reference WAV file used for voice cloning.
        _available: True when both the ref-audio file exists and the service URL is set.
                    TTSRouter checks this flag after __init__ and sets self.kokoclone=None
                    when False, so the engine is never used without a valid reference.
    """

    def __init__(self, config):
        self._url: str = getattr(config, "kokoclone_url", "http://localhost:5003").rstrip("/")
        self._ref_audio: str = getattr(config, "kokoclone_ref_audio", "") or ""
        self._lang: str = "ja"

        if self._ref_audio and os.path.isfile(self._ref_audio):
            self._available = True
            logger.info(
                f"[KokoCloneTTS] initialised — url={self._url!r}, "
                f"ref_audio={self._ref_audio!r}"
            )
        else:
            self._available = False
            if not self._ref_audio:
                logger.warning("[KokoCloneTTS] _available=False — kokoclone_ref_audio is not set")
            else:
                logger.warning(
                    f"[KokoCloneTTS] _available=False — ref audio not found: {self._ref_audio!r}"
                )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._url}/health", timeout=_HEALTH_TIMEOUT)
                return resp.status_code == 200
        except Exception as exc:
            logger.warning(f"[KokoCloneTTS] health check failed: {exc}")
            return False

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesise Japanese text using zero-shot voice cloning.

        Uses the /synthesize_stream endpoint so the first audio chunk arrives
        after the first phoneme batch (~0.5–1 s) rather than waiting for the
        full sentence to finish (~3–7 s).  Falls back to /synthesize if the
        streaming endpoint is unavailable.

        Wire format from /synthesize_stream:
            Repeated: [ 4-byte LE uint32 length ][ WAV bytes of that length ]

        Yields:
            WAV audio bytes for each chunk as it arrives.
        """
        if not text.strip():
            logger.warning("[KokoCloneTTS] synthesize_stream called with empty text — skipping")
            return

        if not self._available:
            logger.warning("[KokoCloneTTS] synthesize_stream called but _available=False — skipping")
            return

        payload = {
            "text": text,
            "lang": self._lang,
            "reference_audio": self._ref_audio,
        }

        logger.info(f"[KokoCloneTTS] synthesising [{self._lang}]: {text[:80]!r}")
        _t_start = time.perf_counter()
        chunks_yielded = 0

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{self._url}/synthesize_stream",
                    json=payload,
                    timeout=httpx.Timeout(
                        connect=_SYNTH_CONNECT_TIMEOUT,
                        read=_SYNTH_READ_TIMEOUT,
                        write=_SYNTH_CONNECT_TIMEOUT,
                        pool=_SYNTH_CONNECT_TIMEOUT,
                    ),
                ) as resp:
                    resp.raise_for_status()

                    # Read length-prefixed WAV frames from the chunked response.
                    # We accumulate raw bytes and parse frames as they arrive.
                    buf = b""
                    async for raw in resp.aiter_bytes(chunk_size=4096):
                        buf += raw
                        # Parse as many complete frames as are available
                        while len(buf) >= 4:
                            (frame_len,) = struct.unpack_from("<I", buf, 0)
                            if len(buf) < 4 + frame_len:
                                break  # wait for more data
                            wav_bytes = buf[4: 4 + frame_len]
                            buf = buf[4 + frame_len:]
                            elapsed = (time.perf_counter() - _t_start) * 1000
                            logger.info(
                                f"[KokoCloneTTS] chunk_{chunks_yielded} "
                                f"elapsed_ms={elapsed:.0f} bytes={len(wav_bytes)}"
                            )
                            chunks_yielded += 1
                            yield wav_bytes

            if chunks_yielded > 0:
                total_ms = (time.perf_counter() - _t_start) * 1000
                logger.info(
                    f"[KokoCloneTTS] stream_complete chunks={chunks_yielded} "
                    f"total_ms={total_ms:.0f}"
                )
                return

        except httpx.ConnectError as exc:
            logger.error(
                f"[KokoCloneTTS] cannot connect to service at {self._url!r}: {exc}"
            )
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # Older server without /synthesize_stream — fall through to
                # the non-streaming fallback below.
                logger.warning(
                    "[KokoCloneTTS] /synthesize_stream not found (404) — "
                    "falling back to /synthesize"
                )
            else:
                logger.error(
                    f"[KokoCloneTTS] /synthesize_stream HTTP {exc.response.status_code}"
                )
                return
        except httpx.TimeoutException as exc:
            logger.error(f"[KokoCloneTTS] stream request timed out: {exc}")
            return
        except Exception as exc:
            logger.error(
                f"[KokoCloneTTS] unexpected error during stream: {exc}", exc_info=True
            )
            return

        # ── Fallback: non-streaming /synthesize ─────────────────────────────
        logger.info("[KokoCloneTTS] using non-streaming /synthesize fallback")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._url}/synthesize",
                    json=payload,
                    timeout=httpx.Timeout(
                        connect=_SYNTH_CONNECT_TIMEOUT,
                        read=_SYNTH_READ_TIMEOUT,
                        write=_SYNTH_CONNECT_TIMEOUT,
                        pool=_SYNTH_CONNECT_TIMEOUT,
                    ),
                )
                resp.raise_for_status()
                wav_bytes = resp.content
                if wav_bytes:
                    _round_trip_ms = (time.perf_counter() - _t_start) * 1000
                    logger.info(
                        f"[KokoCloneTTS] synthesis_complete round_trip_ms={_round_trip_ms:.1f} "
                        f"response_bytes={len(wav_bytes)}"
                    )
                    yield wav_bytes
        except Exception as exc:
            logger.error(f"[KokoCloneTTS] fallback /synthesize failed: {exc}", exc_info=True)
