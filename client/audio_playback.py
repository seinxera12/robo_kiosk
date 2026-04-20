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

logger = logging.getLogger(__name__)


class AudioPlayback:
    """
    Audio playback with WAV decoding and buffering.
    
    Handles WAV audio from TTS engines (CosyVoice, VOICEVOX).
    """
    
    def __init__(
        self,
        sample_rate: int = 22050,  # Default for CosyVoice/VOICEVOX
        channels: int = 1,
        buffer_duration_ms: int = 200
    ):
        """
        Initialize audio playback.
        
        Args:
            sample_rate: Sample rate in Hz (22050 for TTS)
            channels: Number of channels (1 for mono)
            buffer_duration_ms: Buffer duration in milliseconds (200)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_duration_ms = buffer_duration_ms
        
        self.audio_queue = deque()
        self.is_playing = False
        self.stream = None
        
        logger.info(f"Initialized audio playback: {sample_rate}Hz, {channels}ch")
    
    def queue_audio(self, audio_bytes: bytes) -> None:
        """
        Queue audio chunk for playback with enhanced format detection.
        
        Args:
            audio_bytes: WAV audio bytes from TTS engine
        """
        try:
            # Decode WAV bytes
            pcm_data, sample_rate = self._decode_wav(audio_bytes)
            
            if pcm_data is None:
                logger.warning("Failed to decode WAV audio - checking if raw PCM")
                # Some TTS engines might return raw PCM - try to handle it
                if len(audio_bytes) > 0:
                    logger.info("Attempting to play as raw PCM data")
                    self.audio_queue.append(audio_bytes)
                    if not self.is_playing:
                        asyncio.create_task(self._start_playback())
                return
            
            # Update sample rate if different (common with different TTS engines)
            if sample_rate != self.sample_rate:
                logger.info(f"Updating sample rate from {self.sample_rate} to {sample_rate}")
                self.sample_rate = sample_rate
                # Stop current playback to reinitialize with new sample rate
                if self.is_playing:
                    self.stop()
            
            self.audio_queue.append(pcm_data)
            
            # Start playback if not already playing
            if not self.is_playing:
                asyncio.create_task(self._start_playback())
                
        except Exception as e:
            logger.error(f"Error queuing audio: {e}", exc_info=True)
    
    def _decode_wav(self, wav_bytes: bytes) -> tuple:
        """
        Decode WAV bytes to PCM data.
        
        Args:
            wav_bytes: WAV file bytes
            
        Returns:
            Tuple of (pcm_data as bytes, sample_rate)
        """
        try:
            wav_buffer = io.BytesIO(wav_bytes)
            
            with wave.open(wav_buffer, 'rb') as wav_file:
                sample_rate = wav_file.getframerate()
                n_channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                n_frames = wav_file.getnframes()
                
                # Read PCM data
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
            logger.error(f"Audio playback error: {e}", exc_info=True)
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
