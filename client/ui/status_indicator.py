"""
Status indicator widget.

Shows system status: Listening, Recording, Transcribing, Processing, Speaking, Idle.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, pyqtSlot, QPropertyAnimation, QEasingCurve
from typing import Literal
import logging

logger = logging.getLogger(__name__)


class StatusIndicator(QWidget):
    """
    Visual status indicator with pulse animation for active states.

    Shows six states: Listening (🟢), Recording (🔴), Transcribing (⏳),
    Processing (🟡), Speaking (🔵), Idle (⚪).
    """

    PULSE_STATES: frozenset = frozenset({"recording", "speaking"})

    def __init__(self):
        """Initialize status indicator."""
        super().__init__()

        # Layout
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Status label
        self.status_label = QLabel("⚪  Connecting...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 20px; font-weight: bold;")

        layout.addWidget(self.status_label)

        # Opacity effect for pulse animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)

        # Pulse animation: opacity oscillates 1.0 ↔ 0.6 over 800 ms, looping infinitely
        self._pulse_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._pulse_anim.setDuration(800)
        self._pulse_anim.setStartValue(1.0)
        self._pulse_anim.setEndValue(0.6)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.SineCurve)

        logger.info("Initialized status indicator")

    @pyqtSlot(str)
    def set_status(self, status: Literal["listening", "recording", "transcribing", "thinking", "speaking", "idle"]) -> None:
        """
        Update status display.

        Args:
            status: Status state
        """
        status_map = {
            "listening":    ("🟢  Listening",    "#a6e3a1"),
            "recording":    ("🔴  Recording",    "#f38ba8"),
            "transcribing": ("⏳  Transcribing", "#f9e2af"),
            "thinking":     ("🟡  Processing",   "#f9e2af"),
            "speaking":     ("🔵  Speaking",     "#89b4fa"),
            "idle":         ("⚪  Idle",          "#6c7086"),
        }

        text, color = status_map.get(status, ("❓ Unknown", "#ffffff"))

        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {color};"
        )

        if status in self.PULSE_STATES:
            self._pulse_anim.stop()
            self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._opacity_effect.setOpacity(1.0)

        logger.debug(f"Status updated: {status}")
