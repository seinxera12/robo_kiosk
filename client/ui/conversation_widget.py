"""
Conversation display widget.

Each user message and each assistant response is a separate bubble.
Streaming tokens append into the current open assistant bubble.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QTextCursor
import logging

logger = logging.getLogger(__name__)


class ConversationWidget(QWidget):

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Ensure proper UTF-8 encoding for Japanese characters
        self.text_display.setAcceptRichText(True)
        
        layout.addWidget(self.text_display)

        self._bubble_open = False   # True while streaming into an assistant bubble
        logger.info("Initialized conversation widget")

    # ---------------------------------------------------------------- public API

    @pyqtSlot(str)
    def add_user_message(self, text: str, lang: str = "en") -> None:
        """Add a complete user bubble."""
        self._close_bubble_if_open()
        self.text_display.append(
            f'<p style="margin:6px 0"><span style="color:#89b4fa;font-weight:bold;">You</span>'
            f'<span style="color:#585b70;"> ▸ </span>{self._escape(text)}</p>'
        )
        self._scroll_to_bottom()

    @pyqtSlot(str)
    def add_system_message(self, text: str) -> None:
        """Add a complete system/info message (not a streaming bubble)."""
        self._close_bubble_if_open()
        self.text_display.append(
            f'<p style="margin:6px 0;color:#a6adc8;font-style:italic;">{self._escape(text)}</p>'
        )
        self._scroll_to_bottom()

    def start_assistant_bubble(self) -> None:
        """Open a new assistant bubble — tokens will stream into it."""
        self._close_bubble_if_open()
        # insertHtml does not create a new block on its own, so we explicitly
        # move to the end and insert a block break first.  This guarantees the
        # "Assistant ▸" label always starts on its own line regardless of what
        # was appended before (user message via append() or previous tokens).
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertHtml(
            '<span style="color:#a6e3a1;font-weight:bold;">Assistant</span>'
            '<span style="color:#585b70;"> ▸ </span>'
        )
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_display.setTextCursor(cursor)
        self._bubble_open = True
        self._scroll_to_bottom()

    @pyqtSlot(str)
    def append_to_last_message(self, token: str) -> None:
        """Append a streaming token to the currently open bubble."""
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        self._scroll_to_bottom()

    def finish_assistant_bubble(self) -> None:
        """Close the current assistant bubble."""
        if self._bubble_open:
            self._bubble_open = False
            self._scroll_to_bottom()

    def clear(self) -> None:
        self._bubble_open = False
        self.text_display.clear()

    # ---------------------------------------------------------------- private

    def _close_bubble_if_open(self):
        if self._bubble_open:
            self.finish_assistant_bubble()

    def _scroll_to_bottom(self):
        sb = self.text_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
