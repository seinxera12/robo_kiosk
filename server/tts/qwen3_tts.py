"""
Qwen3 TTS engine backed by a vLLM-Omni WebSocket streaming endpoint.

The vLLM-Omni server must be started with:
    vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --port 8001 --async-chunk

Audio output: WAV bytes at 24 kHz, mono, PCM16 — same format as all other engines.
"""

import asyncio
import io
import json
import logging
import wave
from typing import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


def _pcm_to_wav(pcm_bytes: bytes) -> bytes | None:
    """
    Wrap raw int16 PCM bytes in a WAV file header.

    Args:
        pcm_bytes: Raw 16-bit signed PCM audio at 24 kHz, mono.
                   This is the direct output of the vLLM-Omni server —
                   NOT float32 like Kokoro's output.

    Returns:
        Complete WAV file bytes, or None if pcm_bytes is empty.

    Audio parameters (fixed):
        channels:   1  (mono)
        sampwidth:  2  (16-bit = 2 bytes per sample)
        framerate:  24000 Hz
    """
    if not pcm_bytes:
        return None

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class Qwen3TTSEngine:
    """
    Async TTS engine backed by a vLLM-Omni WebSocket streaming endpoint.

    Implements the same synthesize_stream / health_check interface as
    KokoroTTS and KokoCloneTTS so TTSRouter can treat it identically.

    Audio output: WAV bytes at 24 kHz, mono, PCM16 — same as all other engines.
    """

    def __init__(self, config) -> None:
        """
        Store configuration. No I/O is performed at construction time.

        Args:
            config: Server Config object with qwen3_tts_* fields.
        """
        self._enabled: bool = getattr(config, "qwen3_tts_enabled", False)
        self._ws_url: str = getattr(config, "qwen3_tts_ws_url", "ws://localhost:8001/v1/audio/speech/stream")
        self._voice: str = getattr(config, "qwen3_tts_voice", "Ono_Anna")
        self._language: str = getattr(config, "qwen3_tts_language", "ja")

    async def health_check(self) -> bool:
        """
        Return True if the vLLM-Omni WebSocket endpoint is reachable.

        Opens a WebSocket connection with a 3-second timeout, closes it
        immediately, and returns True.  Returns False on any exception or
        when qwen3_tts_enabled is False.

        Returns:
            bool: True = endpoint reachable, False = disabled or unreachable.
        """
        if not self._enabled:
            return False
        try:
            async with websockets.connect(self._ws_url, open_timeout=3.0):
                pass
            return True
        except Exception as exc:
            logger.debug(f"Qwen3TTSEngine.health_check failed: {exc}")
            return False

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesise text via the vLLM-Omni WebSocket endpoint.

        Follows the vLLM-Omni session protocol:
          1. Open WebSocket connection
          2. Send session.config (voice, language, stream_audio, response_format)
          3. Send input.text
          4. Send input.end
          5. Receive binary frames (PCM16) → wrap in WAV header → yield
          6. Receive JSON frames → handle audio.done, log others
          7. Stop on ConnectionClosed (normal completion)

        Guards:
          - If qwen3_tts_enabled is False: yield nothing, return immediately.
          - If text.strip() is empty: log warning, yield nothing, return.
          - On connection error: log error, yield nothing (no exception raised).
          - On asyncio.CancelledError: propagate immediately (do NOT suppress).

        Args:
            text: Text to synthesise (one sentence, as provided by tts_worker).

        Yields:
            bytes: Complete WAV file (header + PCM16 data) for each PCM chunk
                   received from the server. Empty PCM frames are discarded.
        """
        if not self._enabled:
            return

        if not text.strip():
            logger.warning("Qwen3TTSEngine.synthesize_stream: empty/whitespace text, skipping")
            return

        chunk_queue: asyncio.Queue = asyncio.Queue()
        _run_task = None

        async def _run():
            try:
                async with websockets.connect(self._ws_url) as ws:
                    async def sender():
                        session_config = {
                            "type": "session.config",
                            "voice": self._voice,
                            "task_type": "CustomVoice",
                            "language": self._language,
                            "split_granularity": "sentence",
                            "stream_audio": True,
                            "response_format": "pcm",
                        }
                        await ws.send(json.dumps(session_config))

                        input_text = {"type": "input.text", "text": text}
                        await ws.send(json.dumps(input_text))

                        input_end = {"type": "input.end"}
                        await ws.send(json.dumps(input_end))

                    async def receiver():
                        try:
                            async for message in ws:
                                if isinstance(message, bytes):
                                    wav = _pcm_to_wav(message)
                                    if wav is not None:
                                        await chunk_queue.put(wav)
                                else:
                                    try:
                                        data = json.loads(message)
                                        msg_type = data.get("type", "")
                                        if msg_type == "audio.done":
                                            logger.debug("Qwen3TTSEngine: received audio.done")
                                        else:
                                            logger.debug(f"Qwen3TTSEngine: unknown message type: {msg_type!r}")
                                    except json.JSONDecodeError:
                                        logger.debug(f"Qwen3TTSEngine: non-JSON text message: {message!r}")
                        except ConnectionClosed:
                            pass  # Normal completion

                    await asyncio.gather(sender(), receiver())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Qwen3TTSEngine: connection error: {exc}", exc_info=True)
            finally:
                await chunk_queue.put(None)  # sentinel

        try:
            _run_task = asyncio.ensure_future(_run())
            while True:
                chunk = await chunk_queue.get()
                if chunk is None:
                    break
                yield chunk
        except asyncio.CancelledError:
            raise
        finally:
            if _run_task is not None and not _run_task.done():
                _run_task.cancel()
                try:
                    await _run_task
                except (asyncio.CancelledError, Exception):
                    pass
