"""
Voice Activity Detection using Silero VAD.

Detects speech start/end events for automatic recording.
"""

import torch
import numpy as np
from typing import Optional, Literal
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class VADEvent:
    """Voice Activity Detection event."""
    event_type: Literal["speech_start", "speech_chunk", "speech_end"]
    audio_buffer: Optional[bytes] = None
    timestamp_ms: int = 0


class SileroVAD:
    """
    Silero VAD wrapper for speech detection on CPU.
    
    Detects speech start/end with configurable thresholds.
    """
    
    def __init__(
        self,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 500
    ):
        """
        Initialize Silero VAD.
        
        Args:
            threshold: Speech probability threshold (0.5)
            sampling_rate: Audio sample rate (16000)
            min_speech_duration_ms: Minimum speech duration (250ms)
            min_silence_duration_ms: Minimum silence duration (500ms)
        """
        # Load Silero VAD model (CPU)
        self.model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            onnx=False
        )
        
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_speech_samples = (min_speech_duration_ms * sampling_rate) // 1000
        self.min_silence_samples = (min_silence_duration_ms * sampling_rate) // 1000
        
        self.is_speaking = False
        self.speech_buffer = bytearray()
        self.silence_counter = 0
        self.speech_counter = 0
        
        logger.info(f"Initialized Silero VAD with threshold={threshold}")
    
    def process_frame(self, frame) -> Optional[VADEvent]:
        """
        Process 20ms audio frame through VAD.
        
        Args:
            frame: AudioFrame object
            
        Returns:
            VADEvent if state change occurs, None otherwise
            
        Preconditions:
            - frame.data is 640 bytes (20ms at 16kHz)
            - frame.sample_rate = 16000
            
        Postconditions:
            - Returns VADEvent if state change
            - Updates internal speech buffer
            - Maintains speech/silence counters
        """
        # Convert to tensor — copy to make writable (avoids PyTorch warning)
        audio_np = frame.to_numpy().copy()
        audio_tensor = torch.from_numpy(audio_np).float()
        audio_tensor = audio_tensor / 32768.0  # Normalize to [-1, 1]
        
        # Get VAD probability
        with torch.no_grad():
            speech_prob = self.model(audio_tensor, self.sampling_rate).item()
        
        is_speech = speech_prob > self.threshold
        
        if is_speech:
            self.speech_counter += len(frame.data) // 2  # samples
            self.silence_counter = 0
            
            if not self.is_speaking and self.speech_counter >= self.min_speech_samples:
                # Speech start detected
                self.is_speaking = True
                self.speech_buffer = bytearray(frame.data)
                logger.debug("Speech start detected")
                return VADEvent(
                    event_type="speech_start",
                    timestamp_ms=frame.timestamp_ms
                )
            
            elif self.is_speaking:
                # Continue speech
                self.speech_buffer.extend(frame.data)
                return VADEvent(
                    event_type="speech_chunk",
                    audio_buffer=bytes(frame.data),
                    timestamp_ms=frame.timestamp_ms
                )
        
        else:
            self.silence_counter += len(frame.data) // 2  # samples
            if not self.is_speaking:
                self.speech_counter = 0  # reset pre-speech accumulator on silence
            
            if self.is_speaking and self.silence_counter >= self.min_silence_samples:
                # Speech end detected
                self.is_speaking = False
                self.speech_counter = 0
                
                audio_buffer = bytes(self.speech_buffer)
                self.speech_buffer = bytearray()
                
                logger.debug(f"Speech end detected ({len(audio_buffer)} bytes)")
                return VADEvent(
                    event_type="speech_end",
                    audio_buffer=audio_buffer,
                    timestamp_ms=frame.timestamp_ms
                )
        
        return None
