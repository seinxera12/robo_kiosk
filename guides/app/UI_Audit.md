# Voice Kiosk Client - Complete Frontend Technical & UI Audit

**Document Version:** 1.0  
**Date:** June 17, 2026  
**System:** Voice Kiosk Chatbot Client (PyQt6)  
**Author:** Technical Audit Team

---

## Executive Summary

This document provides a comprehensive technical and UI audit of the Voice Kiosk Client frontend application. The client is a Python-based PyQt6 desktop application that connects to a voice chatbot backend via WebSocket, supporting both voice and text input with real-time streaming responses.

**Key Findings:**
- **Architecture:** Event-driven, multi-threaded PyQt6 application with clean separation of concerns
- **Communication:** WebSocket-based bidirectional streaming protocol
- **State Management:** Thread-safe worker pattern with Qt signals/slots
- **UI Framework:** PyQt6 with custom QSS styling (dark blue theme)
- **Audio Processing:** Real-time VAD (Voice Activity Detection) with sentence-boundary TTS playback
- **Deployment:** Supports full UI, headless, and text-only modes

---

## 1. SYSTEM ARCHITECTURE

### 1.1 Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **UI Framework** | PyQt6 | 6.11.0 |
| **Python Runtime** | Python | 3.11+ |
| **WebSocket Client** | websockets | 12.0 |
| **Audio I/O** | sounddevice | 0.4.6 |
| **VAD Engine** | Silero VAD (torch) | 2.1.0 |
| **Audio Backend** | PortAudio (via sounddevice) | - |
| **Configuration** | python-dotenv | 1.0.0 |

### 1.2 Application Modes

The client supports three distinct operational modes:

#### Mode 1: Full UI Mode (Default)
- **Command:** `python client/main.py`
- **Features:** Complete PyQt6 kiosk interface, voice + text input, visual feedback
- **Use Case:** Production kiosk deployment with display

#### Mode 2: Headless Mode
- **Command:** `python client/main.py --no-ui`
- **Features:** Voice input, terminal text output, no display required
- **Use Case:** WSL2 without WSLg, headless servers

#### Mode 3: Text-Only Mode
- **Command:** `python client/main.py --text`
- **Features:** Terminal text I/O only, no microphone or display
- **Use Case:** Quick testing, development

### 1.3 Module Structure

```
client/
├── main.py                    # Entry point, mode selector
├── config.py                  # Configuration management
├── ws_client.py               # WebSocket communication layer
├── audio_capture.py           # Microphone input (16kHz PCM16)
├── audio_playback.py          # Audio output with WAV decoding
├── vad.py                     # Silero VAD integration
├── keyboard_input.py          # Text input handler
└── ui/
    ├── app.py                 # Main window & worker thread
    ├── conversation_widget.py # Chat display with streaming
    ├── keyboard_widget.py     # Text input UI component
    ├── status_indicator.py    # Status display with animations
    └── styles.qss             # QSS stylesheet (dark theme)
```

---

## 2. BACKEND CONNECTIVITY

### 2.1 WebSocket Protocol

**Connection Details:**
- **Protocol:** WebSocket (ws://)
- **Default URL:** `ws://localhost:8765/ws`
- **Configuration:** Via `SERVER_WS_URL` environment variable
- **Reconnection:** Automatic with exponential backoff (1s → 30s max)
- **Keepalive:** Ping interval 20s, timeout 10s

### 2.2 Message Protocol

#### Client → Server Messages

| Message Type | Format | Purpose | Fields |
|-------------|--------|---------|--------|
| **session_start** | JSON | Initialize connection | `kiosk_id`, `kiosk_location` |
| **Audio frames** | Binary | Voice input (PCM16) | Raw audio bytes |
| **text_input** | JSON | Text query | `text`, `lang` (auto/en/ja) |
| **interrupt** | JSON | Barge-in signal | - |
| **session_reset** | JSON | Clear conversation history | - |

**Example: Session Start**
```json
{
  "type": "session_start",
  "kiosk_id": "kiosk-01",
  "kiosk_location": "Floor 1 Lobby"
}
```

**Example: Text Input**
```json
{
  "type": "text_input",
  "text": "What are the office hours?",
  "lang": "auto"
}
```

#### Server → Client Messages

| Message Type | Format | Purpose | Fields |
|-------------|--------|---------|--------|
| **session_ack** | JSON | Connection confirmed | `status: "ready"` |
| **transcript** | JSON | STT result | `text`, `language` |
| **llm_text_chunk** | JSON | Streaming LLM token | `text`, `final` (bool) |
| **status** | JSON | Pipeline state update | `state` (listening/recording/transcribing/thinking/speaking) |
| **Audio frames** | Binary | TTS audio (WAV format) | WAV audio bytes |

**Example: LLM Streaming**
```json
{
  "type": "llm_text_chunk",
  "text": "The office ",
  "final": false
}
{
  "type": "llm_text_chunk",
  "text": "is open from 9 AM to 5 PM.",
  "final": true
}
```

### 2.3 Audio Specifications

#### Microphone Input (Client → Server)
- **Format:** PCM16 (16-bit signed integer)
- **Sample Rate:** 16,000 Hz
- **Channels:** 1 (mono)
- **Frame Size:** 512 samples (32ms)
- **Encoding:** Raw binary, no container format

#### TTS Output (Server → Client)
- **Format:** WAV (RIFF container)
- **Sample Rate:** 24,000 Hz (typical)
- **Channels:** 1 (mono)
- **Encoding:** PCM16
- **Chunk Size:** Variable (sentence boundaries)

### 2.4 State Machine

The backend pipeline operates through these states:

```
listening → recording → transcribing → thinking → speaking → listening
                ↑______________________________________________|
                              (barge-in interrupt)
```

**State Transitions:**
1. **listening** → **recording**: VAD detects speech start
2. **recording** → **transcribing**: VAD detects speech end
3. **transcribing** → **thinking**: STT complete, LLM starting
4. **thinking** → **speaking**: First LLM token arrives
5. **speaking** → **listening**: LLM final chunk sent
6. **Any state** → **listening**: Interrupt (barge-in)

---

## 3. THREADING MODEL

### 3.1 Thread Architecture

The application uses a **two-thread model**:

#### Main Thread (Qt Event Loop)
- **Responsibilities:**
  - UI rendering and event handling
  - User input capture (clicks, key presses)
  - Signal/slot message passing
  - QTimer-based animations
- **Critical Rule:** All UI operations MUST occur on this thread

#### Worker Thread (AsyncIO Event Loop)
- **Responsibilities:**
  - WebSocket I/O
  - Audio capture streaming
  - Audio playback management
  - VAD processing
  - Network communication
- **Critical Rule:** All async operations occur on this thread's event loop

### 3.2 Thread Safety Mechanisms

#### PyQt Signals (Thread-Safe Communication)

```python
# Worker → Main thread communication
status_changed = pyqtSignal(str)        # Status updates
token_received = pyqtSignal(str)        # LLM tokens
response_start = pyqtSignal()           # New response bubble
response_done = pyqtSignal()            # Response complete
transcript_ready = pyqtSignal(str)      # STT result
mic_active = pyqtSignal(bool)           # Recording indicator
connected = pyqtSignal()                # Connection established
error_occurred = pyqtSignal(str)        # Error messages
manual_speak_done = pyqtSignal()        # Manual speak complete
manual_speak_timeout = pyqtSignal()     # 15s timeout
```

#### Main → Worker Communication

```python
# All operations scheduled via asyncio.run_coroutine_threadsafe()
asyncio.run_coroutine_threadsafe(
    self._activate_manual_speak(),
    self._loop  # Worker thread's event loop
)
```

### 3.3 Audio Playback Thread Safety

**Critical Design:** All sounddevice operations run in a **single-threaded executor**:

```python
_playback_executor = ThreadPoolExecutor(max_workers=1)
```

**Rationale:** PortAudio's ALSA backend is NOT thread-safe. Concurrent calls to `write()`, `abort()`, or `close()` cause heap corruption and core dumps.

**Implementation:**
- `_exec_open_stream()`: Opens audio stream (executor only)
- `_exec_write_chunk()`: Writes audio in 20ms sub-frames (executor only)
- `_exec_close_stream()`: Closes stream (executor only)
- `stop()`: Sets flags, NEVER touches stream directly (any thread)

---

## 4. STATE MANAGEMENT

### 4.1 Worker State

```python
class PipelineWorker(QObject):
    # Connection state
    _ws: WebSocketClient
    _loop: asyncio.AbstractEventLoop
    _running: bool
    
    # Audio components
    _audio_capture: AudioCapture
    _vad: SileroVAD
    _playback: AudioPlayback
    
    # Feature flags
    listening_enabled: bool         # Always-listen toggle
    _manual_speak_active: bool      # Manual speak mode
    _response_started: bool         # Bubble open flag
    
    # Async tasks
    _speak_timeout_task: asyncio.Task
    _synthesis_tasks: set[asyncio.Task]
```

### 4.2 VAD State Machine

```python
class SileroVAD:
    is_speaking: bool               # Currently in speech
    speech_buffer: bytearray        # Accumulated audio
    silence_counter: int            # Silence samples
    speech_counter: int             # Speech samples
    _pre_speech_buffer: bytearray   # Rolling 300ms buffer
```

**State Transitions:**
1. **Idle** → **Speech Start**: `speech_counter >= min_speech_samples` (200ms)
2. **Speaking** → **Speech End**: `silence_counter >= min_silence_samples` (800ms)

**Pre-Speech Buffer:** Keeps last 300ms of audio to avoid clipping speech onset

### 4.3 Conversation State

Managed entirely by the server backend:
- Client sends queries
- Server maintains conversation history
- Server includes relevant context in prompts
- Client displays messages in order

**Client Responsibilities:**
- Display user messages immediately
- Stream assistant tokens as they arrive
- Handle interrupts (barge-in)

---

## 5. USER INTERFACE COMPONENTS

### 5.1 Main Window (`KioskMainWindow`)

**Layout Structure:**
```
┌─────────────────────────────────────────────────────────┐
│ [Status Indicator ────────────────────────────] [✕]    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│                                                          │
│            Conversation Display Area                     │
│            (Scrollable chat bubbles)                     │
│                                                          │
│                                                          │
├─────────────────────────────────────────────────────────┤
│ [Text Input Field ─────────────] [Send ↵] [Clear ✕]    │
├─────────────────────────────────────────────────────────┤
│ 🎤 Mic Status | [🎙 Speak] [🔇 Always Listen: OFF] [🗑] │
└─────────────────────────────────────────────────────────┘
```

**Window Properties:**
- **Mode:** Fullscreen, frameless (`Qt.WindowType.FramelessWindowHint`)
- **Margins:** 32px left/right, 24px top/bottom
- **Spacing:** 16px between major sections
- **Background:** #0d1117 (dark blue-black)

### 5.2 Status Indicator Widget

**Component:** `StatusIndicator` (custom QLabel with animation)

**States:**
| State | Icon | Color | Animation |
|-------|------|-------|-----------|
| **Listening** | 🟢 | #a6e3a1 (green) | None |
| **Recording** | 🔴 | #f38ba8 (red) | Pulse (1.0 ↔ 0.6) |
| **Transcribing** | ⏳ | #f9e2af (amber) | None |
| **Processing** | 🟡 | #f9e2af (amber) | None |
| **Speaking** | 🔵 | #89b4fa (blue) | Pulse (1.0 ↔ 0.6) |
| **Idle** | ⚪ | #6c7086 (gray) | None |

**Animation Details:**
- **Type:** Opacity fade (QGraphicsOpacityEffect)
- **Duration:** 800ms per cycle
- **Easing:** Sine curve
- **Loop:** Infinite (-1)
- **Active States:** recording, speaking

**Implementation:**
```python
self._pulse_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
self._pulse_anim.setDuration(800)
self._pulse_anim.setStartValue(1.0)
self._pulse_anim.setEndValue(0.6)
self._pulse_anim.setLoopCount(-1)
```

### 5.3 Conversation Widget

**Component:** `ConversationWidget` (QTextEdit with rich text)

**Features:**
- **Read-only display:** Users cannot edit conversation history
- **Rich text formatting:** HTML-based message bubbles
- **Auto-scroll:** Always scrolls to bottom on new content
- **UTF-8 support:** Full Japanese/English character rendering
- **Streaming cursor:** Blinking ▋ during assistant response

**Message Types:**

#### User Message Bubble
```html
<p style="margin:6px 0">
  <span style="color:#89b4fa;font-weight:bold;">You</span>
  <span style="color:#585b70;"> ▸ </span>
  What are the office hours?
</p>
```

#### Assistant Message Bubble
```html
<p style="margin:6px 0">
  <span style="color:#a6e3a1;font-weight:bold;">Assistant</span>
  <span style="color:#585b70;"> ▸ </span>
  The office is open from 9 AM to 5 PM.
</p>
```

#### System Message
```html
<p style="margin:6px 0;color:#a6adc8;font-style:italic;">
  Connected. Speak or type your question.
</p>
```

**Streaming Implementation:**

1. **`start_assistant_bubble()`**: Creates new assistant line with ▋ cursor
2. **`append_to_last_message(token)`**: Inserts token before ▋, shifts cursor right
3. **`finish_assistant_bubble()`**: Removes ▋ cursor, stops blink timer

**Cursor Blink:**
- **Character:** ▋ (U+258B)
- **Interval:** 500ms
- **Implementation:** QTimer toggles insert/remove at `_cursor_anchor` position

**Highlight Animation:**
When user message appears:
- **Initial alpha:** 180 (blue background)
- **Fade steps:** 6 steps @ 100ms each
- **Final alpha:** 0 (transparent)
- **Color:** #2a4a8a (blue)

### 5.4 Keyboard Widget

**Component:** `KeyboardWidget` (QLineEdit + buttons)

**Layout:**
```
[Text Input Field ──────────────────────] [Send ↵] [Clear ✕]
      (flexible width)                      (110px)   (110px)
```

**Text Input Field:**
- **Placeholder:** "Type your question here and press Enter or Send..."
- **Height:** 52px
- **Enabled:** Only after connection established
- **Enter key:** Submits text (same as Send button)
- **Max length:** 1000 characters (enforced by `KeyboardInput` class)

**Send Button:**
- **Label:** "Send ↵"
- **Object Name:** `sendButton`
- **Color:** Cyan (#0097a7)
- **Behavior:** 
  - Submits text via `text_submitted` signal
  - Clears input field after submit
  - Disabled during assistant response streaming
  - Re-enabled when `final: true` chunk arrives

**Clear Button:**
- **Label:** "Clear ✕"
- **Object Name:** `clearButton`
- **Color:** Muted slate (#1e2d4a)
- **Behavior:** Clears input field immediately

**Submit Locking:**
```python
def set_submit_enabled(self, enabled: bool):
    self.send_button.setEnabled(enabled)
    if enabled:
        self.input_field.returnPressed.connect(self._submit_text)
    else:
        self.input_field.returnPressed.disconnect(self._submit_text)
```

This prevents double-submission during the ~500ms gap before first LLM token arrives.

### 5.5 Bottom Control Bar

**Layout:**
```
[🎤 Microphone: status...] [🎙 Speak] [⏹ Stop] [🔇 Always Listen: OFF] [🗑 Clear Session]
     (flexible width)        (130px)    (100px)        (220px)              (auto)
```

#### Microphone Status Label
- **Object Name:** `micStatus`
- **Height:** 44px
- **Alignment:** Left
- **Default State:** "🎤 Microphone: connecting..."
- **Dynamic States:**
  - "🔇 Always Listen OFF — press Speak to talk" (default)
  - "🎤 Microphone: always listening — just speak naturally" (always-listen ON)
  - "🔴 Recording — speak now..." (active capture, red #f38ba8)
  - "⏳ Transcribing your speech..." (amber #f9e2af)
  - "🔌 Server offline - restart server and client" (error)

#### Speak Button
- **Label:** "🎙 Speak"
- **Object Name:** `speakButton`
- **Color:** Vivid coral (#e63462)
- **Height:** 44px
- **Visibility:** Shown when always-listen is OFF
- **Behavior:**
  - Press → activates manual speak mode
  - VAD detects end of speech → auto-deactivates
  - Timeout after 15s → auto-deactivates
  - Switches to Stop button while active

#### Stop Button
- **Label:** "⏹ Stop"
- **Object Name:** `stopButton`
- **Color:** Vivid amber (#e67e00)
- **Height:** 44px
- **Visibility:** Hidden by default, shown during manual speak
- **Behavior:** Flushes VAD buffer and sends audio immediately

#### Always Listen Toggle
- **Labels:**
  - OFF: "🔇 Always Listen: OFF"
  - ON: "🎤 Always Listen: ON"
- **Object Names:** `toggleOffButton` (OFF), `toggleOnButton` (ON)
- **Colors:**
  - OFF: Muted slate (#1e2d4a, gray text)
  - ON: Vivid green (#1db954, white text)
- **Height:** 44px
- **Behavior:**
  - OFF → ON: Enables continuous VAD, hides Speak button
  - ON → OFF: Disables VAD, shows Speak button

#### Clear Session Button
- **Label:** "🗑 Clear Session"
- **Object Name:** `clearSessionButton`
- **Color:** Purple/violet (#2a1a3a)
- **Behavior:**
  - Clears conversation widget
  - Resets worker state (`_response_started = False`)
  - Sends `{"type": "session_reset"}` to server
  - Displays system message: "Session cleared — ready for new demo."

#### Close Button (Top Right)
- **Label:** "✕"
- **Object Name:** `closeButton`
- **Size:** 56×56px
- **Color:** Muted slate (hover: vivid coral)
- **Behavior:** Stops worker, closes WebSocket, exits application

---

## 6. VISUAL DESIGN (QSS STYLING)

### 6.1 Color Palette

**Theme:** Dark Blue Professional Kiosk

| Element | Color Code | Usage |
|---------|-----------|-------|
| **Background (Main)** | #0d1117 | Window background |
| **Background (Alt)** | #0a0f1a | Text edit area |
| **Surface** | #161b27 | Buttons, input fields |
| **Border** | #1e2d4a | Component borders |
| **Border (Focus)** | #4d8fff | Active input border |
| **Text (Primary)** | #f0f4ff | Main text |
| **Text (Secondary)** | #8899bb | Mic status |
| **Text (Muted)** | #3a4a66 | Disabled state |
| **User Bubble** | #89b4fa | Blue |
| **Assistant Bubble** | #a6e3a1 | Green |
| **System Message** | #a6adc8 | Light gray |
| **Accent (Success)** | #1db954 | Always-listen ON |
| **Accent (Warning)** | #e67e00 | Stop button |
| **Accent (Danger)** | #e63462 | Speak button |
| **Accent (Info)** | #0097a7 | Send button |

### 6.2 Typography

**Font Stack:**
```css
font-family: "Noto Sans CJK JP", "Yu Gothic UI", "Meiryo UI", 
             "Segoe UI", "Noto Sans", Arial, sans-serif;
```

**Size Scale:**
- **Status labels:** 24px (bold)
- **Conversation:** 19px
- **Input fields:** 18px
- **Buttons:** 17px (bold)
- **Small buttons:** 15px (Speak, Stop, Toggle)
- **Close button:** 20px (bold)

### 6.3 Border Radius

- **Large components:** 12px (TextEdit)
- **Medium components:** 10px (Buttons, Input, Status)
- **Small components:** 6px (Close button)
- **Scrollbar handle:** 5px

### 6.4 Button States

**Hover Effect:**
```css
background-color: /* Lighten by ~10% */
```

**Pressed Effect:**
```css
background-color: /* Darken by ~20% */
```

**Disabled Effect:**
```css
background-color: #161b27;
color: #3a4a66;
```

### 6.5 Accessibility

**Focus Indicators:**
- Input fields: 2px solid #4d8fff border
- Buttons: Native Qt focus rectangle

**Color Contrast:**
- Text on dark background: WCAG AA compliant (4.5:1 minimum)
- Status icons provide redundancy for color-blind users

**Keyboard Navigation:**
- Tab order: Status → Conversation → Input → Send → Clear → Speak → Toggle → Clear Session → Close
- Enter key: Submits text from input field

---

## 7. USER WORKFLOWS

### 7.1 Voice Input (Always-Listen Mode)

**Precondition:** Always-listen toggle is ON

```
1. User speaks naturally
2. VAD detects speech start
   → Status: "🔴 Recording"
   → Mic status: "🔴 Recording — speak now..."
3. User finishes speaking
4. VAD detects 800ms silence
   → Status: "⏳ Transcribing"
   → Audio sent to server
5. Server returns transcript
   → User bubble appears with text
   → Status: "🟡 Processing"
6. LLM tokens arrive
   → Assistant bubble opens
   → Tokens stream into bubble
   → Status: "🔵 Speaking"
   → TTS audio plays
7. LLM final chunk arrives
   → Bubble closes
   → Status: "🟢 Listening"
8. Cycle repeats
```

### 7.2 Voice Input (Manual Speak Mode)

**Precondition:** Always-listen toggle is OFF

```
1. User presses "🎙 Speak" button
   → Button changes to "⏹ Stop"
   → Status: "🔴 Recording"
   → 15-second timeout starts
2. User speaks
3. Option A: VAD detects end of speech
   → Audio sent automatically
   → Button resets to "🎙 Speak"
   → Continue from step 5 above
4. Option B: User presses "⏹ Stop"
   → VAD buffer flushed
   → Audio sent immediately
   → Button resets to "🎙 Speak"
   → Continue from step 5 above
5. Option C: 15-second timeout
   → VAD buffer flushed
   → Audio sent automatically
   → Button resets to "🎙 Speak"
   → Continue from step 5 above
```

### 7.3 Text Input

```
1. User types question in input field
2. User presses Enter or clicks "Send ↵"
   → Send button disables
   → Input field clears
   → User bubble appears immediately
   → Status: "🟡 Processing"
3. LLM tokens arrive
   → Assistant bubble opens
   → Tokens stream into bubble
   → Status: "🔵 Speaking"
   → TTS audio plays
4. LLM final chunk arrives
   → Bubble closes
   → Status: "🟢 Listening"
   → Send button re-enables
```

### 7.4 Barge-In (Interrupt)

**Trigger:** New audio input while assistant is speaking

```
1. Assistant is speaking (TTS playing)
2. User starts speaking (or presses Speak button)
3. Client detects audio input
   → Sends interrupt to server
   → Stops TTS playback immediately
   → Drains all audio queues
4. Server aborts LLM generation
   → Sends final=true chunk
   → Client closes current bubble
5. New query processed normally
```

### 7.5 Session Reset

```
1. User clicks "🗑 Clear Session"
2. Conversation widget clears
3. Worker state resets
4. Server receives {"type": "session_reset"}
5. Server clears conversation history
6. System message: "Session cleared — ready for new demo."
```

---

## 8. ERROR HANDLING

### 8.1 Connection Errors

**Scenario:** Server unreachable at startup

```
Error: "⚠️ Server connection failed - check if server is running"
Mic Status: "🔌 Server offline - restart server and client"
Buttons: All disabled (except Close)
Reconnection: Exponential backoff (1s → 2s → 4s → ... → 30s max)
```

### 8.2 Audio Capture Errors

**Scenario:** No microphone available

```
Error: "⚠️ Microphone error - check audio permissions"
Mic Status: "🎤 Microphone unavailable - check settings"
Behavior: Text input still works
Reconnection: Retries 3 times with 2s delay
```

### 8.3 VAD Errors

**Scenario:** Silero model download fails

```
Error: "⚠️ Audio processing error - missing dependencies"
Mic Status: "📦 Missing audio libraries - run pip install"
Buttons: Disabled
Recovery: Requires manual intervention
```

### 8.4 WebSocket Disconnect

**Scenario:** Connection drops mid-session

```
Behavior: Automatic reconnection (exponential backoff)
User Impact: Minimal (transparent to user if reconnection succeeds)
State: Conversation history preserved on server
```

---

## 9. CONFIGURATION

### 9.1 Environment Variables

**File:** `.env` or `.env.local`

```bash
# Server Connection
SERVER_WS_URL=ws://localhost:8765/ws

# Kiosk Metadata
KIOSK_ID=kiosk-01
KIOSK_LOCATION=Floor 1 Lobby
```

### 9.2 Audio Device Selection

**Automatic Selection Priority:**
1. PulseAudio devices (WSLg compatible)
2. Default input device
3. First available input device
4. Fallback to device 0

**Manual Override:** Not currently supported (would require UI dropdown)

### 9.3 VAD Parameters

**Tunable in `vad.py`:**
```python
threshold = 0.3                 # Speech probability (0.0-1.0)
min_speech_duration_ms = 200    # Min speech before triggering
min_silence_duration_ms = 800   # Min silence before end
```

---

## 10. DEPLOYMENT

### 10.1 SystemD Service

**File:** `kiosk.service`

```ini
[Unit]
Description=Voice Kiosk Chatbot Client
After=graphical.target network-online.target sound.target

[Service]
Type=simple
User=kiosk
WorkingDirectory=/home/kiosk/voice-kiosk-chatbot
Environment="DISPLAY=:0"
Environment="XDG_RUNTIME_DIR=/run/user/1000"
ExecStart=/usr/bin/python3 client/main.py
Restart=on-failure
RestartSec=3s

[Install]
WantedBy=graphical.target
```

**Commands:**
```bash
# Enable service
sudo systemctl enable kiosk.service

# Start service
sudo systemctl start kiosk.service

# Check status
sudo systemctl status kiosk.service

# View logs
journalctl -u kiosk.service -f
```

### 10.2 WSL2 Compatibility

**Audio Setup:**
```bash
# Set PulseAudio socket
export PULSE_SERVER=unix:/mnt/wslg/PulseServer

# Disable ALSA RT scheduling
export PA_ALSA_PLUGHW=1
```

**Display Setup:**
```bash
# WSLg provides DISPLAY automatically
echo $DISPLAY  # Should be :0
```

---

## 11. TESTING RECOMMENDATIONS

### 11.1 Unit Testing

**Components to Test:**
- `WebSocketClient`: Connection, reconnection, message handling
- `SileroVAD`: Speech detection accuracy, buffer management
- `AudioCapture`: Device selection, frame generation
- `AudioPlayback`: WAV decoding, queue management
- `KeyboardInput`: Text validation, length enforcement

**Framework:** pytest + pytest-qt

### 11.2 Integration Testing

**Scenarios:**
- Voice input → STT → LLM → TTS → Playback
- Text input → LLM → TTS → Playback
- Barge-in during TTS playback
- Always-listen toggle switching
- Manual speak mode with timeout
- Session reset

### 11.3 UI Testing

**Manual Test Cases:**
- [ ] All buttons respond to clicks
- [ ] Text input accepts Enter key
- [ ] Conversation scrolls to bottom
- [ ] Streaming cursor blinks
- [ ] Status animations play correctly
- [ ] Mic status updates live
- [ ] Error messages display properly
- [ ] Japanese characters render correctly

### 11.4 Performance Testing

**Metrics:**
- Audio latency (input → output): Target < 3s
- UI responsiveness: Target 60 FPS
- Memory usage: Target < 500 MB (steady state)
- WebSocket reconnection time: Target < 5s

---

## 12. KNOWN LIMITATIONS

### 12.1 Audio Constraints

- **Single device:** Cannot switch microphones without restart
- **Fixed sample rate:** 16kHz input, 24kHz output (not configurable)
- **ALSA issues:** Requires specific environment variables on WSL2
- **PortAudio thread safety:** Must use single-threaded executor for playback

### 12.2 UI Constraints

- **Fullscreen only:** No windowed mode option
- **Fixed layout:** No responsive resizing
- **No dark/light toggle:** Dark theme hardcoded
- **Limited accessibility:** No screen reader support

### 12.3 Protocol Constraints

- **No authentication:** WebSocket connection is unauthenticated
- **No encryption:** Traffic sent in plaintext (ws:// not wss://)
- **Single connection:** One client per WebSocket connection
- **No offline mode:** Requires constant server connectivity

---

## 13. FUTURE ENHANCEMENT OPPORTUNITIES

### 13.1 UI Improvements

1. **Windowed mode option** (not just fullscreen)
2. **Theme selector** (dark/light toggle)
3. **Font size controls** (accessibility)
4. **Audio device dropdown** (manual selection)
5. **Volume controls** (TTS output level)
6. **Conversation export** (save chat history to file)

### 13.2 Audio Improvements

1. **Noise cancellation** (background noise filtering)
2. **Echo cancellation** (prevent TTS feedback)
3. **Audio device hot-swap** (detect device changes)
4. **Multi-channel support** (stereo audio)

### 13.3 Protocol Improvements

1. **WebSocket authentication** (token-based auth)
2. **TLS encryption** (wss://)
3. **Compression** (gzip for text messages)
4. **Offline queue** (store messages when disconnected)

### 13.4 Accessibility Improvements

1. **Screen reader support** (ARIA-like announcements)
2. **High contrast mode** (WCAG AAA compliance)
3. **Keyboard shortcuts** (Ctrl+Enter, Ctrl+L, etc.)
4. **Speech rate control** (adjust TTS speed)

---

## 14. REGRESSION PREVENTION GUIDELINES

### 14.1 Thread Safety Rules

**CRITICAL:** All sounddevice operations MUST occur via `_playback_executor`

**Allowed:**
```python
await loop.run_in_executor(_playback_executor, self._exec_write_chunk, audio)
```

**FORBIDDEN:**
```python
self._sd_stream.write(audio)  # NEVER call from main/worker thread directly
```

### 14.2 Signal/Slot Rules

**CRITICAL:** Never block UI thread with long-running operations

**Allowed:**
```python
# Emit signal from worker → updates UI on main thread
self.token_received.emit(token)
```

**FORBIDDEN:**
```python
# Heavy computation on main thread
def _on_token(self, token):
    result = expensive_computation(token)  # Blocks UI
```

### 14.3 VAD State Rules

**CRITICAL:** Always reset VAD before manual speak mode

**Allowed:**
```python
async def _activate_manual_speak(self):
    if self._vad:
        self._vad.reset()  # Clean state before activation
    self._manual_speak_active = True
```

**FORBIDDEN:**
```python
# Activating without reset causes false speech_start
self._manual_speak_active = True  # BAD: stale counters
```

### 14.4 Response Bubble Rules

**CRITICAL:** Always set `_response_started = False` before new query

**Allowed:**
```python
# Before sending new query
self._response_started = False
self.transcript_ready.emit(text)
```

**FORBIDDEN:**
```python
# Sending query without reset causes token append to wrong bubble
self.transcript_ready.emit(text)  # BAD: may reuse bubble
```

### 14.5 Interrupt Handling Rules

**CRITICAL:** Cancel synthesis tasks BEFORE draining queues

**Allowed:**
```python
# Cancel all in-flight TTS tasks
for t in tasks_to_cancel:
    t.cancel()
await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
# NOW safe to drain queues
await self._drain_queue(self.state.audio_output)
```

**FORBIDDEN:**
```python
# Draining before canceling causes resumed TTS after interrupt
await self._drain_queue(self.state.audio_output)  # BAD
for t in tasks_to_cancel:
    t.cancel()  # Too late — tasks may have queued more audio
```

---

## 15. DEPENDENCY ANALYSIS

### 15.1 Direct Dependencies

| Package | Version | Purpose | Criticality |
|---------|---------|---------|-------------|
| **PyQt6** | 6.11.0 | UI framework | CRITICAL |
| **PyQt6-Qt6** | 6.11.0 | Qt binaries | CRITICAL |
| **PyQt6-sip** | 13.11.1 | Python bindings | CRITICAL |
| **websockets** | 12.0 | WebSocket client | CRITICAL |
| **sounddevice** | 0.4.6 | Audio I/O | CRITICAL |
| **torch** | 2.1.0 | VAD model runtime | CRITICAL |
| **torchaudio** | 2.1.0 | Audio utilities | HIGH |
| **numpy** | 1.24.3 | Audio processing | HIGH |
| **python-dotenv** | 1.0.0 | Config loading | MEDIUM |

### 15.2 System Dependencies

| Dependency | Purpose | Platform |
|-----------|---------|----------|
| **PortAudio** | Audio backend | All |
| **ALSA** | Linux audio | Linux |
| **PulseAudio** | Audio server | Linux |
| **X11/Wayland** | Display server | Linux |
| **WSLg** | GUI/audio for WSL2 | WSL2 |

### 15.3 Dependency Risks

**High Risk:**
- **PyQt6:** UI framework upgrade may break QSS styling
- **torch:** Large download (>800MB), slow model loading

**Medium Risk:**
- **websockets:** Protocol changes may affect reconnection logic
- **sounddevice:** PortAudio API changes may affect thread safety

**Low Risk:**
- **numpy:** Well-established, stable API
- **python-dotenv:** Simple, unlikely to break

---

## 16. PERFORMANCE CHARACTERISTICS

### 16.1 Latency Breakdown

**Voice Query (Always-Listen Mode):**
```
User speaks → VAD detects end (800ms silence) → Audio sent
   ↓
Server STT (0.5-2s) → Server LLM (0.5-3s) → Server TTS (0.3-1s)
   ↓
Audio arrives → Client playback starts
```

**Total Latency:** 2-7 seconds (typical: 3-4s)

**Text Query:**
```
User types → Enter pressed → Server LLM (0.5-3s) → Server TTS (0.3-1s)
   ↓
Audio arrives → Client playback starts
```

**Total Latency:** 0.8-4 seconds (typical: 1.5-2s)

### 16.2 Memory Usage

**Baseline (Connected, Idle):**
- PyQt6 UI: ~100 MB
- torch + Silero VAD: ~200 MB
- Python runtime: ~50 MB
- **Total:** ~350 MB

**Peak (Active Conversation):**
- Audio buffers: ~50 MB
- WebSocket buffers: ~10 MB
- Conversation history: ~5 MB
- **Total:** ~415 MB

### 16.3 CPU Usage

**Idle:** <1% (Qt event loop only)
**Recording:** 5-10% (VAD inference)
**Playback:** 2-5% (audio decoding)
**Peak:** 15-20% (VAD + playback simultaneous)

### 16.4 Network Bandwidth

**Upstream (Client → Server):**
- Audio: 32 KB/s (16kHz PCM16)
- Control messages: <1 KB/s
- **Total:** ~33 KB/s during recording

**Downstream (Server → Client):**
- Audio: 48 KB/s (24kHz PCM16 WAV)
- LLM tokens: 1-5 KB/s (streaming text)
- **Total:** ~50 KB/s during response

---

## 17. CODE QUALITY METRICS

### 17.1 Module Complexity

| Module | Lines | Functions | Classes | Complexity |
|--------|-------|-----------|---------|------------|
| **app.py** | 450 | 25 | 2 | HIGH |
| **ws_client.py** | 120 | 7 | 1 | LOW |
| **audio_capture.py** | 180 | 6 | 2 | MEDIUM |
| **audio_playback.py** | 320 | 12 | 1 | HIGH |
| **vad.py** | 200 | 5 | 2 | MEDIUM |
| **conversation_widget.py** | 280 | 15 | 1 | MEDIUM |
| **keyboard_widget.py** | 80 | 6 | 1 | LOW |
| **status_indicator.py** | 90 | 3 | 1 | LOW |

### 17.2 Code Quality Observations

**Strengths:**
- Well-documented with docstrings
- Clear separation of concerns
- Consistent naming conventions
- Thread-safety explicitly handled
- Error handling comprehensive

**Areas for Improvement:**
- `app.py` is too large (450 lines) — consider splitting PipelineWorker
- `audio_playback.py` has complex thread synchronization — add more inline comments
- Limited type hints (only in function signatures)
- No unit tests included

---

## 18. SECURITY CONSIDERATIONS

### 18.1 Network Security

**Current State:**
- **Protocol:** Unencrypted WebSocket (ws://)
- **Authentication:** None
- **Input validation:** Server-side only

**Risks:**
- Man-in-the-middle attacks (audio/text interception)
- Unauthorized access to kiosk
- DoS via flood of audio frames

**Mitigations (Recommended):**
1. Upgrade to WSS (WebSocket Secure)
2. Implement token-based authentication
3. Add rate limiting on server

### 18.2 Audio Privacy

**Current State:**
- Audio transmitted in cleartext
- No local recording or caching
- Conversation history on server only

**Risks:**
- Network eavesdropping
- Server-side audio logging

**Mitigations (Recommended):**
1. End-to-end encryption for audio
2. Server-side audio deletion policy
3. Privacy notice on kiosk UI

### 18.3 Input Validation

**Current State:**
- Text input: 1000 char max (client-side)
- Audio input: No validation (trust server)

**Risks:**
- Buffer overflow if server returns malformed data
- XSS via conversation widget (HTML injection)

**Mitigations (Implemented):**
- HTML escaping in `conversation_widget.py`:
  ```python
  @staticmethod
  def _escape(text: str) -> str:
      return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
  ```

---

## 19. MAINTENANCE GUIDELINES

### 19.1 Adding New UI Components

**Steps:**
1. Create widget class in `ui/` directory
2. Inherit from appropriate Qt class (QWidget, QPushButton, etc.)
3. Define signals for thread-safe communication
4. Add stylesheet rules to `styles.qss`
5. Integrate into `app.py` layout
6. Update this audit document

**Example:**
```python
# ui/volume_slider.py
from PyQt6.QtWidgets import QSlider
from PyQt6.QtCore import pyqtSignal

class VolumeSlider(QSlider):
    volume_changed = pyqtSignal(float)
    
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.valueChanged.connect(self._on_value_changed)
    
    def _on_value_changed(self, value: int):
        self.volume_changed.emit(value / 100.0)
```

### 19.2 Modifying Audio Pipeline

**CRITICAL:** All changes MUST preserve thread safety

**Checklist:**
- [ ] Does this modify `_playback_executor` operations?
- [ ] Does this add new sounddevice calls?
- [ ] Does this change VAD state machine?
- [ ] Are all async operations scheduled via `run_coroutine_threadsafe`?
- [ ] Are new signals added to `PipelineWorker`?

### 19.3 Updating WebSocket Protocol

**Steps:**
1. Update message schemas in this document
2. Update `ws_client.py` if new message types
3. Update `handle_control_message()` in `app.py`
4. Update `_receive_loop()` in `app.py`
5. Coordinate with backend team
6. Test backwards compatibility

### 19.4 Styling Changes

**QSS File Structure:**
```css
/* Window background */
QMainWindow, QWidget { ... }

/* Status indicator */
QLabel { ... }
QLabel#micStatus { ... }

/* Conversation */
QTextEdit { ... }

/* Input */
QLineEdit { ... }

/* Buttons */
QPushButton { ... }
QPushButton#sendButton { ... }
QPushButton#speakButton { ... }
/* ... etc ... */

/* Scrollbar */
QScrollBar:vertical { ... }
```

**Best Practices:**
- Use `setObjectName()` for specific component styling
- Test on actual hardware (colors may differ from dev machine)
- Maintain color contrast ratios (WCAG AA minimum)

---

## 20. TROUBLESHOOTING GUIDE

### 20.1 Common Issues

#### Issue: "WebSocket connection failed"
**Symptoms:** Red error message, all buttons disabled
**Causes:**
1. Server not running
2. Wrong SERVER_WS_URL in .env
3. Firewall blocking port 8765

**Solutions:**
```bash
# Check server status
curl http://localhost:8765/health

# Check environment
cat .env | grep SERVER_WS_URL

# Test connection
wscat -c ws://localhost:8765/ws
```

#### Issue: "Microphone unavailable"
**Symptoms:** Amber error message, text input still works
**Causes:**
1. No microphone connected
2. Wrong audio device selected
3. PortAudio/ALSA configuration issue (WSL2)

**Solutions:**
```bash
# List audio devices
python -c "import sounddevice; print(sounddevice.query_devices())"

# WSL2: Set environment variables
export PULSE_SERVER=unix:/mnt/wslg/PulseServer
export PA_ALSA_PLUGHW=1
```

#### Issue: "VAD not detecting speech"
**Symptoms:** Speak button pressed, no recording status
**Causes:**
1. Threshold too high (0.3 default)
2. Background noise
3. Microphone too quiet

**Solutions:**
```python
# In vad.py, lower threshold
threshold=0.2  # Was 0.3

# Or increase mic sensitivity in OS settings
```

#### Issue: "Audio playback stutters"
**Symptoms:** Choppy TTS audio, robot voice
**Causes:**
1. Network latency (audio chunks delayed)
2. CPU overload
3. Audio driver issues

**Solutions:**
```python
# In audio_playback.py, increase buffer
# (NOT RECOMMENDED — increases latency)
frame_samples = int(self._sd_rate * 0.05)  # 50ms vs 20ms
```

#### Issue: "Cursor stops blinking mid-response"
**Symptoms:** Static ▋ character, tokens still arriving
**Causes:**
1. Timer stopped unexpectedly
2. Exception in `_toggle_cursor()`

**Solutions:**
- Check logs for exceptions
- Restart application
- Report bug with reproduction steps

### 20.2 Debug Mode

**Enable verbose logging:**
```python
# In main.py, change logging level
logging.basicConfig(
    level=logging.DEBUG,  # Was INFO
    ...
)
```

**Output:**
```
2026-06-17 10:30:45 - client.ws_client - DEBUG - Sending JSON: {"type": "text_input", ...}
2026-06-17 10:30:45 - client.ui.app - DEBUG - VAD event: speech_start
2026-06-17 10:30:46 - client.audio_playback - DEBUG - Decoded WAV: 24000Hz, 48000 bytes
```

---

## 21. GLOSSARY

| Term | Definition |
|------|------------|
| **VAD** | Voice Activity Detection — algorithm that detects speech in audio |
| **TTS** | Text-to-Speech — synthesis of spoken audio from text |
| **STT** | Speech-to-Text — transcription of audio to text (Whisper) |
| **LLM** | Large Language Model — AI that generates text responses |
| **PCM16** | Pulse-Code Modulation 16-bit — uncompressed audio format |
| **WAV** | Waveform Audio File Format — audio container format |
| **Barge-in** | User interrupts assistant mid-response with new input |
| **QSS** | Qt Style Sheets — CSS-like styling for Qt widgets |
| **AsyncIO** | Python library for asynchronous I/O operations |
| **PortAudio** | Cross-platform audio I/O library |
| **ALSA** | Advanced Linux Sound Architecture |
| **PulseAudio** | Sound server for Linux |
| **WSLg** | Windows Subsystem for Linux GUI support |

---

## 22. CONCLUSION

### 22.1 System Maturity

**Production Readiness: 85%**

**Strengths:**
- ✅ Robust thread-safety architecture
- ✅ Comprehensive error handling
- ✅ Clean separation of concerns
- ✅ Well-documented code
- ✅ Multiple deployment modes
- ✅ Graceful degradation (text input when mic fails)

**Missing for 100%:**
- ❌ No authentication/encryption
- ❌ No unit tests
- ❌ Limited accessibility features
- ❌ No metrics/monitoring
- ❌ No A/B testing framework

### 22.2 Critical Success Factors

For successful frontend changes:
1. **Maintain thread safety** — Never call sounddevice from main thread
2. **Preserve signal/slot patterns** — Worker → Main communication
3. **Test on target hardware** — Dev machine ≠ production kiosk
4. **Coordinate with backend** — Protocol changes require both sides
5. **Document all changes** — Update this audit for regression prevention

### 22.3 Technical Debt

**High Priority:**
1. Split `app.py` into smaller modules (PipelineWorker → separate file)
2. Add unit tests (pytest + pytest-qt)
3. Implement WebSocket authentication

**Medium Priority:**
1. Add audio device selection UI
2. Improve error recovery (auto-restart on crash)
3. Add conversation export feature

**Low Priority:**
1. Theme customization (dark/light toggle)
2. Font size controls
3. Keyboard shortcuts

---

## APPENDIX A: FILE REFERENCE

### A.1 Configuration Files

| File | Purpose | Format |
|------|---------|--------|
| `.env` | Environment variables | Key=Value |
| `requirements.txt` | Python dependencies | pip format |
| `kiosk.service` | SystemD service definition | INI |

### A.2 Source Files

| File | Lines | Primary Responsibility |
|------|-------|----------------------|
| `main.py` | 180 | Entry point, mode selection |
| `config.py` | 35 | Configuration dataclass |
| `ws_client.py` | 120 | WebSocket communication |
| `audio_capture.py` | 180 | Microphone input streaming |
| `audio_playback.py` | 320 | TTS audio output |
| `vad.py` | 200 | Silero VAD integration |
| `keyboard_input.py` | 80 | Text input validation |
| `ui/app.py` | 450 | Main window + worker thread |
| `ui/conversation_widget.py` | 280 | Chat display |
| `ui/keyboard_widget.py` | 80 | Text input UI |
| `ui/status_indicator.py` | 90 | Status display |
| `ui/styles.qss` | 200 | Visual styling |

### A.3 Key Classes

| Class | Module | Purpose |
|-------|--------|---------|
| `ClientConfig` | config.py | Config management |
| `WebSocketClient` | ws_client.py | WebSocket I/O |
| `AudioCapture` | audio_capture.py | Mic input |
| `AudioPlayback` | audio_playback.py | Audio output |
| `SileroVAD` | vad.py | Speech detection |
| `KeyboardInput` | keyboard_input.py | Text validation |
| `KioskMainWindow` | ui/app.py | Main window |
| `PipelineWorker` | ui/app.py | Background async worker |
| `ConversationWidget` | ui/conversation_widget.py | Chat display |
| `KeyboardWidget` | ui/keyboard_widget.py | Text input UI |
| `StatusIndicator` | ui/status_indicator.py | Status display |

---

## APPENDIX B: MESSAGE FLOW DIAGRAMS

### B.1 Voice Input Flow

```
┌─────────┐                                    ┌────────┐
│  User   │                                    │ Server │
└────┬────┘                                    └───┬────┘
     │                                             │
     │ [Speaks]                                   │
     ├─────────────────────────────────────────┐  │
     │ AudioCapture                            │  │
     │   → VAD (detects speech_end)           │  │
     │     → WebSocket                          │  │
     │                                          ▼  │
     │                                   [Binary Audio]
     │                                             │
     │                                    [STT → LLM → TTS]
     │                                             │
     │                                  ◀─────────┤
     │                         {"type": "transcript", ...}
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  {"type": "llm_text_chunk", "text": "The", ...}
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  {"type": "llm_text_chunk", "text": " office", ...}
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  [Binary WAV audio chunk 1]                │
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  [Binary WAV audio chunk 2]                │
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  {"type": "llm_text_chunk", "final": true} │
     │                                             │
     ▼                                             ▼
```

### B.2 Text Input Flow

```
┌─────────┐                                    ┌────────┐
│  User   │                                    │ Server │
└────┬────┘                                    └───┬────┘
     │                                             │
     │ [Types + Enter]                            │
     ├────────────────────────────────────────────▶│
     │ {"type": "text_input", "text": "...", ...} │
     │                                             │
     │                                    [LLM → TTS]
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  {"type": "llm_text_chunk", ...}           │
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  [Binary WAV audio]                        │
     │                                             │
     ▼                                             ▼
```

### B.3 Barge-In Flow

```
┌─────────┐                                    ┌────────┐
│  User   │                                    │ Server │
└────┬────┘                                    └───┬────┘
     │                                             │
     │ [Assistant speaking...]                    │
     │  ◀──────────────────────────────────────────┤
     │  [Binary WAV audio streaming]              │
     │                                             │
     │ [User speaks (interrupt)]                  │
     ├─────────────────────────────────────────▶  │
     │ [Audio input detected]                     │
     │                                             │
     │ [Client stops TTS playback]                │
     ├────────────────────────────────────────────▶│
     │ {"type": "interrupt"}                      │
     │                                             │
     │                                    [Abort LLM/TTS]
     │                                             │
     │  ◀──────────────────────────────────────────┤
     │  {"type": "llm_text_chunk", "final": true} │
     │                                             │
     │ [New query starts...]                      │
     │                                             │
     ▼                                             ▼
```

---

**END OF AUDIT**

---

**Document Control:**
- **Version:** 1.0
- **Status:** Complete
- **Next Review:** Quarterly or on major changes
- **Owner:** Development Team
- **Last Updated:** June 17, 2026
