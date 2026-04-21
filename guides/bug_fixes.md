# Bug Fix Guide

Reference for a coding agent to implement fixes directly. No design overhead — just file, problem, fix.

---

## STT / Voice Input Bugs

### STT-BUG-001 — `manual_speak_done` signal defined twice on `PipelineWorker`; second definition silently shadows the first, breaking the signal entirely

**File:** `client/ui/app.py`  
**Lines:** 40 and 216  
**Symptom:** After speech ends, `manual_speak_done.emit()` is called inside `_capture_loop` (line 183) but the connected slot `_on_manual_speak_done` never fires — so the Speak button never resets and the UI stays stuck in recording state. More critically, because the signal object is re-declared at line 216, the one connected at line 387 is the *second* (empty, unconnected) instance, not the one that `emit()` is called on.

**Root cause:**  
`PipelineWorker` declares `manual_speak_done = pyqtSignal()` twice:
- Line 40: inside the class body with the other signals (correct location)
- Line 216: again, after the `_capture_loop` method (duplicate, wrong location)

In Python, the second class-level assignment overwrites the first. The signal that `_capture_loop` calls `.emit()` on is the one from line 40 (the descriptor on the instance), but the one that `_start_pipeline` connects to (`self._worker.manual_speak_done`) resolves to the second descriptor. They are different objects — emit on one, listener on the other → slot never fires.

Additionally, `_start_pipeline` connects `manual_speak_done` **twice** (line 387 appears twice):
```python
self._worker.manual_speak_done.connect(self._on_manual_speak_done)
self._worker.manual_speak_done.connect(self._on_manual_speak_done)
```
This means if the signal ever does fire, `_on_manual_speak_done` runs twice.

**Fix:**  
1. Delete the duplicate signal declaration at line 216 (the one after `_capture_loop`).
2. Remove the duplicate `.connect()` call in `_start_pipeline` — keep only one.

```python
# In PipelineWorker class body — keep ONLY this one (line ~40):
manual_speak_done = pyqtSignal()

# DELETE the second one at line ~216:
# manual_speak_done = pyqtSignal()   <-- remove this

# In _start_pipeline — keep only ONE connect:
self._worker.manual_speak_done.connect(self._on_manual_speak_done)
# DELETE the duplicate line below it
```

---

### STT-BUG-002 — VAD `speech_counter` never accumulates enough samples in manual speak mode because frames are gated before VAD runs

**File:** `client/ui/app.py`  
**Method:** `_capture_loop()`  
**Symptom:** User presses Speak, starts talking, but `speech_start` is never logged and no audio is ever sent. The VAD's `speech_counter` needs to accumulate `min_speech_samples` (200ms × 16000 / 1000 = 3200 samples) before it fires `speech_start`. But because frames are skipped when `should_process` is False, the VAD state machine is never warm — when the user presses Speak and starts talking immediately, the first ~200ms of speech is missed and the counter starts from 0.

**Root cause:**  
The gate check:
```python
should_process = self.listening_enabled or self._manual_speak_active
if not should_process:
    continue
```
skips all frames when idle. The VAD model itself is stateful (Silero VAD maintains internal hidden state across frames). When frames are skipped, the model's internal state goes stale. When processing resumes, the model needs a few frames to "warm up" again, during which it may not detect speech reliably.

**Fix:**  
Always feed frames to the VAD model to keep its internal state current, but only act on the resulting events when `should_process` is True:

```python
# Always run VAD to keep model state warm
try:
    event = self._vad.process_frame(frame)
except Exception as e:
    logger.warning(f"VAD processing error: {e}")
    continue

# Only act on events when listening is enabled
should_process = self.listening_enabled or self._manual_speak_active
if not should_process or event is None:
    continue

# Handle events below (existing code unchanged)
logger.debug(f"VAD event: {event.event_type}")
...
```

---

### STT-BUG-003 — `speech_counter` is not reset when `_manual_speak_active` transitions from False to True; stale counter causes immediate false `speech_start`

**File:** `client/vad.py`  
**Symptom:** Occasionally, pressing Speak immediately fires `speech_start` even before the user speaks, because `speech_counter` accumulated samples from a previous session or from ambient noise frames that slipped through the gate.

**Root cause:**  
`SileroVAD` is a long-lived object. Its `speech_counter`, `silence_counter`, `is_speaking`, and `speech_buffer` persist across manual speak activations. If the user pressed Speak, spoke, and the session ended, the counters are reset on `speech_end`. But if the user pressed Speak and then Stop (cancelled), `stop_manual_speak()` just sets `_manual_speak_active = False` — it does not reset the VAD state. On the next Speak press, the VAD may still have a partial `speech_counter` from the cancelled session.

**Fix:**  
Add a `reset()` method to `SileroVAD` and call it from `start_manual_speak()`:

```python
# In SileroVAD (vad.py), add:
def reset(self):
    """Reset VAD state between sessions."""
    self.is_speaking = False
    self.speech_buffer = bytearray()
    self.silence_counter = 0
    self.speech_counter = 0
    logger.debug("VAD state reset")
```

```python
# In PipelineWorker.start_manual_speak() (app.py), add after setting _manual_speak_active:
self._manual_speak_active = True
if hasattr(self, '_vad') and self._vad:
    self._vad.reset()
```

---

### STT-BUG-004 — Server `audio_input_worker` receives raw PCM16 bytes but `whisper_stt.transcribe()` has no minimum length guard; very short audio (< ~0.1s) causes Whisper to return empty text silently

**File:** `server/pipeline.py`, `server/stt/whisper_stt.py`  
**Symptom:** If the user speaks very briefly or the VAD fires `speech_end` prematurely (e.g. due to a cough or short noise), Whisper receives too few samples, returns an empty `text`, and the pipeline puts an empty `TranscriptionResult` into the transcript queue. `llm_worker` then picks it up, builds a prompt with empty user text, and sends it to the LLM — wasting a full LLM call and producing a confused response.

**Root cause:**  
`whisper_stt.transcribe()` has no guard on minimum audio length. Whisper's minimum meaningful input is ~0.5 seconds (8000 samples at 16kHz = 16000 bytes). Anything shorter produces empty or hallucinated output.

**Fix:**  
Add a minimum length check at the top of `audio_input_worker` before calling STT, and also inside `transcribe()` as a safety net:

```python
# In audio_input_worker (pipeline.py), after getting audio_bytes:
MIN_AUDIO_BYTES = 16000  # 0.5s at 16kHz PCM16 (16000 samples × 2 bytes)
if len(audio_bytes) < MIN_AUDIO_BYTES:
    logger.warning(f"Audio too short ({len(audio_bytes)} bytes), skipping STT")
    self.state.audio_input.task_done()
    continue
```

```python
# In WhisperSTT.transcribe() (whisper_stt.py), after converting to audio_float:
if len(audio_float) < 8000:  # < 0.5 seconds
    logger.warning(f"Audio too short for transcription: {len(audio_float)} samples")
    return TranscriptionResult(text="", language="en", confidence=0.0, duration_ms=0)
```

---

### STT-BUG-005 — `_capture_loop` in `app.py` deactivates `_manual_speak_active` and emits `manual_speak_done` *before* `send_audio` completes; if send fails, UI resets but audio is lost with no retry

**File:** `client/ui/app.py`  
**Method:** `_capture_loop()`  
**Symptom:** On a slow or briefly interrupted connection, `send_audio` raises an exception. The UI has already reset (Speak button re-enabled, status back to idle) because `manual_speak_done` was emitted before the send. The user sees the UI reset normally but their speech was never delivered to the server — no transcript, no response.

**Root cause:**  
```python
if self._manual_speak_active:
    self._manual_speak_active = False
    ...
    self.manual_speak_done.emit()   # <-- UI resets here

try:
    await self._ws.send_audio(event.audio_buffer)  # <-- send happens after
except Exception as e:
    logger.error(f"Failed to send audio: {e}")
    self.error_occurred.emit(...)
```

**Fix:**  
Move `manual_speak_done.emit()` to after a successful send:

```python
elif event.event_type == "speech_end" and event.audio_buffer:
    self.mic_active.emit(False)
    self.status_changed.emit("transcribing")
    logger.info(f"Sending {len(event.audio_buffer)} bytes of audio to server")

    # Deactivate manual speak mode
    if self._manual_speak_active:
        self._manual_speak_active = False
        if self._manual_speak_timer:
            self._manual_speak_timer.stop()
            self._manual_speak_timer = None

    try:
        await self._ws.send_audio(event.audio_buffer)
        # Only signal done after successful send
        self.manual_speak_done.emit()
    except Exception as e:
        logger.error(f"Failed to send audio: {e}")
        self.error_occurred.emit(f"Audio transmission failed: {e}")
        self.manual_speak_done.emit()  # still reset UI even on failure
```

---

## TTS / Audio Output Bugs

### TTS-BUG-001 — `_start_playback` opens a fixed-rate sounddevice stream; sample rate mismatch causes wrong-speed audio

**File:** `client/audio_playback.py`  
**Method:** `_start_playback()`  
**Symptom:** Audio plays at wrong pitch/speed. VOICEVOX outputs 24000 Hz WAV; `_decode_wav` correctly reads the rate and updates `self.sample_rate`, but `_start_playback` opens the stream using `self.sample_rate` at the moment it starts — which may be the old value if the rate update and `stop()` call race with the new `_start_playback` task.

**Root cause:**  
`queue_audio()` calls `stop()` when the sample rate changes, which clears the queue and drops the chunk that triggered the rate change. The new chunk is appended after `stop()` but the queue was just cleared.

**Fix:**  
Store `(pcm_data, sample_rate)` tuples in `audio_queue`. Open a new stream per rate change inside `_start_playback`, and remove the `stop()` call from `queue_audio()`:

```python
# In queue_audio(), replace:
self.audio_queue.append(pcm_data)
# With:
self.audio_queue.append((pcm_data, sample_rate))
# Remove the stop() call and sample_rate update block entirely

# In _start_playback(), replace the inner loop with:
current_rate = None
stream_ctx = None

while self.audio_queue:
    audio_data, chunk_rate = self.audio_queue.popleft()
    if chunk_rate != current_rate:
        if stream_ctx:
            stream_ctx.__exit__(None, None, None)
        current_rate = chunk_rate
        stream_ctx = sd.OutputStream(
            samplerate=current_rate, channels=self.channels, dtype=np.int16
        )
        stream_ctx.__enter__()
    audio_np = np.frombuffer(audio_data, dtype=np.int16)
    stream_ctx.write(audio_np)
    await asyncio.sleep(0.01)

if stream_ctx:
    stream_ctx.__exit__(None, None, None)
```

---

### TTS-BUG-002 — Headless `receive_loop` in `client/main.py` ignores binary audio frames; no audio output in `--no-ui` mode

**File:** `client/main.py`  
**Function:** `run_headless()` → `receive_loop()`  
**Symptom:** In `--no-ui` mode, server sends WAV audio as binary WebSocket frames. The receive loop only handles `dict` (JSON) messages — binary frames fall through silently. `AudioPlayback` is never instantiated.

**Fix:**  
```python
from client.audio_playback import AudioPlayback
playback = AudioPlayback()

async def receive_loop():
    async for msg in ws.receive():
        if isinstance(msg, bytes):
            playback.queue_audio(msg)
            continue
        if isinstance(msg, dict):
            ...  # existing handling unchanged
```

---

### TTS-BUG-003 — `asyncio.create_task()` in `queue_audio` has no error reference; playback exceptions are silently swallowed

**File:** `client/audio_playback.py`  
**Method:** `queue_audio()`  

**Fix:**  
```python
if not self.is_playing:
    task = asyncio.create_task(self._start_playback())
    task.add_done_callback(
        lambda t: logger.error(f"Playback task failed: {t.exception()}")
        if t.exception() else None
    )
```

---

### TTS-BUG-004 — `MIN_SENTENCE_LENGTH = 8` too long for short Japanese sentences; synthesis delayed or skipped

**File:** `server/pipeline.py`  
**Method:** `tts_worker()`  
**Symptom:** Short Japanese responses like `「はい。」` (4 chars) never hit the sentence boundary condition. They fall through to the 0.5s timeout path, adding latency per sentence.

**Fix:**  
Make the minimum length language-aware. Determine `current_lang` before the inner token loop (it's already set in `self.state.current_turn` by `audio_input_worker`):

```python
current_lang = "en"
if self.state.current_turn and "lang" in self.state.current_turn:
    current_lang = self.state.current_turn["lang"]

min_len = 2 if current_lang == "ja" else 8

# In the boundary check:
if (buffer and buffer[-1] in SENTENCE_ENDINGS and len(buffer) >= min_len):
    sentence_complete = True
```

---

### TTS-BUG-005 — VOICEVOX synthesis timeout 10s too short for longer sentences; `httpx.ReadTimeout` silently drops audio

**File:** `server/tts/voicevox_tts.py`  
**Method:** `synthesize_stream()`  

**Fix:**  
```python
# audio_query timeout: 5.0 → 10.0
timeout=10.0

# synthesis timeout: 10.0 → 30.0
timeout=30.0
```

---

## Summary Table

| ID | File | Symptom | Fix Complexity |
|----|------|---------|----------------|
| STT-BUG-001 | `client/ui/app.py` | Speak button never resets; `manual_speak_done` slot never fires | Low — delete duplicate signal + duplicate connect |
| STT-BUG-002 | `client/ui/app.py` | `speech_start` never fires; VAD model state goes stale when gated | Low — always feed frames to VAD, gate only the event handling |
| STT-BUG-003 | `client/vad.py`, `client/ui/app.py` | Stale VAD counters cause false triggers on new Speak press | Low — add `reset()` to VAD, call it in `start_manual_speak` |
| STT-BUG-004 | `server/pipeline.py`, `server/stt/whisper_stt.py` | Very short audio sends empty transcript to LLM | Low — add minimum byte length guard before STT call |
| STT-BUG-005 | `client/ui/app.py` | UI resets before send completes; failed sends lose audio silently | Low — move `manual_speak_done.emit()` to after send |
| TTS-BUG-001 | `client/audio_playback.py` | Wrong-speed audio; sample rate race drops chunks | Medium — store `(pcm, rate)` tuples, open stream per rate |
| TTS-BUG-002 | `client/main.py` | No audio in headless mode; binary frames ignored | Low — add `isinstance(msg, bytes)` branch + `AudioPlayback` |
| TTS-BUG-003 | `client/audio_playback.py` | Playback exceptions silently swallowed | Low — add `done_callback` to task |
| TTS-BUG-004 | `server/pipeline.py` | Short Japanese sentences skip TTS synthesis | Low — language-aware `min_len` |
| TTS-BUG-005 | `server/tts/voicevox_tts.py` | Long sentences time out, audio dropped | Low — increase timeouts to 10s/30s |
