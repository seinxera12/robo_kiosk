"""
Keyboard text input handler.

Captures keyboard input for text-based queries.
"""

from typing import Optional, Literal
import logging

logger = logging.getLogger(__name__)


class KeyboardInput:
    """
    Keyboard text input handler.
    
    Validates and processes text input from keyboard or on-screen keyboard.
    """
    
    MAX_TEXT_LENGTH = 1000
    
    def __init__(self):
        """Initialize keyboard input handler."""
        self.current_text = ""
        logger.info("Initialized keyboard input handler")
    
    def add_text(self, text: str) -> None:
        """
        Add text to current input.
        
        Args:
            text: Text to add
        """
        self.current_text += text
        
        # Enforce max length
        if len(self.current_text) > self.MAX_TEXT_LENGTH:
            self.current_text = self.current_text[:self.MAX_TEXT_LENGTH]
            logger.warning(f"Text input truncated to {self.MAX_TEXT_LENGTH} characters")
    
    def clear(self) -> None:
        """Clear current input."""
        self.current_text = ""
    
    def get_text(self) -> str:
        """
        Get current input text.
        
        Returns:
            Current input text
        """
        return self.current_text
    
    def validate_and_submit(self, lang: Literal["auto", "en", "ja"] = "auto") -> Optional[dict]:
        """
        Validate and prepare text input message.
        
        Args:
            lang: Language hint ("auto", "en", or "ja")
            
        Returns:
            Message dict if valid, None if invalid
        """
        text = self.current_text.strip()
        
        # Validate non-empty
        if not text:
            logger.warning("Cannot submit empty text input")
            return None
        
        # Validate length
        if len(text) > self.MAX_TEXT_LENGTH:
            logger.warning(f"Text input exceeds maximum length: {len(text)}")
            return None
        
        # Create message
        message = {
            "type": "text_input",
            "text": text,
            "lang": lang
        }
        
        # Clear input after submission
        self.clear()
        
        logger.info(f"Text input submitted: {text[:50]}...")
        return message
