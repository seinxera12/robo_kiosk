"""
Audio playback with WAV decoding.

Thread-safety contract
----------------------
All sounddevice stream operations (open, write, abort, close) run exclusively
inside _playback_executor — a single-threaded ThreadPoolExecutor.  This is
required because PortAudio's ALSA backend is NOT thread-safe: calling abort()
or close() from a different thread while write() is in progress corrupts
internal ALSA state and causes heap corruption / core dumps.

stop() signals intent via:
  1. self._stopped     — a plain bool the executor _write_chunk checks
  2. self._stop_event  — an asyncio.Event the playback loop awaits

The actual stream teardown always happens inside the executor, never from the
calling thread.

The stream reference (self._sd_stream) lives on the instance so that a new
session's _open_stream can close a stale stream left by a previous session
that was interrupted before its finally block ran.
"""

import sounddevice as sd
import numpy as np
import asyncio
import logging
import io
import wave
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Single-threaded executor — ALL sounddevice calls go through this.
_playback_executor = ThreadPoolExecutor(max_workers=1)


class AudioPlayback:
    """
    Audio playback with WAV decoding and buffering.
    Handles WAV audio from TTS engines (CosyVoice, VOICEVOX).
    """

    def __init__(self, sample_rate: int = 22050, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

        self._queue: asyncio.Queue = None
        self.is_playing = False
        self._playback_task = None
        self._stopped = False
        self._stop_event: asyncio.Event = None
        self._loop: asyncio.AbstractEventLoop = None
        self._sd_stream: sd.OutputStream = None   # owned by executor thread only
        self._sd_rate: int = None

        logger.info(f"Initialized audio playback: {sample_rate}Hz, {channels}ch")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def queue_audio(self, audio_bytes: bytes) -> None:
        """Queue a WAV chunk for playback. Called from the worker event loop."""
        try:
            pcm_data, sample_rate = self._decode_wav(audio_bytes)
            if pcm_data is None:
                if audio_bytes:
                    logger.info("WAV decode failed — attempting raw PCM")
                    self._stopped = False
                    self._get_queue().put_nowait((audio_bytes, self.sample_rate))
                    self._ensure_playing()
                return
            self._stopped = False
            self._get_queue().put_nowait((pcm_data, sample_rate))
            self._ensure_playing()
        except Exception as e:
            logger.error(f"Error queuing audio: {e}", exc_info=True)

    def stop(self) -> None:
        """
        Stop playback immediately and clear the queue.

        Safe to call from ANY thread (Qt main thread or worker event loop).
        Does NOT touch the sounddevice stream directly — sets flags and wakes
        the playback loop so it tears down the stream from inside the executor.
        """
        self._stopped = True

        # Drain the queue so no stale chunks play after a new session starts
        q = self._get_queue()
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except asyncio.QueueEmpty:
                break

        # Wake the playback loop immediately (don't wait for the 0.5s timeout)
        loop = self._loop
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._signal_stop)
            except RuntimeError:
                pass

        self.is_playing = False
        logger.debug("Audio playback stop requested")

    def is_buffer_underrun(self) -> bool:
        return self._get_queue().empty() and self.is_playing

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_queue(self) -> asyncio.Queue:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def _signal_stop(self) -> None:
        """Called via call_soon_threadsafe — runs on the worker event loop."""
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._playback_task
        if task and not task.done():
            task.cancel()

    def _ensure_playing(self) -> None:
        """Start the playback loop if it isn't already running."""
        if self.is_playing:
            return
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        self._stop_event = asyncio.Event()
        task = asyncio.create_task(self._playback_loop())
        task.add_done_callback(self._on_task_done)
        self._playback_task = task

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Playback task failed: {exc}", exc_info=exc)

    def _decode_wav(self, wav_bytes: bytes) -> tuple:
        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, 'rb') as wf:
                sr = wf.getframerate()
                pcm = wf.readframes(wf.getnframes())
                logger.debug(f"Decoded WAV: {sr}Hz, {len(pcm)} bytes")
                return pcm, sr
        except Exception as e:
            logger.debug(f"WAV decode error: {e}")
            return None, None

    # ------------------------------------------------------------------
    # Executor functions — ONLY called via run_in_executor
    # These run on the single _playback_executor thread, never concurrently.
    # ------------------------------------------------------------------

    def _exec_open_stream(self, rate: int) -> None:
        """Close any existing stream and open a new one at the given rate."""
        if self._sd_stream is not None:
            try:
                self._sd_stream.abort()
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None
        s = sd.OutputStream(samplerate=rate, channels=self.channels, dtype=np.int16)
        s.start()
        self._sd_stream = s
        self._sd_rate = rate
        logger.debug(f"Opened audio stream at {rate}Hz")

    def _exec_write_chunk(self, data: bytes) -> None:
        """
        Write one PCM chunk in small frames, checking _stopped between each.

        sounddevice's blocking write() plays the entire buffer before returning —
        for a 2-second TTS sentence that means 2 seconds of audio after stop()
        is called.  Writing in 20ms sub-frames lets us bail within one frame
        (~20ms) of a stop request, which is imperceptible to the user.
        """
        if self._stopped or self._sd_stream is None:
            return

        audio_np = np.frombuffer(data, dtype=np.int16)
        # 20ms of samples at the current stream rate
        frame_samples = int(self._sd_rate * 0.02) if self._sd_rate else 441

        offset = 0
        total = len(audio_np)
        while offset < total:
            if self._stopped or self._sd_stream is None:
                return
            end = min(offset + frame_samples, total)
            frame = audio_np[offset:end]
            try:
                self._sd_stream.write(frame)
            except Exception as e:
                logger.debug(f"Stream write error (likely after stop): {e}")
                return
            offset = end

    def _exec_close_stream(self) -> None:
        """Abort and close the current stream. Safe to call when stream is None."""
        s = self._sd_stream
        if s is None:
            return
        self._sd_stream = None
        self._sd_rate = None
        try:
            s.abort()
            s.close()
        except Exception as e:
            logger.debug(f"Stream close error: {e}")

    # ------------------------------------------------------------------
    # Playback loop
    # ------------------------------------------------------------------

    async def _playback_loop(self) -> None:
        """
        Consume audio chunks from the queue and play them via sounddevice.

        All sounddevice calls go through _playback_executor so they are
        serialised on a single thread and never race with each other or with
        the Qt main thread.
        """
        if self.is_playing:
            return

        self.is_playing = True
        self._stopped = False
        loop = asyncio.get_event_loop()
        self._loop = loop
        queue = self._get_queue()
        stop_event = self._stop_event

        logger.debug("Playback loop started")
        try:
            while not self._stopped:
                # Wait for either a new chunk or a stop signal (0.5s idle timeout)
                get_fut = asyncio.ensure_future(queue.get())
                stop_fut = asyncio.ensure_future(stop_event.wait())

                done, pending = await asyncio.wait(
                    {get_fut, stop_fut},
                    timeout=0.5,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

                if not done:
                    # Idle timeout — nothing queued, exit cleanly
                    break

                if stop_fut in done:
                    break

                if get_fut not in done:
                    break

                try:
                    audio_data, chunk_rate = get_fut.result()
                except Exception:
                    break

                if self._stopped:
                    queue.task_done()
                    break

                # Open / reopen stream if sample rate changed
                if chunk_rate != self._sd_rate:
                    await loop.run_in_executor(
                        _playback_executor, self._exec_open_stream, chunk_rate
                    )

                if self._stopped:
                    queue.task_done()
                    break

                await loop.run_in_executor(
                    _playback_executor, self._exec_write_chunk, audio_data
                )
                queue.task_done()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Playback loop error: {e}", exc_info=True)
        finally:
            # Close the stream from inside the executor.
            # _exec_open_stream in a new session will also close any stale
            # stream, so this is belt-and-suspenders.
            await loop.run_in_executor(_playback_executor, self._exec_close_stream)
            self.is_playing = False
            logger.debug("Playback loop stopped")
