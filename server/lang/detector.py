"""
Language detection module with Whisper primary and Unicode fallback.

This module provides language detection for English and Japanese text,
using Whisper STT confidence as the primary method and Unicode block
scanning as a fallback for low-confidence cases.
"""

from typing import Literal, Optional


def detect_from_unicode(text: str) -> Literal["en", "ja"]:
    """
    Fast Japanese detection by Unicode block presence.
    
    Scans text for Japanese characters in Unicode blocks:
    - U+3000-U+9FFF: Hiragana, Katakana, CJK Unified Ideographs
    - U+FF00-U+FFEF: Halfwidth and Fullwidth Forms
    
    Args:
        text: Input text to analyze
    
    Returns:
        "ja" if Japanese character ratio > 0.2, else "en"
    
    Preconditions:
        - text is non-empty string
    
    Postconditions:
        - Returns "ja" if Japanese character ratio > 0.2
        - Returns "en" otherwise
        - No side effects
    
    Loop Invariants:
        - jp_chars count is non-decreasing
        - All characters are examined exactly once
    """
    jp_chars = sum(
        1 for c in text 
        if '\u3000' <= c <= '\u9fff' or '\uff00' <= c <= '\uffef'
    )
    
    text_length = max(len(text), 1)  # Avoid division by zero
    japanese_ratio = jp_chars / text_length
    
    return "ja" if japanese_ratio > 0.2 else "en"


def detect_language(
    text: str,
    whisper_lang: Optional[str] = None,
    whisper_confidence: float = 0.0
) -> Literal["en", "ja"]:
    """
    Detect language with Whisper primary, Unicode fallback.
    
    Uses Whisper STT language detection when confidence >= 0.8,
    otherwise falls back to Unicode block scanning.
    
    Args:
        text: Input text to analyze
        whisper_lang: Language detected by Whisper STT (optional)
        whisper_confidence: Confidence score from Whisper (0.0-1.0)
    
    Returns:
        "en" or "ja" based on detection
    
    Preconditions:
        - text is non-empty string
        - whisper_confidence is in range [0.0, 1.0]
    
    Postconditions:
        - Returns either "en" or "ja"
        - Uses Whisper result if confidence >= 0.8
        - Falls back to Unicode scan if confidence < 0.8
        - Deterministic for same inputs
    
    Loop Invariants:
        - Character count remains consistent during iteration
        - Japanese character ratio is monotonically computed
    """
    CONFIDENCE_THRESHOLD = 0.8
    
    # Primary: Use Whisper detection if confident
    if whisper_lang and whisper_confidence >= CONFIDENCE_THRESHOLD:
        return whisper_lang if whisper_lang in ("en", "ja") else "en"
    
    # Fallback: Unicode block scan
    return detect_from_unicode(text)
