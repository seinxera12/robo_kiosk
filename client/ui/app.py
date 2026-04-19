"""
Main PyQt6 application window.

Fullscreen kiosk interface with:
  - Status bar (Listening / Processing / Responding)
  - Conversation transcript with streaming tokens
  - Text input row with Send + Clear buttons
  - Mic status indicator (always-on VAD, no button press needed)
"""

import asyncio
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSizePolicy, QLabel
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor

from client.ui.conversation_widget import ConversationWidget
from client.ui.status_indicator import StatusIndicator
from client.ui.keyboard_widget import KeyboardWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class PipelineWorker(QObject):
    """Runs the async client pipeline in a QThread, emits Qt signals to UI."""

    status_changed  = pyqtSignal(str)   # "listening" | "thinking" | "speaking"
    token_received  = pyqtSignal(str)
    response_done   = pyqtSignal()
    user_text       = pyqtSignal(str)   # text shown in chat as user bubble
    mic_active      = pyqtSignal(bool)  # True = speech detected, False = silence
    connected       = pyqtSignal()
    error_occurred  = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._loop = None
        self._ws   = None
        self._running = False
        self.listening_enabled = True   # toggle — VAD always runs, this gates send

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._running = True
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self._loop.close()

    async def _main(self):
        from client.ws_client import WebSocketClient
        from client.audio_capture import AudioCapture
        from client.vad import SileroVAD

        self._ws = WebSocketClient(self.config.server_ws_url)
        audio_capture = AudioCapture()
        vad = SileroVAD()

        await self._ws.connect()
        await self._ws.send_json({
            "type": "session_start",
            "kiosk_id": self.config.kiosk_id,
            "kiosk_location": self.config.kiosk_location,
        })
        self.connected.emit()
        self.status_changed.emit("listening")

        await asyncio.gather(
            self._receive_loop(),
            self._capture_loop(audio_capture, vad),
        )

    async def _receive_loop(self):
        async for msg in self._ws.receive():
            if not self._running:
                break
            if isinstance(msg, bytes):
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if t == "llm_text_chunk":
                text  = msg.get("text", "")
                final = msg.get("final", False)
                if text:
                    self.token_received.emit(text)
                if final:
                    self.response_done.emit()
                    self.status_changed.emit("listening")
            elif t == "status":
                self.status_changed.emit(msg.get("state", "idle"))
            elif t == "session_ack":
                logger.info("Server acknowledged session")

    async def _capture_loop(self, audio_capture, vad):
        async for frame in audio_capture.stream():
            if not self._running:
                break
            event = vad.process_frame(frame)
            if event is None:
                continue
            if not self.listening_enabled:
                # VAD still runs (keeps state fresh) but we don't act on it
                continue
            if event.event_type == "speech_start":
                self.mic_active.emit(True)
                self.status_changed.emit("thinking")
            elif event.event_type == "speech_end" and event.audio_buffer:
                self.mic_active.emit(False)
                await self._ws.send_audio(event.audio_buffer)

    def send_text(self, text: str, lang: str = "en"):
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(
                self._ws.send_json({"type": "text_input", "text": text, "lang": lang}),
                self._loop,
            )
            self.user_text.emit(text)
            self.status_changed.emit("thinking")

    def stop(self):
        self._running = False
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class KioskMainWindow(QMainWindow):
    """
    Fullscreen kiosk window.

    ┌──────────────────────────────────────────────┐
    │  🟢 Listening — Voice Kiosk Assistant        │  ← status bar
    ├──────────────────────────────────────────────┤
    │                                              │
    │  You: Where is the cafeteria?                │  ← conversation
    │  Assistant: The cafeteria is on floor 2...   │
    │                                              │
    ├──────────────────────────────────────────────┤
    │  [Type your question...    ] [Send] [Clear]  │  ← text input
    │  🎤 Microphone: always listening             │  ← mic status
    └──────────────────────────────────────────────┘
    """

    def __init__(self, config=None):
        super().__init__()
        self.config = config
        self._worker = None
        self._thread = None
        self._response_buffer = ""

        self.setWindowTitle("Voice Kiosk Assistant")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.showFullScreen()

        self._build_ui()
        self._load_stylesheet()

        if config:
            self._start_pipeline()

        logger.info("KioskMainWindow initialized")

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        # ── Status bar ──────────────────────────────────────────────────
        self.status = StatusIndicator()
        self.status.setFixedHeight(64)
        layout.addWidget(self.status)

        # ── Conversation area ────────────────────────────────────────────
        self.conversation = ConversationWidget()
        self.conversation.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.conversation, stretch=1)

        # ── Text input row ───────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.keyboard = KeyboardWidget()
        self.keyboard.text_submitted.connect(self._on_text_submitted)
        input_row.addWidget(self.keyboard, stretch=1)

        layout.addLayout(input_row)

        # ── Mic status bar + toggle ──────────────────────────────────────
        mic_row = QHBoxLayout()
        mic_row.setSpacing(12)

        self.mic_status = QLabel("🎤  Microphone: connecting...")
        self.mic_status.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.mic_status.setFixedHeight(40)
        self.mic_status.setObjectName("micStatus")
        mic_row.addWidget(self.mic_status, stretch=1)

        self.listen_toggle = QPushButton("🎤  Always Listen: ON")
        self.listen_toggle.setFixedHeight(40)
        self.listen_toggle.setMinimumWidth(220)
        self.listen_toggle.setObjectName("toggleOnButton")
        self.listen_toggle.setToolTip("Toggle always-on voice listening on/off")
        self.listen_toggle.setEnabled(False)   # enabled once connected
        self.listen_toggle.clicked.connect(self._on_toggle_listen)
        mic_row.addWidget(self.listen_toggle)

        layout.addLayout(mic_row)

    def _load_stylesheet(self):
        try:
            with open("client/ui/styles.qss") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            logger.warning("styles.qss not found, using defaults")

    # --------------------------------------------------------- Pipeline

    def _start_pipeline(self):
        self._worker = PipelineWorker(self.config)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status_changed.connect(self.status.set_status)
        self._worker.token_received.connect(self._on_token)
        self._worker.response_done.connect(self._on_response_done)
        self._worker.user_text.connect(self._on_user_text)
        self._worker.mic_active.connect(self._on_mic_active)
        self._worker.connected.connect(self._on_connected)
        self._worker.error_occurred.connect(self._on_error)

        self._thread.start()

    # --------------------------------------------------------- Slots

    def _on_connected(self):
        self.mic_status.setText(
            "🎤  Microphone: always listening — just speak naturally"
        )
        self.keyboard.set_enabled(True)
        self.listen_toggle.setEnabled(True)
        self.conversation.add_system_message(
            "Connected. You can speak or type your question below."
        )
        logger.info("Pipeline connected")

    def _on_toggle_listen(self):
        if not self._worker:
            return
        self._worker.listening_enabled = not self._worker.listening_enabled
        enabled = self._worker.listening_enabled
        if enabled:
            self.listen_toggle.setText("🎤  Always Listen: ON")
            self.listen_toggle.setObjectName("toggleOnButton")
            self.mic_status.setText("🎤  Microphone: always listening — just speak naturally")
            self.mic_status.setStyleSheet("")
        else:
            self.listen_toggle.setText("🔇  Always Listen: OFF")
            self.listen_toggle.setObjectName("toggleOffButton")
            self.mic_status.setText("🔇  Microphone: disabled — use text input")
            self.mic_status.setStyleSheet("color: #6c7086;")
        # Force stylesheet refresh (objectName change needs this)
        self.listen_toggle.style().unpolish(self.listen_toggle)
        self.listen_toggle.style().polish(self.listen_toggle)
        logger.info(f"Always-listen toggled: {'ON' if enabled else 'OFF'}")

    def _on_mic_active(self, active: bool):
        if not self._worker or not self._worker.listening_enabled:
            return
        if active:
            self.mic_status.setText("🔴  Microphone: speech detected — listening...")
            self.mic_status.setStyleSheet("color: #f38ba8; font-weight: bold;")
        else:
            self.mic_status.setText("🎤  Microphone: always listening — just speak naturally")
            self.mic_status.setStyleSheet("")

    def _on_text_submitted(self, text: str):
        if self._worker:
            self._worker.send_text(text)

    def _on_user_text(self, text: str):
        self.conversation.add_user_message(text)
        self.conversation.text_display.append("<b>Assistant:</b> ")
        self._response_buffer = ""

    def _on_token(self, token: str):
        self._response_buffer += token
        self.conversation.append_to_last_message(token)

    def _on_response_done(self):
        logger.info(f"Response complete ({len(self._response_buffer)} chars)")
        self._response_buffer = ""

    def _on_error(self, msg: str):
        self.status.set_status("idle")
        self.mic_status.setText("⚠️  Connection error — restart the client")
        self.mic_status.setStyleSheet("color: #c0392b;")
        self.conversation.add_system_message(f"⚠️ Error: {msg}")
        logger.error(f"Pipeline error: {msg}")

    # --------------------------------------------------------- Lifecycle

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        event.accept()
