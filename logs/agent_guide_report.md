# Agent Guide Report

> Role: Passive observer and guide. No code modifications. Each entry documents an issue, its cause, and a brief fix direction for the implementing agent.

---

## Issue Log

---

### Issue #1 — CosyVoice2 TTS Synthesis Failure

**Error:**
```
Synthesis failed: Failed to create AudioDecoder for [0. 0. 0. ... 0. 0. 0.]:
Unknown source type: <class 'numpy.ndarray'>.
Supported types are str, Path, bytes, Tensor and file-like objects.
```

**Location:** `cosyvoice_service/app.py` → `/synthesize` endpoint

**Root Cause:**
`inference_zero_shot()` expects `prompt_wav` to be a `torch.Tensor`, a file path (`str`/`Path`), raw `bytes`, or a file-like object. The code reads `prompt.wav` via `sf.read(..., dtype="float32")` which returns a plain `numpy.ndarray`. CosyVoice2's internal `AudioDecoder` does not accept `numpy.ndarray` directly, hence the crash.

**Fix Direction:**
After reading `prompt.wav` with `sf.read`, convert the resulting numpy array to a `torch.Tensor` before passing it to `inference_zero_shot`. Specifically:
- `import torch`
- wrap the array: `prompt_wav = torch.from_numpy(prompt_wav).unsqueeze(0)` (add batch/channel dim if the model expects it — check CosyVoice2 repo examples for expected shape, typically `[1, T]` or `[T]`)
- pass the tensor as `prompt_wav` argument

Also verify the sample rate: `sf.read` returns the file's native sample rate as `sr`. If CosyVoice2 expects a specific rate (commonly 16000 Hz for prompt audio), resample before converting to tensor using `torchaudio.functional.resample` or `librosa.resample`.

**Secondary Note:**
The `sample_rate = 22050` used in `audio_to_wav` is for the output. The prompt input sample rate should match what the model was trained on (likely 16000 Hz). These are two separate concerns and should not be conflated.

---

---

### Issue #2 — STT Voice Input Never Reaches the Server

**Symptom:**
User presses Speak, speaks, stops — nothing appears in server logs. No `audio_input_worker` activity, no transcription, no pipeline activity. Text input works fine. STT loads at startup but is never invoked during a voice turn.

**Root Cause — Three compounding problems:**

**A. `_manual_speak_active` flag is set from the Qt main thread, read from the asyncio worker thread — no synchronization.**

`start_manual_speak()` is called on the Qt main thread (button click → `_on_speak_pressed` → `self._worker.start_manual_speak()`). The flag `self._manual_speak_active = True` is written on the Qt thread. `_capture_loop()` runs inside `asyncio.gather()` on the worker thread's event loop and reads `self._manual_speak_active` on every frame. More critically, the `QTimer` created inside `start_manual_speak()` is created on the Qt main thread but `QTimer` requires a running Qt event loop on the thread it was created on to fire — the worker thread has no Qt event loop, only an asyncio loop. So the 15-second timeout never fires, and in some race conditions the flag write may not be seen by the capture loop in time.

**B. `_capture_loop` silently exits after 3 retries with no UI feedback.**

If audio capture fails at startup (ALSA/PulseAudio issue in WSL2 is common), `_capture_loop` retries 3 times then exits permanently. The Speak button stays enabled because `_on_connected` enables it unconditionally before audio capture is confirmed working. The user sees a working button but pressing it does nothing — the capture loop is dead and no frames are ever processed.

**C. The gate check has no INFO-level logging.**

`should_process = self.listening_enabled or self._manual_speak_active` is checked on every frame but never logged at INFO level. It is impossible to tell from `logs/new.txt` whether frames are flowing and being gated out, or whether the capture loop is not running at all. This makes the bug invisible in logs.

**Fix Direction:**

1. Replace the bare `self._manual_speak_active` bool with a `threading.Event`, or signal the asyncio loop using `loop.call_soon_threadsafe(lambda: setattr(self, '_manual_speak_active', True))`. This ensures the write is visible to the asyncio thread immediately.

2. Remove `QTimer` from `start_manual_speak()`. Implement the 15-second timeout entirely inside `_capture_loop` using `asyncio.wait_for` or a cancellable `asyncio.sleep` task — keep all timeout logic on the asyncio side where the event loop is actually running.

3. Add an INFO-level log when the gate opens (`_manual_speak_active` becomes True) and when audio bytes are dispatched to `send_audio`. This makes the voice path visible in logs.

4. When `_capture_loop` exhausts retries and exits, emit a dedicated signal (e.g. `audio_unavailable`) that explicitly disables the Speak button in the UI, so the user knows audio is dead rather than silently broken.

5. At startup, log the selected audio device at INFO level (not just DEBUG) so it is visible in `logs/new.txt` and confirms whether audio capture even opened successfully.
