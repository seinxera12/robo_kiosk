"""
Text input widget for the kiosk.

Single-line input with Send and Clear buttons.
Disabled until the pipeline connects.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLineEdit
from PyQt6.QtCore import pyqtSignal
import logging

logger = logging.getLogger(__name__)


class KeyboardWidget(QWidget):
    """Text input row: [input field] [Send ↵] [Clear ✕]"""

    text_submitted = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.setLayout(layout)

        # Input field
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type your question here and press Enter or Send...")
        self.input_field.setMinimumHeight(52)
        self.input_field.returnPressed.connect(self._submit_text)
        self.input_field.setEnabled(False)
        layout.addWidget(self.input_field, stretch=1)

        # Send button
        self.send_button = QPushButton("Send ↵")
        self.send_button.setMinimumHeight(52)
        self.send_button.setMinimumWidth(110)
        self.send_button.setToolTip("Send your typed question (or press Enter)")
        self.send_button.clicked.connect(self._submit_text)
        self.send_button.setEnabled(False)
        layout.addWidget(self.send_button)

        # Clear button
        self.clear_button = QPushButton("Clear ✕")
        self.clear_button.setMinimumHeight(52)
        self.clear_button.setMinimumWidth(110)
        self.clear_button.setToolTip("Clear the input field")
        self.clear_button.setObjectName("clearButton")
        self.clear_button.clicked.connect(self._clear_text)
        self.clear_button.setEnabled(False)
        layout.addWidget(self.clear_button)

        logger.info("Initialized keyboard widget")

    def _submit_text(self):
        text = self.input_field.text().strip()
        if text:
            self.text_submitted.emit(text)
            self.input_field.clear()
            logger.info(f"Text submitted: {text[:60]}...")

    def _clear_text(self):
        self.input_field.clear()

    def set_enabled(self, enabled: bool):
        self.input_field.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
        if enabled:
            self.input_field.setFocus()

    def set_submit_enabled(self, enabled: bool):
        """Allow or block submission while keeping the input field writable.

        Call with False while the assistant is streaming so the user can
        pre-type their next message but cannot send it until the response
        finishes.  The input field and Clear button stay active throughout.
        """
        self.send_button.setEnabled(enabled)
        # Disconnect / reconnect returnPressed so Enter is also blocked
        try:
            if enabled:
                self.input_field.returnPressed.connect(self._submit_text)
            else:
                self.input_field.returnPressed.disconnect(self._submit_text)
        except RuntimeError:
            # Already connected/disconnected — safe to ignore
            pass
