"""
Audio playback with WAV decoding.

Plays audio received from server with buffer management.
"""

import sounddevice as sd
import numpy as np
import asyncio
from collections import deque
import logging
import io
import wave
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Thread pool for blocking sounddevice writes — keeps the event loop free
_playback_executor = ThreadPoolExecutor(max_workers=1)


class AudioPlayback:
    """
    Audio playback with WAV decoding and buffering.
    
    Handles WAV audio from TTS engines (CosyVoice, VOICEVOX).
    """
    
    def __init__(
        self,
        sample_rate: int = 22050,
        channels: int = 1,
        buffer_duration_ms: int = 200
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_duration_ms = buffer_duration_ms
        
        # asyncio.Queue so _start_playback can await new chunks while playing
        self._queue: asyncio.Queue = None  # initialised lazily on first use
        self.is_playing = False
        self.stream = None
        self._playback_task = None
        
        logger.info(f"Initialized audio playback: {sample_rate}Hz, {channels}ch")

    def _get_queue(self) -> asyncio.Queue:
        """Return (or lazily create) the asyncio queue."""
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def queue_audio(self, audio_bytes: bytes) -> None:
        """
        Queue audio chunk for playback.

        Args:
            audio_bytes: WAV audio bytes from TTS engine
        """
        try:
            pcm_data, sample_rate = self._decode_wav(audio_bytes)
            
            if pcm_data is None:
                if len(audio_bytes) > 0:
                    logger.info("WAV decode failed — attempting raw PCM")
                    self._get_queue().put_nowait((audio_bytes, self.sample_rate))
                    self._ensure_playing()
                return
            
            self._get_queue().put_nowait((pcm_data, sample_rate))
            self._ensure_playing()
                
        except Exception as e:
            logger.error(f"Error queuing audio: {e}", exc_info=True)

    def _ensure_playing(self) -> None:
        """Start the playback loop if it isn't already running."""
        if not self.is_playing:
            task = asyncio.create_task(self._start_playback())
            task.add_done_callback(
                lambda t: logger.error(f"Playback task failed: {t.exception()}")
                if t.exception() else None
            )
            self._playback_task = task

    def _decode_wav(self, wav_bytes: bytes) -> tuple:
        try:
            wav_buffer = io.BytesIO(wav_bytes)
            with wave.open(wav_buffer, 'rb') as wav_file:
                sample_rate = wav_file.getframerate()
                n_channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                n_frames = wav_file.getnframes()
                pcm_data = wav_file.readframes(n_frames)
                logger.debug(
                    f"Decoded WAV: {sample_rate}Hz, {n_channels}ch, "
                    f"{sample_width}B, {len(pcm_data)} bytes"
                )
                return pcm_data, sample_rate
        except Exception as e:
            logger.error(f"WAV decode error: {e}", exc_info=True)
            return None, None

    async def _start_playback(self) -> None:
        """
        Persistent playback loop.

        Waits for chunks from the queue and plays them immediately.
        Runs blocking sounddevice writes in a thread executor so the
        event loop stays free to receive the next WAV chunk while audio plays.
        Exits only when the queue has been empty for a short idle timeout.
        """
        if self.is_playing:
            return

        self.is_playing = True
        logger.debug("Playback loop started")

        queue = self._get_queue()
        current_rate = None
        stream = None
        loop = asyncio.get_event_loop()

        def _open_stream(rate: int) -> sd.OutputStream:
            s = sd.OutputStream(samplerate=rate, channels=self.channels, dtype=np.int16)
            s.start()
            return s

        def _close_stream(s: sd.OutputStream) -> None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

        def _write_chunk(s: sd.OutputStream, data: bytes) -> None:
            """Blocking write — runs in thread executor."""
            audio_np = np.frombuffer(data, dtype=np.int16)
            s.write(audio_np)

        try:
            while True:
                try:
                    # Wait up to 0.5s for the next chunk before declaring idle
                    audio_data, chunk_rate = await asyncio.wait_for(
                        queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    # Queue empty long enough — stop the loop
                    break

                # Reopen stream if sample rate changed
                if chunk_rate != current_rate:
                    if stream is not None:
                        await loop.run_in_executor(_playback_executor, _close_stream, stream)
                    current_rate = chunk_rate
                    stream = await loop.run_in_executor(
                        _playback_executor, _open_stream, current_rate
                    )
                    logger.debug(f"Opened audio stream at {current_rate}Hz")

                # Write audio without blocking the event loop
                await loop.run_in_executor(_playback_executor, _write_chunk, stream, audio_data)
                queue.task_done()

        except Exception as e:
            logger.error(f"Audio playback error: {e}", exc_info=True)
        finally:
            if stream is not None:
                await loop.run_in_executor(_playback_executor, _close_stream, stream)
            self.is_playing = False
            logger.debug("Playback loop stopped")

    def stop(self) -> None:
        """Stop playback immediately and clear queue."""
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
        # Drain the queue
        q = self._get_queue()
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except asyncio.QueueEmpty:
                break
        self.is_playing = False
        logger.debug("Audio playback stopped and queue cleared")

    def is_buffer_underrun(self) -> bool:
        return self._get_queue().empty() and self.is_playing
