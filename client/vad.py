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
        threshold: float = 0.3,  # Lowered from 0.5 for better sensitivity
        sampling_rate: int = 16000,
        min_speech_duration_ms: int = 200,  # Lowered from 250ms
        min_silence_duration_ms: int = 800  # Increased from 500ms for better end detection
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
        try:
            self.model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            logger.info("Silero VAD model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Silero VAD model: {e}")
            logger.info("Attempting to download model...")
            try:
                # Force download if loading fails
                self.model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=True,
                    onnx=False
                )
                logger.info("Silero VAD model downloaded and loaded")
            except Exception as e2:
                logger.error(f"Failed to download VAD model: {e2}")
                raise RuntimeError(f"Cannot initialize VAD: {e2}")
        
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_speech_samples = (min_speech_duration_ms * sampling_rate) // 1000
        self.min_silence_samples = (min_silence_duration_ms * sampling_rate) // 1000
        
        self.is_speaking = False
        self.speech_buffer = bytearray()
        self.silence_counter = 0
        self.speech_counter = 0
        # Rolling pre-speech buffer: keeps the last ~300ms of audio so that
        # the onset of speech is not clipped when is_speaking flips True.
        self._pre_speech_buffer = bytearray()
        self._pre_speech_max_bytes = int(0.3 * sampling_rate * 2)  # 300ms of PCM16
        
        logger.info(f"Initialized Silero VAD with threshold={threshold}")
    
    def reset(self):
        """
        Reset VAD state between manual speak sessions.

        Called before each new Speak press so that stale counters from a
        previous (possibly cancelled) session don't cause an immediate false
        speech_start on the next activation.
        """
        self.is_speaking = False
        self.speech_buffer = bytearray()
        self.silence_counter = 0
        self.speech_counter = 0
        self._pre_speech_buffer = bytearray()
        logger.debug("VAD state reset")

    def flush(self) -> Optional[bytes]:
        """
        Flush whatever audio is currently buffered and reset state.

        Called when the user presses Stop before VAD detects end-of-speech.
        Returns the buffered audio (or None if nothing was captured), then
        resets all state so the next session starts clean.

        Returns:
            bytes if there is buffered speech, None otherwise.
        """
        audio = None
        # Include pre-speech buffer if we never crossed the speech threshold
        combined = bytes(self._pre_speech_buffer) + bytes(self.speech_buffer)
        if combined:
            audio = combined
            logger.info(f"VAD flush: returning {len(audio)} bytes of buffered audio")
        else:
            logger.info("VAD flush: no audio buffered")
        self.reset()
        return audio

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
        
        # Debug logging every 50 frames (about 1 second)
        if hasattr(self, '_debug_counter'):
            self._debug_counter += 1
        else:
            self._debug_counter = 1
            
        if self._debug_counter % 50 == 0:
            logger.debug(f"VAD: prob={speech_prob:.3f}, threshold={self.threshold}, is_speech={is_speech}, speaking={self.is_speaking}")
        
        if is_speech:
            self.speech_counter += len(frame.data) // 2  # samples
            self.silence_counter = 0
            
            # Always accumulate into the pre-speech buffer while not yet speaking
            if not self.is_speaking:
                self._pre_speech_buffer.extend(frame.data)
                # Keep only the last _pre_speech_max_bytes to bound memory
                if len(self._pre_speech_buffer) > self._pre_speech_max_bytes:
                    self._pre_speech_buffer = self._pre_speech_buffer[-self._pre_speech_max_bytes:]

            if not self.is_speaking and self.speech_counter >= self.min_speech_samples:
                # Speech start detected — seed speech_buffer with pre-speech audio
                # so the onset of the utterance is not clipped.
                self.is_speaking = True
                self.speech_buffer = bytearray(self._pre_speech_buffer)
                self._pre_speech_buffer = bytearray()
                logger.info("Speech start detected")
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
                # Keep rolling pre-speech buffer even during silence so we capture
                # the audio just before speech starts.
                self._pre_speech_buffer.extend(frame.data)
                if len(self._pre_speech_buffer) > self._pre_speech_max_bytes:
                    self._pre_speech_buffer = self._pre_speech_buffer[-self._pre_speech_max_bytes:]
            
            if self.is_speaking and self.silence_counter >= self.min_silence_samples:
                # Speech end detected
                self.is_speaking = False
                self.speech_counter = 0
                
                audio_buffer = bytes(self.speech_buffer)
                self.speech_buffer = bytearray()
                self._pre_speech_buffer = bytearray()
                
                logger.info(f"Speech end detected ({len(audio_buffer)} bytes)")
                return VADEvent(
                    event_type="speech_end",
                    audio_buffer=audio_buffer,
                    timestamp_ms=frame.timestamp_ms
                )
        
        return None
