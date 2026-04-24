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
    manual_speak_done = pyqtSignal()    # VAD detected end of speech in manual mode
    manual_speak_timeout = pyqtSignal() # Manual speak timed out

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._loop  = None
        self._ws    = None
        self._running = False
        self.listening_enabled = False  # default OFF — user must enable explicitly
        # Manual speak mode: set True while Speak button is held/active
        self._manual_speak_active = False
        self._speak_timeout_task = None  # asyncio Task for 15s timeout
        self._response_started = False   # tracks if bubble already opened
        self._playback = None  # AudioPlayback, created inside worker thread

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

        from client.audio_playback import AudioPlayback
        self._playback = AudioPlayback()

        await self._ws.connect()
        await self._ws.send_json({
            "type": "session_start",
            "kiosk_id": self.config.kiosk_id,
            "kiosk_location": self.config.kiosk_location,
        })
        self.connected.emit()
        self.status_changed.emit("listening")

        # Run receive loop always; capture loop is best-effort (audio may be unavailable)
        async def safe_capture_loop():
            try:
                await self._capture_loop()
            except Exception as e:
                logger.warning(f"Audio capture unavailable: {e}")
                self.error_occurred.emit(f"Audio capture unavailable: {e}")
                # Don't re-raise — keep the receive loop and text input alive

        await asyncio.gather(
            self._receive_loop(),
            safe_capture_loop(),
        )

    async def _receive_loop(self):
        async for msg in self._ws.receive():
            if not self._running:
                break
            if isinstance(msg, bytes):
                # Binary audio from TTS — queue for playback
                if self._playback:
                    self._playback.queue_audio(msg)
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")

            if t == "transcript":
                # Server finished STT — show user bubble.
                # Reset _response_started so the next assistant response always
                # opens a fresh bubble, even if the previous response was
                # interrupted before its final=True chunk arrived.
                self._response_started = False
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
                if final and self._response_started:
                    # Only close the bubble if we actually opened one.
                    # Spurious final=True from server-side interrupt handling
                    # (when pipeline was already idle) must not trigger a
                    # "Response complete" log or a finish_assistant_bubble call.
                    self._response_started = False
                    self.response_done.emit()
                    self.status_changed.emit("listening")

            elif t == "status":
                self.status_changed.emit(msg.get("state", "idle"))
            elif t == "session_ack":
                logger.info("Server ready")

    async def _capture_loop(self):
        retry_count = 0
        max_retries = 3
        
        while self._running and retry_count < max_retries:
            try:
                async for frame in self._audio_capture.stream():
                    if not self._running:
                        break

                    # Debug: Log every 100 frames (about 3 seconds) to show capture is working
                    if not hasattr(self, '_frame_counter'):
                        self._frame_counter = 0
                    self._frame_counter += 1
                    
                    if self._frame_counter % 100 == 0:
                        logger.debug(f"Audio capture active: frame {self._frame_counter}, manual_speak={self._manual_speak_active}, listening={self.listening_enabled}")

                    # Always feed frames to VAD to keep its internal state warm.
                    # Silero VAD is stateful — skipping frames causes the model to
                    # go cold and miss the first ~200ms of speech when processing resumes.
                    try:
                        event = self._vad.process_frame(frame)
                    except Exception as e:
                        logger.warning(f"VAD processing error: {e}")
                        continue

                    # Gate: only act on events when listening is enabled
                    should_process = self.listening_enabled or self._manual_speak_active
                    if not should_process or event is None:
                        continue

                    logger.debug(f"VAD event: {event.event_type}")

                    if event.event_type == "speech_start":
                        self.mic_active.emit(True)
                        self.status_changed.emit("recording")
                        logger.info("VAD: speech_start — microphone active")

                    elif event.event_type == "speech_end" and event.audio_buffer:
                        self.mic_active.emit(False)
                        self.status_changed.emit("transcribing")
                        logger.info(f"VAD: speech_end — sending {len(event.audio_buffer)} bytes to server")
                        # If manual speak, auto-deactivate after VAD speech_end
                        if self._manual_speak_active:
                            self._manual_speak_active = False
                            # Cancel the asyncio timeout task
                            if self._speak_timeout_task:
                                self._speak_timeout_task.cancel()
                                self._speak_timeout_task = None

                        try:
                            await self._ws.send_audio(event.audio_buffer)
                            # STT-BUG-005: emit done only after successful send
                            # so the UI doesn't reset before audio is delivered
                            self.manual_speak_done.emit()
                        except Exception as e:
                            logger.error(f"Failed to send audio: {e}")
                            self.error_occurred.emit(f"Audio transmission failed: {e}")
                            # Still reset the UI even on failure so the button
                            # doesn't stay stuck in recording state
                            self.manual_speak_done.emit()
                        
                # If we reach here, the stream ended normally
                break
                
            except Exception as e:
                retry_count += 1
                logger.warning(f"Audio capture failed (attempt {retry_count}/{max_retries}): {e}")
                
                if retry_count < max_retries:
                    logger.info(f"Retrying audio capture in 2 seconds...")
                    await asyncio.sleep(2)
                    # Reinitialize audio capture
                    try:
                        from client.audio_capture import AudioCapture
                        self._audio_capture = AudioCapture()
                    except Exception as init_error:
                        logger.error(f"Failed to reinitialize audio capture: {init_error}")
                else:
                    logger.error("Audio capture failed permanently")
                    self.error_occurred.emit("Microphone unavailable - please check your audio settings")

    def start_manual_speak(self):
        """Called when Speak button is pressed (main thread).

        Schedules the actual activation onto the worker's event loop so that
        VAD state is only ever touched from the worker thread.
        """
        logger.info("start_manual_speak called")
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._activate_manual_speak(),
                self._loop,
            )
        else:
            logger.error("No event loop available for manual speak")

    async def _activate_manual_speak(self):
        """Activate manual speak mode — runs on the worker event loop."""
        # Cancel any previous timeout task
        if hasattr(self, '_speak_timeout_task') and self._speak_timeout_task:
            self._speak_timeout_task.cancel()
            self._speak_timeout_task = None

        # Reset VAD state cleanly before activating
        if self._vad:
            self._vad.reset()

        # Stop any ongoing TTS playback (barge-in)
        if self._playback:
            self._playback.stop()

        self._manual_speak_active = True
        logger.info("Manual speak activated")

        # Start asyncio timeout (15s) — no QTimer needed
        self._speak_timeout_task = asyncio.create_task(self._manual_speak_timeout_task())

    async def _manual_speak_timeout_task(self):
        """Asyncio-based 15s timeout for manual speak — runs on worker loop."""
        await asyncio.sleep(15)
        if self._manual_speak_active:
            logger.warning("Manual speak timed out after 15 seconds — flushing audio")
            await self._flush_and_send_vad_audio()
            self.manual_speak_timeout.emit()

    def stop_manual_speak(self):
        """Called if user presses Stop before VAD detects end-of-speech (main thread).

        Schedules the flush onto the worker's event loop so VAD state is only
        ever touched from the worker thread.
        """
        if not self._manual_speak_active:
            return
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._deactivate_manual_speak(),
                self._loop,
            )

    async def _deactivate_manual_speak(self):
        """Flush VAD buffer and send audio — runs on the worker event loop."""
        if not self._manual_speak_active:
            return

        # Cancel timeout task
        if hasattr(self, '_speak_timeout_task') and self._speak_timeout_task:
            self._speak_timeout_task.cancel()
            self._speak_timeout_task = None

        await self._flush_and_send_vad_audio()

    async def _flush_and_send_vad_audio(self):
        """Flush VAD buffer and send to server — runs on the worker event loop."""
        self._manual_speak_active = False

        if not self._vad:
            self.manual_speak_done.emit()
            return

        audio = self._vad.flush()
        if audio and len(audio) >= 16000:
            logger.info(f"Flushing {len(audio)} bytes of VAD audio to server")
            try:
                await self._ws.send_audio(audio)
                logger.info("Flushed audio sent to server")
            except Exception as e:
                logger.error(f"Failed to send flushed audio: {e}")
        else:
            logger.info(f"Not enough audio to flush ({len(audio) if audio else 0} bytes), discarding")

        self.manual_speak_done.emit()

    async def _send_flushed_audio(self, audio: bytes) -> None:
        """Send flushed VAD audio to server (runs in worker event loop)."""
        try:
            await self._ws.send_audio(audio)
            logger.info("Flushed audio sent to server")
        except Exception as e:
            logger.error(f"Failed to send flushed audio: {e}")
        finally:
            self.manual_speak_done.emit()

    def send_text(self, text: str, lang: str = "en"):
        if self._loop and not self._loop.is_closed() and self._ws:
            # Stop any in-progress TTS playback immediately — same as barge-in
            if self._playback:
                self._playback.stop()
            asyncio.run_coroutine_threadsafe(
                self._ws.send_json({"type": "text_input", "text": text, "lang": lang}),
                self._loop,
            )
            # Reset _response_started so the incoming response always opens a
            # fresh assistant bubble, even if a previous response was in-flight.
            self._response_started = False
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
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.status = StatusIndicator()
        self.status.setFixedHeight(48)
        top_bar.addWidget(self.status, stretch=1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(44, 44)
        close_btn.setObjectName("closeButton")
        close_btn.setToolTip("Close application")
        close_btn.clicked.connect(self._on_close)
        top_bar.addWidget(close_btn)

        layout.addLayout(top_bar)

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
        self.speak_button.setVisible(True)   # visible by default (always-listen starts OFF)
        self.speak_button.clicked.connect(self._on_speak_pressed)
        bottom_row.addWidget(self.speak_button)

        # Stop button — only visible during manual speak
        self.stop_button = QPushButton("⏹  Stop")
        self.stop_button.setFixedHeight(44)
        self.stop_button.setMinimumWidth(100)
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setToolTip("Stop recording")
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)   # hidden by default
        self.stop_button.clicked.connect(self._on_stop_pressed)
        bottom_row.addWidget(self.stop_button)

        # Always-listen toggle
        self.listen_toggle = QPushButton("🔇  Always Listen: OFF")
        self.listen_toggle.setFixedHeight(44)
        self.listen_toggle.setMinimumWidth(220)
        self.listen_toggle.setObjectName("toggleOffButton")
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
        self._worker.manual_speak_timeout.connect(self._on_manual_speak_timeout)
        self._worker.connected.connect(self._on_connected)
        self._worker.error_occurred.connect(self._on_error)

        self._thread.start()

    # --------------------------------------------------------- Slots

    def _on_connected(self):
        self.keyboard.set_enabled(True)
        self.listen_toggle.setEnabled(True)
        self.speak_button.setEnabled(True)
        self.mic_status.setText("🔇  Always Listen OFF — press Speak to talk")
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
            self.stop_button.setVisible(False)
            self.stop_button.setEnabled(False)
            self.mic_status.setText("🎤  Microphone: always listening — just speak naturally")
            self.mic_status.setStyleSheet("")
        else:
            self.listen_toggle.setText("🔇  Always Listen: OFF")
            self.listen_toggle.setObjectName("toggleOffButton")
            self._reset_speak_buttons()
            self.mic_status.setText("🔇  Always Listen OFF — press Speak to talk")
            self.mic_status.setStyleSheet("color: #6c7086;")

        self.listen_toggle.style().unpolish(self.listen_toggle)
        self.listen_toggle.style().polish(self.listen_toggle)
        logger.info(f"Always-listen: {'ON' if enabled else 'OFF'}")

    def _on_speak_pressed(self):
        """User pressed Speak — activate one-shot VAD capture."""
        if not self._worker:
            logger.error("No worker available")
            return
            
        logger.info("Speak button pressed - starting manual speak mode")
        self.speak_button.setEnabled(False)
        self.speak_button.setVisible(False)
        self.stop_button.setEnabled(True)
        self.stop_button.setVisible(True)
        self.speak_button.setText("🔴  Listening...")
        self.mic_status.setText("🔴  Recording — speak now, stop when done")
        self.mic_status.setStyleSheet("color: #f38ba8; font-weight: bold;")
        
        try:
            self._worker.start_manual_speak()
            logger.info("Manual speak mode activated")
        except Exception as e:
            logger.error(f"Failed to start manual speak: {e}")
            self._reset_speak_buttons()

    def _on_stop_pressed(self):
        """User pressed Stop — flush VAD buffer and send to server."""
        if not self._worker:
            return
        # Disable stop button immediately to prevent double-press.
        # The Speak button re-enables via _on_manual_speak_done once audio is sent.
        self.stop_button.setEnabled(False)
        self.mic_status.setText("⏳  Sending audio...")
        self.mic_status.setStyleSheet("color: #f9e2af;")
        self._worker.stop_manual_speak()

    def _on_manual_speak_done(self):
        """VAD detected end of speech in manual mode — reset button."""
        self._reset_speak_buttons()

    def _on_manual_speak_timeout(self):
        """Manual speak timed out — reset button."""
        self._reset_speak_buttons()
        self.mic_status.setText("🔇  Always Listen OFF — press Speak to talk")
        self.mic_status.setStyleSheet("color: #6c7086;")

    def _reset_speak_buttons(self):
        """Reset speak/stop buttons to default state."""
        self.speak_button.setText("🎙  Speak")
        self.speak_button.setEnabled(True)
        self.speak_button.setVisible(True)
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)

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
        self.keyboard.set_submit_enabled(True)
        logger.info("Response complete")

    def _on_text_submitted(self, text: str):
        if self._worker:
            # Lock submit immediately — before the server even receives the
            # message.  Without this, the user can fire a second submit in the
            # ~500ms gap between Enter and the first LLM token arriving.
            self.keyboard.set_submit_enabled(False)
            self._worker.send_text(text)
        else:
            # No worker — nothing was sent, keep submit enabled
            pass

    def _on_error(self, msg: str):
        self.status.set_status("idle")
        # Unlock submit in case an error fires mid-stream
        self.keyboard.set_submit_enabled(True)
        
        # Provide specific error messages
        if "WebSocket" in msg or "connection" in msg.lower():
            error_msg = "⚠️  Server connection failed - check if server is running"
            self.mic_status.setText("🔌  Server offline - restart server and client")
        elif "audio" in msg.lower() or "microphone" in msg.lower():
            error_msg = "⚠️  Microphone error - check audio permissions"
            self.mic_status.setText("🎤  Microphone unavailable - check settings")
        elif "VAD" in msg or "torch" in msg:
            error_msg = "⚠️  Audio processing error - missing dependencies"
            self.mic_status.setText("📦  Missing audio libraries - run pip install")
        else:
            error_msg = f"⚠️  Error: {msg}"
            self.mic_status.setText("⚠️  Error - restart the client")
            
        self.mic_status.setStyleSheet("color: #f38ba8;")
        self.conversation.add_system_message(error_msg)
        logger.error(f"Pipeline error: {msg}")
        
        # Disable buttons on error
        self.speak_button.setEnabled(False)
        self.listen_toggle.setEnabled(False)

    def _on_close(self):
        """Cleanly shut down worker/thread then exit the process."""
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
    # --------------------------------------------------------- Lifecycle
        from PyQt6.QtWidgets import QApplication

        QApplication.quit()
    def closeEvent(self, event):
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        event.accept()
