"""
Audio playback with Opus decoding.

Plays audio received from server with buffer management.
"""

import sounddevice as sd
import numpy as np
import asyncio
from collections import deque
import logging

logger = logging.getLogger(__name__)


class AudioPlayback:
    """
    Audio playback with Opus decoding and buffering.
    
    Maintains 200ms buffer for smooth playback.
    """
    
    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 1,
        buffer_duration_ms: int = 200
    ):
        """
        Initialize audio playback.
        
        Args:
            sample_rate: Sample rate in Hz (48000)
            channels: Number of channels (1 for mono)
            buffer_duration_ms: Buffer duration in milliseconds (200)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_duration_ms = buffer_duration_ms
        
        self.audio_queue = deque()
        self.is_playing = False
        self.stream = None
        
        # TODO: Initialize Opus decoder
        # from server.tts.opus_encoder import OpusDecoder
        # self.opus_decoder = OpusDecoder(sample_rate, channels)
        
        logger.info(f"Initialized audio playback: {sample_rate}Hz, {channels}ch")
    
    def queue_audio(self, audio_bytes: bytes) -> None:
        """
        Queue audio chunk for playback.
        
        Args:
            audio_bytes: Opus-encoded or PCM16 audio bytes
        """
        # TODO: Decode Opus to PCM16
        # pcm_data = self.opus_decoder.decode_frame(audio_bytes)
        pcm_data = audio_bytes  # Placeholder
        
        self.audio_queue.append(pcm_data)
        
        # Start playback if not already playing
        if not self.is_playing:
            asyncio.create_task(self._start_playback())
    
    async def _start_playback(self) -> None:
        """Start audio playback from queue."""
        if self.is_playing:
            return
        
        self.is_playing = True
        logger.debug("Starting audio playback")
        
        try:
            # Open output stream
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.int16
            )
            
            with self.stream:
                while self.audio_queue:
                    # Get next chunk
                    audio_data = self.audio_queue.popleft()
                    
                    # Convert to numpy array
                    audio_np = np.frombuffer(audio_data, dtype=np.int16)
                    
                    # Play audio
                    self.stream.write(audio_np)
                    
                    # Small delay to prevent busy loop
                    await asyncio.sleep(0.01)
                
        except Exception as e:
            logger.error(f"Audio playback error: {e}")
        finally:
            self.is_playing = False
            logger.debug("Audio playback stopped")
    
    def stop(self) -> None:
        """Stop playback immediately and clear queue."""
        self.audio_queue.clear()
        self.is_playing = False
        
        if self.stream:
            self.stream.stop()
        
        logger.debug("Audio playback stopped and queue cleared")
    
    def is_buffer_underrun(self) -> bool:
        """
        Check if buffer is running low.
        
        Returns:
            True if buffer underrun detected
        """
        return len(self.audio_queue) == 0 and self.is_playing
