"""
Status indicator widget.

Shows system status: Listening, Thinking, Speaking.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSlot
from typing import Literal
import logging

logger = logging.getLogger(__name__)


class StatusIndicator(QWidget):
    """
    Visual status indicator.
    
    Shows three states: Listening (🟢), Thinking (🟡), Speaking (🔵)
    """
    
    def __init__(self):
        """Initialize status indicator."""
        super().__init__()
        
        # Layout
        layout = QHBoxLayout()
        self.setLayout(layout)
        
        # Status label
        self.status_label = QLabel("⚪  Connecting...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        
        layout.addWidget(self.status_label)
        
        logger.info("Initialized status indicator")
    
    @pyqtSlot(str)
    def set_status(self, status: Literal["listening", "thinking", "speaking", "idle"]) -> None:
        """
        Update status display.
        
        Args:
            status: Status state
        """
        status_map = {
            "listening":    ("🟢  Listening — speak or type your question", "color: #a6e3a1;"),
            "recording":    ("🔴  Recording — speak now...",                "color: #f38ba8;"),
            "transcribing": ("⏳  Transcribing...",                         "color: #f9e2af;"),
            "thinking":     ("🟡  Processing your request...",              "color: #f9e2af;"),
            "speaking":     ("🔵  Responding...",                           "color: #89b4fa;"),
            "idle":         ("⚪  Idle",                                    "color: #6c7086;"),
        }
        
        text, color = status_map.get(status, ("❓ Unknown", "color: black;"))
        
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"font-size: 24px; font-weight: bold; {color}")
        
        logger.debug(f"Status updated: {status}")
