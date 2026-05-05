"""
KokoClone TTS client — zero-shot voice cloning for Japanese.

Calls the KokoClone microservice (kokoclone/server.py) over HTTP.
The microservice runs in a separate Python 3.12 venv to avoid version
conflicts with the main server (Python 3.11).

Service API:
    POST /synthesize
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
        """
        Initialise the KokoClone TTS client.

        Args:
            config: Server Config dataclass (or any object with the relevant attrs).
        """
        self._url: str = getattr(config, "kokoclone_url", "http://localhost:5003").rstrip("/")
        self._ref_audio: str = getattr(config, "kokoclone_ref_audio", "") or ""
        self._lang: str = "ja"  # KokoClone is used exclusively for Japanese here

        # Validate reference audio path — engine is unusable without it
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
    # Public interface (matches the contract expected by TTSRouter)
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Ping the KokoClone microservice.

        Returns:
            True if the service responds with status 200, False otherwise.
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._url}/health", timeout=_HEALTH_TIMEOUT)
                if resp.status_code == 200:
                    logger.debug("[KokoCloneTTS] health check passed")
                    return True
                logger.warning(f"[KokoCloneTTS] health check HTTP {resp.status_code}")
                return False
        except httpx.TimeoutException:
            logger.warning("[KokoCloneTTS] health check timed out")
            return False
        except Exception as exc:
            logger.warning(f"[KokoCloneTTS] health check failed: {exc}")
            return False

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesise Japanese text using zero-shot voice cloning.

        Sends a POST /synthesize request to the KokoClone microservice and
        yields the returned WAV bytes as a single chunk.  TTSRouter's fallback
        logic treats zero chunks as a service failure and moves to the next
        engine (KokoroJapaneseTTS).

        Args:
            text: Japanese text to synthesise.

        Yields:
            WAV audio bytes (complete response, not chunked).

        Raises:
            Does NOT raise — exceptions are caught and logged so TTSRouter's
            fallback loop can continue to the next engine.
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

        try:
            _t_start = time.perf_counter()
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
                if not wav_bytes:
                    logger.warning("[KokoCloneTTS] service returned empty response body")
                    return

                _round_trip_ms = (time.perf_counter() - _t_start) * 1000
                logger.info(f"[KokoCloneTTS] synthesis_complete round_trip_ms={_round_trip_ms:.1f} response_bytes={len(wav_bytes)}")
                yield wav_bytes

        except httpx.ConnectError as exc:
            logger.error(
                f"[KokoCloneTTS] cannot connect to service at {self._url!r}: {exc} — "
                "is the kokoclone microservice running? "
                "(cd kokoclone && uv run python server.py)"
            )
        except httpx.TimeoutException as exc:
            logger.error(f"[KokoCloneTTS] request timed out: {exc}")
        except httpx.HTTPStatusError as exc:
            logger.error(
                f"[KokoCloneTTS] service returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
        except Exception as exc:
            logger.error(f"[KokoCloneTTS] unexpected error during synthesis: {exc}", exc_info=True)
