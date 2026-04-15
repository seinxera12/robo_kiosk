"""
Text cleaning and normalization for STT transcripts.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 18.6**
"""

import re
from typing import Literal

# Language-specific filler words
# Requirement 5.2: Remove English filler words ("um", "uh")
# Requirement 5.3: Remove Japanese filler words ("えー", "あの")
FILLER_WORDS = {
    "en": ["um", "uh", "umm", "uhh", "er", "ah"],
    "ja": ["えー", "あの", "えっと", "あー", "うーん"]
}


def strip_whitespace(text: str) -> str:
    """
    Strip leading and trailing whitespace from text.
    
    Args:
        text: Input text string
    
    Returns:
        Text with leading/trailing whitespace removed
    
    Preconditions:
    - text is a string (may be empty)
    
    Postconditions:
    - Returns text with no leading/trailing whitespace
    - Internal whitespace is preserved
    - Empty string returns empty string
    
    **Validates: Requirement 5.1**
    """
    return text.strip()


def remove_filler_words(text: str, lang: Literal["en", "ja"]) -> str:
    """
    Remove language-specific filler words from text.
    
    Args:
        text: Input text string
        lang: Language code ("en" or "ja")
    
    Returns:
        Text with filler words removed
    
    Preconditions:
    - text is a string
    - lang is either "en" or "ja"
    
    Postconditions:
    - Returns text with filler words removed
    - Word boundaries are respected (no partial matches)
    - Multiple spaces are collapsed to single space
    - Leading/trailing whitespace is stripped
    
    Loop Invariants:
    - All filler words in the list are processed
    - Text structure is preserved
    
    **Validates: Requirements 5.2, 5.3, 18.6**
    """
    if lang not in FILLER_WORDS:
        return text
    
    filler_list = FILLER_WORDS[lang]
    
    # For each filler word, remove it with word boundaries
    for filler in filler_list:
        # Use word boundaries for English, direct match for Japanese
        if lang == "en":
            # Case-insensitive word boundary match for English
            pattern = r'\b' + re.escape(filler) + r'\b'
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        else:
            # Direct match for Japanese (no word boundaries in Japanese)
            text = text.replace(filler, '')
    
    # Collapse multiple spaces to single space
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def restore_punctuation(text: str, lang: Literal["en", "ja"]) -> str:
    """
    Restore sentence-ending punctuation if missing.
    
    Args:
        text: Input text string
        lang: Language code ("en" or "ja")
    
    Returns:
        Text with sentence-ending punctuation restored
    
    Preconditions:
    - text is a string
    - lang is either "en" or "ja"
    
    Postconditions:
    - Returns text with appropriate sentence-ending punctuation
    - If text already ends with punctuation, no change
    - Empty or whitespace-only text returns unchanged
    
    **Validates: Requirement 5.4**
    """
    text = text.strip()
    
    if not text:
        return text
    
    # Check if text already ends with punctuation
    # English: . ? ! ... 
    # Japanese: 。？！…
    punctuation_marks = {
        "en": ['.', '?', '!', '…'],
        "ja": ['。', '？', '！', '…', '.', '?', '!']
    }
    
    marks = punctuation_marks.get(lang, punctuation_marks["en"])
    
    if any(text.endswith(mark) for mark in marks):
        return text
    
    # Add appropriate punctuation
    if lang == "ja":
        return text + "。"
    else:
        return text + "."


def clean_transcript(
    text: str,
    lang: Literal["en", "ja"]
) -> str:
    """
    Apply all cleaning steps to a transcript.
    
    Combines all cleaning operations in the correct order:
    1. Strip whitespace
    2. Remove filler words
    3. Restore punctuation
    
    Args:
        text: Input transcript text
        lang: Language code ("en" or "ja")
    
    Returns:
        Cleaned transcript text
    
    Preconditions:
    - text is a string
    - lang is either "en" or "ja"
    
    Postconditions:
    - Returns fully cleaned text
    - All cleaning steps are applied in order
    - Empty input returns empty string
    
    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 18.6**
    """
    # Step 1: Strip whitespace (Requirement 5.1)
    text = strip_whitespace(text)
    
    if not text:
        return text
    
    # Step 2: Remove filler words (Requirements 5.2, 5.3, 18.6)
    text = remove_filler_words(text, lang)
    
    if not text:
        return text
    
    # Step 3: Restore punctuation (Requirement 5.4)
    text = restore_punctuation(text, lang)
    
    return text
