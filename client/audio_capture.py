"""
Audio capture from microphone.

Captures audio at 16kHz, mono, PCM16 in 32ms frames.

WSL2 note: PortAudio's ALSA backend requires a real-time thread which WSL2
kernel doesn't support (PaErrorCode -9987). We work around this by setting
PULSE_SERVER to the WSLg socket and disabling ALSA's RT scheduling via
ALSA_PCM_CARD env var before opening the stream.
"""

import os
import sounddevice as sd
import numpy as np
import asyncio
from typing import AsyncIterator
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class AudioFrame:
    """32ms PCM16 audio frame — 512 samples at 16kHz."""
    data: bytes  # 1024 bytes = 16kHz * 1ch * 2 bytes * 0.032s
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
        frame_duration_ms: int = 32,   # 32ms = 512 samples — required by Silero VAD at 16kHz
        device = None
    ):
        """
        Initialize audio capture.

        Args:
            sample_rate: Sample rate in Hz (16000)
            channels: Number of channels (1 for mono)
            frame_duration_ms: Frame duration in milliseconds.
                               Must be 32ms at 16kHz (512 samples) for Silero VAD.
        """
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = (sample_rate * frame_duration_ms) // 1000
        
        self._queue: asyncio.Queue | None = None  # created lazily inside the running loop
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
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(frame)
            self.timestamp += self.frame_duration_ms
        except asyncio.QueueFull:
            logger.warning("Audio capture queue full, dropping frame")
    
    def _pick_device(self) -> int:
        """
        Pick the best available input device.

        Priority order (WSL2-friendly):
        1. PulseAudio devices (WSLg compatibility)
        2. Default input device
        3. Any available input device
        """
        try:
            devices = sd.query_devices()
            logger.debug(f"Available audio devices: {len(devices)}")
            
            # Log all devices for debugging
            for i, device in enumerate(devices):
                logger.debug(f"Device {i}: {device['name']} (inputs: {device['max_input_channels']})")
            
            # Try default input device first
            try:
                default_device = sd.default.device[0]  # Input device
                if default_device is not None:
                    device_info = sd.query_devices(default_device)
                    if device_info['max_input_channels'] > 0:
                        logger.info(f"Using default input device: {device_info['name']}")
                        return default_device
            except Exception as e:
                logger.warning(f"Default device check failed: {e}")
            
            # Find first device with input channels
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    logger.info(f"Using input device {i}: {device['name']}")
                    return i
            
            # Fallback to device 0
            logger.warning("No input devices found, using device 0")
            return 0
            
        except Exception as e:
            logger.error(f"Device selection failed: {e}")
            return 0  # Fallback

    async def stream(self) -> AsyncIterator[AudioFrame]:
        """
        Stream audio frames from microphone.

        Yields:
            AudioFrame objects (32ms each)

        Raises:
            RuntimeError: If no usable microphone is found
        """
        device = self._pick_device()

        # Create the queue here, inside the running event loop (not at __init__ time,
        # which may be on a different thread/loop in the PyQt6 QThread setup).
        self._queue = asyncio.Queue()

        # WSL2 workaround: ALSA's RT thread fails with PaErrorCode -9987.
        # Setting PULSE_SERVER points libpulse at WSLg's socket so the ALSA
        # pulse plugin can connect. PA_ALSA_PLUGHW=1 disables hardware-direct
        # access and avoids the RT thread requirement entirely.
        wslg_pulse = "/mnt/wslg/PulseServer"
        if os.path.exists(wslg_pulse) and "PULSE_SERVER" not in os.environ:
            os.environ["PULSE_SERVER"] = f"unix:{wslg_pulse}"
            logger.info(f"WSL2: set PULSE_SERVER={os.environ['PULSE_SERVER']}")
        if "PA_ALSA_PLUGHW" not in os.environ:
            os.environ["PA_ALSA_PLUGHW"] = "1"

        # On WSL2 the ALSA backend raises PaErrorCode -9987 (RT thread timeout).
        # Try the chosen device first; if it fails, walk through all remaining
        # input devices until one succeeds (PulseAudio device usually works).
        devices = sd.query_devices()
        candidates = [device] + [
            i for i, d in enumerate(devices)
            if d["max_input_channels"] > 0 and i != device
        ]

        last_error: Exception = RuntimeError("No audio input device available")
        for candidate in candidates:
            try:
                stream = sd.InputStream(
                    device=candidate,
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=np.float32,
                    blocksize=self.frame_size,
                    callback=self._audio_callback,
                    latency="high",  # avoids RT thread requirement on WSL2
                )
                with stream:
                    logger.info(
                        f"Audio capture started on device {candidate}: "
                        f"{devices[candidate]['name']}"
                    )
                    while True:
                        frame = await self._queue.get()
                        yield frame
                return  # clean exit — don't fall through to next candidate
            except Exception as e:
                logger.warning(f"Device {candidate} failed: {e} — trying next")
                last_error = e
                # Drain any stale frames left in the queue before retrying
                while not self._queue.empty():
                    self._queue.get_nowait()

        logger.error(f"Audio capture failed on all devices: {last_error}")
        raise last_error
