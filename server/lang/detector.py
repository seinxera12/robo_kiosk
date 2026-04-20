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
    
    # Lower threshold for better Japanese detection and add debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"Unicode detection: jp_chars={jp_chars}, total={text_length}, ratio={japanese_ratio:.3f}")
    
    return "ja" if japanese_ratio > 0.1 else "en"  # Lowered from 0.2 to 0.1


def detect_language(
    text: str,
    whisper_lang: Optional[str] = None,
    whisper_confidence: float = 0.0
) -> Literal["en", "ja"]:
    """
    Detect language with Whisper primary, Unicode fallback.
    
    Uses Whisper STT language detection when confidence >= 0.6,
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
        - Uses Whisper result if confidence >= 0.6
        - Falls back to Unicode scan if confidence < 0.6
        - Deterministic for same inputs
    
    Loop Invariants:
        - Character count remains consistent during iteration
        - Japanese character ratio is monotonically computed
    """
    CONFIDENCE_THRESHOLD = 0.6  # Balanced threshold for accuracy
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Primary: Use Whisper detection if confident and valid
    if whisper_lang and whisper_confidence >= CONFIDENCE_THRESHOLD:
        # Map common language codes to our supported languages
        lang_mapping = {
            "en": "en", "english": "en",
            "ja": "ja", "japanese": "ja", "jp": "ja"
        }
        detected_lang = lang_mapping.get(whisper_lang.lower(), "en")
        logger.debug(f"Using Whisper detection: {detected_lang} (confidence={whisper_confidence:.3f})")
        return detected_lang
    
    # Fallback: Unicode block scan
    fallback_lang = detect_from_unicode(text)
    logger.debug(f"Using Unicode fallback: {fallback_lang} (Whisper confidence={whisper_confidence:.3f} < {CONFIDENCE_THRESHOLD})")
    return fallback_lang
