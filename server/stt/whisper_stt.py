"""
Whisper STT implementation using faster-whisper.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 24.3, 24.4**
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """Result of STT transcription."""
    text: str
    language: Literal["en", "ja"]
    confidence: float
    duration_ms: int


class WhisperSTT:
    """
    Whisper Large V3 Turbo STT wrapper using faster-whisper.
    
    Preconditions:
    - CUDA available on server (or CPU fallback)
    - Model weights downloaded or will be auto-downloaded
    
    Postconditions:
    - Returns transcript, language, confidence
    - Transcription time < 150ms for typical utterances
    
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 24.3, 24.4**
    """
    
    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "int8"
    ):
        """
        Initialize Whisper STT model.
        
        Args:
            model_size: Whisper model size (default: "large-v3-turbo")
            device: Device to run on ("cuda" or "cpu")
            compute_type: Compute precision ("float16" for ≥12GB VRAM, "int8" for <12GB)
        
        **Validates: Requirements 4.1, 4.4, 4.5, 24.3, 24.4**
        """
        logger.info(
            f"Initializing WhisperSTT: model={model_size}, "
            f"device={device}, compute_type={compute_type}"
        )
        
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                num_workers=1
            )
            logger.info("WhisperSTT initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Whisper model: {e}")
            if device == "cuda":
                logger.info("Falling back to CPU...")
                try:
                    self.model = WhisperModel(
                        model_size,
                        device="cpu",
                        compute_type="int8",
                        num_workers=1
                    )
                    logger.info("WhisperSTT initialized on CPU")
                except Exception as e2:
                    logger.error(f"CPU fallback failed: {e2}")
                    raise RuntimeError(f"Cannot initialize Whisper: {e2}")
            else:
                raise RuntimeError(f"Cannot initialize Whisper: {e}")
    
    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio with language detection.
        
        Args:
            audio_bytes: PCM16 audio data (16kHz, mono)
        
        Returns:
            TranscriptionResult with text, language, confidence, and duration
        
        Preconditions:
        - audio_bytes is PCM16 audio data
        - Audio duration > 0.5 seconds
        
        Postconditions:
        - Returns non-empty transcript (or empty string if no speech detected)
        - Language is "en" or "ja"
        - Confidence in range [0.0, 1.0]
        
        Loop Invariants:
        - All segments are processed sequentially
        - Text accumulation preserves order
        
        **Validates: Requirements 4.2, 4.3, 4.6, 4.7, 4.8, 4.9**
        """
        start_time = time.time()
        
        # Convert bytes to numpy array
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float = audio_np.astype(np.float32) / 32768.0

        # STT-BUG-004: secondary guard — if somehow a short clip reaches here,
        # return an empty result rather than letting Whisper hallucinate.
        # 8000 samples = 0.5s at 16kHz.
        if len(audio_float) < 8000:
            logger.warning(
                f"Audio too short for transcription: {len(audio_float)} samples"
            )
            return TranscriptionResult(text="", language="en", confidence=0.0, duration_ms=0)

        # Run transcription in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        segments, info = await loop.run_in_executor(
            None,
            self._transcribe_sync,
            audio_float
        )
        
        # Collect segments
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text)
            # Log no_speech_prob at INFO — values > 0.6 usually mean silence/noise
            # and are the main cause of Whisper hallucinations.
            if segment.no_speech_prob > 0.4:
                logger.warning(
                    f"[Whisper] high no_speech_prob={segment.no_speech_prob:.3f} "
                    f"for segment: {segment.text!r}"
                )
        
        text = " ".join(text_parts).strip()
        
        # Get language and confidence
        # Requirement 4.3: Automatically detect language (English or Japanese)
        # Requirement 4.8: Use Whisper's detected language if confidence ≥0.8
        # Requirement 4.9: Fall back to Unicode scan if confidence <0.8
        from server.lang.detector import detect_language
        language = detect_language(
            text=text,
            whisper_lang=info.language,
            whisper_confidence=info.language_probability,
        )
        confidence = info.language_probability
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        logger.info(
            f"Transcription complete: text='{text[:50]}...', "
            f"language={language}, confidence={confidence:.2f}, "
            f"duration={duration_ms}ms"
        )
        
        return TranscriptionResult(
            text=text,
            language=language,
            confidence=confidence,
            duration_ms=duration_ms
        )
    
    def _transcribe_sync(self, audio_float: np.ndarray):
        """
        Synchronous transcription — runs in thread pool via run_in_executor.
        The generator is fully consumed here so it doesn't escape the thread.
        """
        segments, info = self.model.transcribe(
            audio_float,
            beam_size=1,
            language=None,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=False,  # keep timestamps for debug logging
        )
        # Consume generator fully inside the thread
        segments = list(segments)

        # ------------------------------------------------------------------ #
        # Debug logging — set log level to DEBUG to see full Whisper output.  #
        # All of this is zero-cost at INFO level (logger.isEnabledFor check). #
        # ------------------------------------------------------------------ #
        if logger.isEnabledFor(logging.DEBUG):
            audio_duration_s = len(audio_float) / 16000
            logger.debug(
                f"[Whisper] audio_duration={audio_duration_s:.2f}s  "
                f"detected_lang={info.language}  "
                f"lang_prob={info.language_probability:.3f}  "
                f"all_lang_probs={dict(sorted(info.all_language_probs.items(), key=lambda x: -x[1])[:5])}  "
                f"duration={info.duration:.2f}s  "
                f"duration_after_vad={getattr(info, 'duration_after_vad', 'n/a')}"
            )
            for i, seg in enumerate(segments):
                logger.debug(
                    f"[Whisper] segment[{i}]  "
                    f"[{seg.start:.2f}s → {seg.end:.2f}s]  "
                    f"avg_logprob={seg.avg_logprob:.3f}  "
                    f"no_speech_prob={seg.no_speech_prob:.3f}  "
                    f"compression_ratio={seg.compression_ratio:.2f}  "
                    f"text={seg.text!r}"
                )

        return segments, info
