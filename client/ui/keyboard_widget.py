"""
On-screen keyboard widget (optional).

Provides touch-based text input for kiosk.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit
from PyQt6.QtCore import pyqtSignal
import logging

logger = logging.getLogger(__name__)


class KeyboardWidget(QWidget):
    """
    On-screen keyboard for text input.
    
    Optional widget for touch-based kiosks.
    """
    
    # Signal emitted when text is submitted
    text_submitted = pyqtSignal(str)
    
    def __init__(self):
        """Initialize keyboard widget."""
        super().__init__()
        
        # Layout
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Text input field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type your question here...")
        self.input_field.returnPressed.connect(self._submit_text)
        layout.addWidget(self.input_field)
        
        # Submit button
        button_layout = QHBoxLayout()
        
        self.submit_button = QPushButton("Submit")
        self.submit_button.clicked.connect(self._submit_text)
        button_layout.addWidget(self.submit_button)
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_text)
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        
        # TODO: Add on-screen keyboard buttons if needed
        
        logger.info("Initialized keyboard widget")
    
    def _submit_text(self) -> None:
        """Submit text input."""
        text = self.input_field.text().strip()
        
        if text:
            self.text_submitted.emit(text)
            self.input_field.clear()
            logger.info(f"Text submitted: {text[:50]}...")
    
    def _clear_text(self) -> None:
        """Clear text input."""
        self.input_field.clear()
    
    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable keyboard input.
        
        Args:
            enabled: True to enable, False to disable
        """
        self.input_field.setEnabled(enabled)
        self.submit_button.setEnabled(enabled)
