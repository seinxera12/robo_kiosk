"""
Conversation display widget.

Each user message and each assistant response is a separate bubble.
Streaming tokens append into the current open assistant bubble.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor
import logging

logger = logging.getLogger(__name__)

_CURSOR_CHAR = "▋"


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

        # Streaming cursor state
        self._cursor_timer: QTimer = QTimer(self)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_visible: bool = False
        self._cursor_anchor: int = -1   # document position of ▋; -1 means no cursor

        # Transcript highlight animation state
        self._highlight_timer: QTimer = QTimer(self)
        self._highlight_timer.setInterval(100)
        self._highlight_timer.timeout.connect(self._on_highlight_step)
        self._highlight_steps: int = 0
        self._highlight_anchor: QTextCursor = None  # type: ignore[assignment]

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
        if text.strip():
            self._start_highlight_animation()

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
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        cursor.insertHtml(
            '<span style="color:#a6e3a1;font-weight:bold;">Assistant</span>'
            '<span style="color:#585b70;"> ▸ </span>'
        )
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Record the position where ▋ will live, then insert it
        self._cursor_anchor = cursor.position()
        cursor.insertText(_CURSOR_CHAR)
        self._cursor_visible = True

        self.text_display.setTextCursor(cursor)
        self._bubble_open = True

        # Start the 500 ms repeating blink timer
        self._cursor_timer.start()

        self._scroll_to_bottom()

    @pyqtSlot(str)
    def append_to_last_message(self, token: str) -> None:
        """Append a streaming token to the currently open bubble."""
        if self._cursor_anchor >= 0:
            # Insert the token before the ▋ cursor, pushing it right
            cursor = self.text_display.textCursor()
            cursor.setPosition(self._cursor_anchor)
            cursor.insertText(token)
            # Use the cursor's actual position after insertion so that
            # characters Qt silently drops (e.g. Unicode non-characters such
            # as U+FFFE/U+FFFF) don't cause _cursor_anchor to drift past the
            # real ▋ position.
            self._cursor_anchor = cursor.position()
        else:
            cursor = self.text_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(token)
        self._scroll_to_bottom()

    def finish_assistant_bubble(self) -> None:
        """Close the current assistant bubble."""
        if self._bubble_open:
            self._remove_cursor()
            self._bubble_open = False
            self._scroll_to_bottom()

    def clear(self) -> None:
        self._stop_highlight_animation()
        self._remove_cursor()
        self._bubble_open = False
        self.text_display.clear()

    # ---------------------------------------------------------------- private

    def _close_bubble_if_open(self):
        if self._bubble_open:
            self.finish_assistant_bubble()

    def _start_highlight_animation(self) -> None:
        """Record anchor to last paragraph; apply initial highlight; start step timer."""
        # Stop any running highlight animation first
        self._highlight_timer.stop()

        # Get a fresh cursor at the end of the document and select the last paragraph
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        self._highlight_anchor = cursor

        # Set initial highlight steps
        self._highlight_steps = 6

        # Apply initial background color with alpha=180
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(42, 74, 138, 180))
        cursor.setCharFormat(fmt)

        # Start the timer with 100 ms interval
        self._highlight_timer.start()

    def _on_highlight_step(self) -> None:
        """Advance one fade step; update background color alpha."""
        self._highlight_steps -= 1

        # Compute alpha linearly from 180 → 0 over 6 steps
        alpha = int(180 * (self._highlight_steps / 6))

        if self._highlight_anchor is not None:
            # Re-select the block to apply the updated format
            cursor = self._highlight_anchor
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(42, 74, 138, alpha))
            cursor.setCharFormat(fmt)

        if self._highlight_steps == 0:
            self._stop_highlight_animation()

    def _stop_highlight_animation(self) -> None:
        """Stop timer; clear background from the highlighted paragraph."""
        self._highlight_timer.stop()
        if self._highlight_anchor is not None:
            cursor = self._highlight_anchor
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(Qt.GlobalColor.transparent))
            cursor.setCharFormat(fmt)
            self._highlight_anchor = None

    def _toggle_cursor(self) -> None:
        """Blink: remove ▋ if visible, insert ▋ if not visible."""
        if self._cursor_visible:
            self._remove_cursor_char()
            self._cursor_visible = False
        else:
            # Re-insert ▋ at the tracked anchor position
            cursor = self.text_display.textCursor()
            cursor.setPosition(self._cursor_anchor)
            cursor.insertText(_CURSOR_CHAR)
            self._cursor_visible = True

    def _remove_cursor_char(self) -> None:
        """Remove the ▋ character from the document near _cursor_anchor."""
        doc = self.text_display.document()
        # Search for ▋ starting at _cursor_anchor; it should be right there
        # when visible, but scan a small window to be safe.
        search_start = max(0, self._cursor_anchor)
        cursor = self.text_display.textCursor()
        cursor.setPosition(search_start)
        # Try the character at the anchor position first
        cursor.setPosition(search_start, QTextCursor.MoveMode.MoveAnchor)
        cursor.setPosition(search_start + 1, QTextCursor.MoveMode.KeepAnchor)
        if cursor.selectedText() == _CURSOR_CHAR:
            cursor.removeSelectedText()
            return
        # Fallback: search forward a few characters
        for offset in range(0, 5):
            pos = search_start + offset
            if pos + 1 > doc.characterCount():
                break
            cursor.setPosition(pos, QTextCursor.MoveMode.MoveAnchor)
            cursor.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
            if cursor.selectedText() == _CURSOR_CHAR:
                cursor.removeSelectedText()
                return

    def _remove_cursor(self) -> None:
        """Full cleanup: stop timer, remove ▋ from document, reset state."""
        self._cursor_timer.stop()
        if self._cursor_anchor >= 0 and self._cursor_visible:
            self._remove_cursor_char()
        self._cursor_anchor = -1
        self._cursor_visible = False

    def _scroll_to_bottom(self):
        sb = self.text_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
