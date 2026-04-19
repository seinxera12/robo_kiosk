"""
Main PyQt6 application window.

Fixes applied:
  1. Speak button appears when always-listen is OFF
  2. Status updates live during voice capture
  3. Transcript shown in chat as user bubble when server returns it
  4. Each response is a new chat bubble; response_start signal gates this
"""

import asyncio
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSizePolicy, QLabel
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject

from client.ui.conversation_widget import ConversationWidget
from client.ui.status_indicator import StatusIndicator
from client.ui.keyboard_widget import KeyboardWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class PipelineWorker(QObject):
    status_changed  = pyqtSignal(str)   # "listening"|"recording"|"transcribing"|"thinking"|"speaking"
    token_received  = pyqtSignal(str)
    response_start  = pyqtSignal()      # fired once before first token of each response
    response_done   = pyqtSignal()
    transcript_ready = pyqtSignal(str)  # final transcript text from server
    mic_active      = pyqtSignal(bool)
    connected       = pyqtSignal()
    error_occurred  = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._loop  = None
        self._ws    = None
        self._running = False
        self.listening_enabled = True
        # Manual speak mode: set True while Speak button is held/active
        self._manual_speak_active = False
        self._response_started = False   # tracks if bubble already opened

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
        self._audio_capture = AudioCapture()
        self._vad = SileroVAD()

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
            self._capture_loop(),
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

            if t == "transcript":
                # Server finished STT — show user bubble
                self.transcript_ready.emit(msg.get("text", ""))
                self.status_changed.emit("thinking")

            elif t == "llm_text_chunk":
                text  = msg.get("text", "")
                final = msg.get("final", False)
                if text:
                    if not self._response_started:
                        self._response_started = True
                        self.response_start.emit()
                    self.token_received.emit(text)
                if final:
                    self._response_started = False
                    self.response_done.emit()
                    self.status_changed.emit("listening")

            elif t == "status":
                self.status_changed.emit(msg.get("state", "idle"))
            elif t == "session_ack":
                logger.info("Server ready")

    async def _capture_loop(self):
        async for frame in self._audio_capture.stream():
            if not self._running:
                break

            # Gate: only process if always-listen ON or manual speak active
            should_process = self.listening_enabled or self._manual_speak_active
            if not should_process:
                continue

            event = self._vad.process_frame(frame)
            if event is None:
                continue

            if event.event_type == "speech_start":
                self.mic_active.emit(True)
                self.status_changed.emit("recording")

            elif event.event_type == "speech_end" and event.audio_buffer:
                self.mic_active.emit(False)
                self.status_changed.emit("transcribing")
                # If manual speak, auto-deactivate after EOS
                if self._manual_speak_active:
                    self._manual_speak_active = False
                    self.manual_speak_done.emit()
                await self._ws.send_audio(event.audio_buffer)

    # Extra signal for manual speak done
    manual_speak_done = pyqtSignal()

    def start_manual_speak(self):
        """Called when Speak button is pressed."""
        if self._loop:
            self._manual_speak_active = True

    def stop_manual_speak(self):
        """Called if user cancels before EOS."""
        self._manual_speak_active = False

    def send_text(self, text: str, lang: str = "en"):
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(
                self._ws.send_json({"type": "text_input", "text": text, "lang": lang}),
                self._loop,
            )
            self.transcript_ready.emit(text)
            self.status_changed.emit("thinking")

    def stop(self):
        self._running = False
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class KioskMainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.config = config
        self._worker = None
        self._thread = None

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

        # Status bar
        self.status = StatusIndicator()
        self.status.setFixedHeight(64)
        layout.addWidget(self.status)

        # Conversation
        self.conversation = ConversationWidget()
        self.conversation.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.conversation, stretch=1)

        # Text input row
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.keyboard = KeyboardWidget()
        self.keyboard.text_submitted.connect(self._on_text_submitted)
        input_row.addWidget(self.keyboard, stretch=1)
        layout.addLayout(input_row)

        # Bottom row: mic status | [Speak] | [Always Listen toggle]
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self.mic_status = QLabel("🎤  Microphone: connecting...")
        self.mic_status.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.mic_status.setFixedHeight(44)
        self.mic_status.setObjectName("micStatus")
        bottom_row.addWidget(self.mic_status, stretch=1)

        # Speak button — only visible when always-listen is OFF
        self.speak_button = QPushButton("🎙  Speak")
        self.speak_button.setFixedHeight(44)
        self.speak_button.setMinimumWidth(130)
        self.speak_button.setObjectName("speakButton")
        self.speak_button.setToolTip("Press to speak — VAD detects end of speech automatically")
        self.speak_button.setEnabled(False)
        self.speak_button.setVisible(False)   # hidden while always-listen is ON
        self.speak_button.clicked.connect(self._on_speak_pressed)
        bottom_row.addWidget(self.speak_button)

        # Always-listen toggle
        self.listen_toggle = QPushButton("🎤  Always Listen: ON")
        self.listen_toggle.setFixedHeight(44)
        self.listen_toggle.setMinimumWidth(220)
        self.listen_toggle.setObjectName("toggleOnButton")
        self.listen_toggle.setToolTip("Toggle always-on voice listening")
        self.listen_toggle.setEnabled(False)
        self.listen_toggle.clicked.connect(self._on_toggle_listen)
        bottom_row.addWidget(self.listen_toggle)

        layout.addLayout(bottom_row)

    def _load_stylesheet(self):
        try:
            with open("client/ui/styles.qss") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            logger.warning("styles.qss not found")

    # --------------------------------------------------------- Pipeline

    def _start_pipeline(self):
        self._worker = PipelineWorker(self.config)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.token_received.connect(self._on_token)
        self._worker.response_start.connect(self._on_response_start)
        self._worker.response_done.connect(self._on_response_done)
        self._worker.transcript_ready.connect(self._on_transcript_ready)
        self._worker.mic_active.connect(self._on_mic_active)
        self._worker.manual_speak_done.connect(self._on_manual_speak_done)
        self._worker.connected.connect(self._on_connected)
        self._worker.error_occurred.connect(self._on_error)

        self._thread.start()

    # --------------------------------------------------------- Slots

    def _on_connected(self):
        self.keyboard.set_enabled(True)
        self.listen_toggle.setEnabled(True)
        self.mic_status.setText("🎤  Microphone: always listening — just speak naturally")
        self.conversation.add_system_message("Connected. Speak or type your question.")
        logger.info("Pipeline connected")

    def _on_status_changed(self, state: str):
        self.status.set_status(state)
        status_text = {
            "listening":     "🎤  Microphone: always listening — just speak naturally",
            "recording":     "🔴  Recording — speak now...",
            "transcribing":  "⏳  Transcribing your speech...",
            "thinking":      "🟡  Processing...",
            "speaking":      "🔵  Responding...",
            "idle":          "⚪  Idle",
        }
        if state in status_text:
            # Don't overwrite mic status when always-listen is off and speak button shown
            if state == "listening" and not (self._worker and self._worker.listening_enabled):
                self.mic_status.setText("🔇  Always Listen OFF — press Speak to talk")
                self.mic_status.setStyleSheet("color: #6c7086;")
            else:
                self.mic_status.setText(status_text[state])
                self.mic_status.setStyleSheet(
                    "color: #f38ba8; font-weight: bold;" if state == "recording" else ""
                )

    def _on_mic_active(self, active: bool):
        if active:
            self.mic_status.setText("🔴  Recording — speak now...")
            self.mic_status.setStyleSheet("color: #f38ba8; font-weight: bold;")
        else:
            self.mic_status.setText("⏳  Transcribing your speech...")
            self.mic_status.setStyleSheet("color: #f9e2af;")

    def _on_toggle_listen(self):
        if not self._worker:
            return
        self._worker.listening_enabled = not self._worker.listening_enabled
        enabled = self._worker.listening_enabled

        if enabled:
            self.listen_toggle.setText("🎤  Always Listen: ON")
            self.listen_toggle.setObjectName("toggleOnButton")
            self.speak_button.setVisible(False)
            self.speak_button.setEnabled(False)
            self.mic_status.setText("🎤  Microphone: always listening — just speak naturally")
            self.mic_status.setStyleSheet("")
        else:
            self.listen_toggle.setText("🔇  Always Listen: OFF")
            self.listen_toggle.setObjectName("toggleOffButton")
            self.speak_button.setVisible(True)
            self.speak_button.setEnabled(True)
            self.mic_status.setText("🔇  Always Listen OFF — press Speak to talk")
            self.mic_status.setStyleSheet("color: #6c7086;")

        self.listen_toggle.style().unpolish(self.listen_toggle)
        self.listen_toggle.style().polish(self.listen_toggle)
        logger.info(f"Always-listen: {'ON' if enabled else 'OFF'}")

    def _on_speak_pressed(self):
        """User pressed Speak — activate one-shot VAD capture."""
        if not self._worker:
            return
        self.speak_button.setEnabled(False)
        self.speak_button.setText("🔴  Listening...")
        self.mic_status.setText("🔴  Recording — speak now, stop when done")
        self.mic_status.setStyleSheet("color: #f38ba8; font-weight: bold;")
        self._worker.start_manual_speak()

    def _on_manual_speak_done(self):
        """VAD detected end of speech in manual mode — reset button."""
        self.speak_button.setText("🎙  Speak")
        self.speak_button.setEnabled(True)

    def _on_transcript_ready(self, text: str):
        """Server returned transcript — show as user bubble."""
        if text.strip():
            self.conversation.add_user_message(text)

    def _on_response_start(self):
        """First token arriving — open a fresh assistant bubble."""
        self.conversation.start_assistant_bubble()

    def _on_token(self, token: str):
        self.conversation.append_to_last_message(token)

    def _on_response_done(self):
        self.conversation.finish_assistant_bubble()
        logger.info("Response complete")

    def _on_text_submitted(self, text: str):
        if self._worker:
            self._worker.send_text(text)

    def _on_error(self, msg: str):
        self.status.set_status("idle")
        self.mic_status.setText("⚠️  Error — restart the client")
        self.mic_status.setStyleSheet("color: #f38ba8;")
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
