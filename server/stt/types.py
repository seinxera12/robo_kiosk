"""Shared STT data types (import-light — no model dependencies)."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class TranscriptionResult:
    """Result of STT transcription."""
    text: str
    language: Literal["en", "ja"]
    confidence: float
    duration_ms: int
