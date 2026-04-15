"""
Conversation display widget.

Shows conversation transcript with user queries and system responses.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QScrollArea
from PyQt6.QtCore import Qt, pyqtSlot
import logging

logger = logging.getLogger(__name__)


class ConversationWidget(QWidget):
    """
    Conversation transcript display.
    
    Shows user queries and system responses with auto-scroll.
    """
    
    def __init__(self):
        """Initialize conversation widget."""
        super().__init__()
        
        # Layout
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Text display
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        layout.addWidget(self.text_display)
        
        logger.info("Initialized conversation widget")
    
    @pyqtSlot(str, str)
    def add_user_message(self, text: str, lang: str = "en") -> None:
        """
        Add user message to conversation.
        
        Args:
            text: User query text
            lang: Language code
        """
        self.text_display.append(f"<b>You:</b> {text}")
        self._scroll_to_bottom()
    
    @pyqtSlot(str)
    def add_system_message(self, text: str) -> None:
        """
        Add system response to conversation.
        
        Args:
            text: System response text
        """
        self.text_display.append(f"<b>Assistant:</b> {text}")
        self._scroll_to_bottom()
    
    @pyqtSlot(str)
    def append_to_last_message(self, text: str) -> None:
        """
        Append text to last message (for streaming).
        
        Args:
            text: Text chunk to append
        """
        cursor = self.text_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self._scroll_to_bottom()
    
    def _scroll_to_bottom(self) -> None:
        """Scroll to bottom of conversation."""
        scrollbar = self.text_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear(self) -> None:
        """Clear conversation display."""
        self.text_display.clear()
