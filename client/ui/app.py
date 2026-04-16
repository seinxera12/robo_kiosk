"""
Main PyQt6 application window.

Fullscreen kiosk interface with conversation display and status.
"""

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
import logging

logger = logging.getLogger(__name__)


class KioskMainWindow(QMainWindow):
    """
    Main kiosk application window.
    
    Fullscreen interface with no window chrome.
    """
    
    def __init__(self):
        """Initialize main window."""
        super().__init__()
        
        self.setWindowTitle("Voice Kiosk Chatbot")
        
        # Fullscreen kiosk mode
        self.showFullScreen()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # TODO: Add conversation widget, status indicator, input area
        # from client.ui.conversation_widget import ConversationWidget
        # from client.ui.status_indicator import StatusIndicator
        # from client.ui.keyboard_widget import KeyboardWidget
        
        # self.conversation = ConversationWidget()
        # self.status = StatusIndicator()
        # self.keyboard = KeyboardWidget()
        
        # layout.addWidget(self.status)
        # layout.addWidget(self.conversation)
        # layout.addWidget(self.keyboard)
        
        # Load stylesheet
        self._load_stylesheet()
        
        logger.info("Initialized kiosk main window")
    
    def _load_stylesheet(self) -> None:
        """Load Qt stylesheet from file."""
        try:
            with open("client/ui/styles.qss", "r") as f:
                stylesheet = f.read()
                self.setStyleSheet(stylesheet)
        except FileNotFoundError:
            logger.warning("Stylesheet file not found, using default styles")
    
    def closeEvent(self, event):
        """Handle window close event."""
        logger.info("Closing kiosk application")
        event.accept()
