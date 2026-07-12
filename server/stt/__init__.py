"""Speech-to-Text module."""

import logging

from .types import TranscriptionResult
from .text_cleaner import (
    strip_whitespace,
    remove_filler_words,
    restore_punctuation,
    clean_transcript
)

logger = logging.getLogger(__name__)


def __getattr__(name):
    """Lazily expose WhisperSTT so importing this package (e.g. for the remote
    backend) does not require faster-whisper to be installed."""
    if name == "WhisperSTT":
        from .whisper_stt import WhisperSTT
        return WhisperSTT
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_stt(config):
    """
    Construct the STT backend selected by config.

    - "local"  -> WhisperSTT (loads faster-whisper in-process, own VRAM)
    - "remote" -> RemoteWhisperSTT (calls an existing faster-whisper HTTP service)

    Both expose the same ``async transcribe(audio_bytes) -> TranscriptionResult``
    interface, so callers are backend-agnostic.
    """
    backend = getattr(config, "stt_backend", "local").lower()

    if backend == "remote":
        from .remote_whisper_stt import RemoteWhisperSTT
        logger.info("STT backend: remote (%s)", config.stt_remote_url)
        return RemoteWhisperSTT(
            remote_url=config.stt_remote_url,
            model_size=config.stt_model,
        )

    logger.info("STT backend: local (in-process faster-whisper)")
    from .whisper_stt import WhisperSTT
    return WhisperSTT(
        model_size=config.stt_model,
        device=config.stt_device,
        compute_type=config.stt_compute_type,
    )


__all__ = [
    "WhisperSTT",
    "TranscriptionResult",
    "create_stt",
    "strip_whitespace",
    "remove_filler_words",
    "restore_punctuation",
    "clean_transcript"
]
