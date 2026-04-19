"""
Audio capture from microphone.

Captures audio at 16kHz, mono, PCM16 in 20ms frames.
"""

import sounddevice as sd
import numpy as np
import asyncio
from typing import AsyncIterator
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class AudioFrame:
    """20ms PCM16 audio frame."""
    data: bytes  # 640 bytes = 16kHz * 1ch * 2 bytes * 0.02s
    timestamp_ms: int
    sample_rate: int = 16000
    channels: int = 1
    
    def to_numpy(self) -> np.ndarray:
        """Convert bytes to numpy array."""
        return np.frombuffer(self.data, dtype=np.int16)


class AudioCapture:
    """
    Audio capture from microphone.
    
    Captures audio at 16kHz, mono, PCM16 format in 20ms frames.
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_duration_ms: int = 20
    ):
        """
        Initialize audio capture.
        
        Args:
            sample_rate: Sample rate in Hz (16000)
            channels: Number of channels (1 for mono)
            frame_duration_ms: Frame duration in milliseconds (20)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = (sample_rate * frame_duration_ms) // 1000
        
        self.queue = asyncio.Queue()
        self.timestamp = 0
        
        logger.info(f"Initialized audio capture: {sample_rate}Hz, {channels}ch, {frame_duration_ms}ms frames")
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for sounddevice stream."""
        if status:
            logger.warning(f"Audio capture status: {status}")
        
        # Convert to PCM16 bytes
        audio_int16 = (indata * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()
        
        # Create frame
        frame = AudioFrame(
            data=audio_bytes,
            timestamp_ms=self.timestamp,
            sample_rate=self.sample_rate,
            channels=self.channels
        )
        
        # Put in queue (non-blocking)
        try:
            self.queue.put_nowait(frame)
            self.timestamp += self.frame_duration_ms
        except asyncio.QueueFull:
            logger.warning("Audio capture queue full, dropping frame")
    
    async def stream(self) -> AsyncIterator[AudioFrame]:
        """
        Stream audio frames from microphone.
        
        Yields:
            AudioFrame objects (20ms each)
            
        Raises:
            Exception: If microphone is unavailable
        """
        try:
            # Open audio stream
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                blocksize=self.frame_size,
                callback=self._audio_callback
            )
            
            with stream:
                logger.info("Audio capture started")
                
                while True:
                    frame = await self.queue.get()
                    yield frame
                    
        except Exception as e:
            logger.error(f"Audio capture failed: {e}")
            raise
