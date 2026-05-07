# KokoClone Optimization Logging Bugfix Design

## Overview

The KokoClone TTS pipeline currently has no persistent, structured log file.
All timing and diagnostic output goes to stdout via `print()` or a
`logging.basicConfig` handler, making post-hoc analysis impossible.

The fix adds a single shared `FileHandler` that writes structured entries to
`kokoclone/kokoclone.log` across four components:

| Component | File |
|-----------|------|
| HTTP API server | `kokoclone/server.py` |
| Core synthesis (Kokoro TTS + Kanade VC) | `kokoclone/core/cloner.py` |
| Chunked voice conversion | `kokoclone/core/chunked_convert.py` |
| HTTP client (round-trip timing) | `server/tts/kokoclone_tts.py` |

The fix is purely additive: no audio processing logic, API contracts, or
return values are changed. Logging calls are wrapped in try/except so that a
logging failure can never break synthesis.

---

## Glossary

- **Bug_Condition (C)**: The condition that exposes the observability gap — a
  synthesis request is processed but no structured timing entry is written to
  `kokoclone.log`.
- **Property (P)**: The desired post-fix behavior — every synthesis request
  produces at least one structured log entry in `kokoclone.log` containing a
  `request_id`, phase name, and `elapsed_seconds > 0`.
- **Preservation**: All audio output (bytes, sample rate, waveform content)
  and all API contracts must remain byte-for-byte identical after the fix.
- **`KokoClone.generate()`**: The method in `kokoclone/core/cloner.py` that
  orchestrates the Kokoro TTS phase followed by the Kanade VC phase.
- **`chunked_voice_conversion()`**: The function in
  `kokoclone/core/chunked_convert.py` that splits long waveforms into
  VRAM-safe chunks and reassembles them.
- **`KokoCloneTTS.synthesize_stream()`**: The async method in
  `server/tts/kokoclone_tts.py` that sends an HTTP request to the microservice
  and yields the WAV response.
- **`request_id`**: A short unique identifier (8-char hex from `uuid4`) that
  is generated in `server.py` per request and threaded through the call chain
  via a keyword argument.
- **`kokoclone_logger`**: The `logging.Logger` instance named
  `"kokoclone"` that is configured with the `FileHandler` pointing to
  `kokoclone/kokoclone.log`.

---

## Bug Details

### Bug Condition

The bug manifests whenever a synthesis request is processed by any of the four
components and no structured entry with timing data is written to
`kokoclone.log`. This covers the normal path (no log file exists at all) and
the partial path (a log file exists but is missing timing fields for the
current request).

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT: X of type SynthesisRequest
         (fields: text, lang, reference_audio, request_id)
  OUTPUT: boolean

  RETURN NOT file_exists("kokoclone/kokoclone.log")
      OR NOT log_contains_entry WHERE
               entry.request_id = X.request_id
           AND entry.phase IN {"kokoro_tts", "kanade_vc", "total"}
           AND entry.elapsed_seconds > 0
END FUNCTION
```

### Examples

- **Normal synthesis (Japanese)**: User sends `POST /synthesize` with
  `text="こんにちは"`, `lang="ja"`. Currently: one unstructured stdout line,
  no log file. After fix: `kokoclone.log` contains entries for
  `kokoro_tts`, `kanade_vc`, and `total` phases with elapsed times.

- **Chunked conversion (long audio)**: Source waveform > 8.9 s triggers
  multi-chunk path. Currently: `print()` lines to stdout only. After fix:
  per-chunk INFO entries in `kokoclone.log` with `chunk_index`,
  `chunk_duration_s`, and `elapsed_s`.

- **HTTP client round-trip**: `KokoCloneTTS.synthesize_stream()` receives a
  200 response. Currently: logs `received N bytes` with no timing. After fix:
  logs `round_trip_ms=NNN response_bytes=NNN` to the main server logger.

- **Exception during synthesis**: `kanade.voice_conversion()` raises
  `RuntimeError`. Currently: logged to stderr only. After fix: structured
  ERROR entry in `kokoclone.log` with `phase`, `exc_type`, and `message`.

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `KokoClone.generate()` must continue to write a valid WAV file to
  `output_path` with the same sample rate and audio content.
- `GET /health` must continue to return `{"status": "ok", "sample_rate": <int>}`
  with HTTP 200.
- `chunked_voice_conversion()` must continue to return a waveform tensor that
  is numerically identical to the pre-fix result for both single-chunk and
  multi-chunk inputs.
- `KokoCloneTTS.synthesize_stream()` must continue to yield zero chunks (not
  raise) on connection errors, timeouts, and HTTP errors.
- `TTSRouter` must continue to fall back to `KokoroJapaneseTTS` when
  `KokoCloneTTS` produces no audio.
- The Kokoro model cache (`KokoClone.kokoro_cache`) must continue to be reused
  across calls with the same model file.

**Scope:**
All inputs that do NOT involve the logging path are completely unaffected.
The logging calls are side-effects only — they do not alter any return value,
tensor, or byte stream. Specifically:
- Audio processing tensors and numpy arrays are not touched.
- HTTP response bytes are not modified.
- No new dependencies are introduced (only Python stdlib `logging`, `uuid`,
  `time.perf_counter` — all already available).

---

## Hypothesized Root Cause

The observability gap has four concrete causes, each in a different file:

1. **No `FileHandler` configured** (`kokoclone/server.py`): The module calls
   `logging.basicConfig(level=INFO)` which attaches only a `StreamHandler`
   (stdout). No `FileHandler` for `kokoclone.log` is ever created.

2. **`print()` instead of `logger` calls** (`kokoclone/core/cloner.py`,
   `kokoclone/core/chunked_convert.py`): Timing output uses bare `print()`
   statements that bypass the logging system entirely and are lost when the
   process exits.

3. **No elapsed-time measurement** (`kokoclone/core/cloner.py`): The Kokoro
   TTS and Kanade VC phases have no `time.perf_counter()` bookends, so even
   if a logger were present there would be no timing data to record.

4. **No round-trip timing** (`server/tts/kokoclone_tts.py`): The HTTP client
   records the request start and response size but does not compute
   `round_trip_ms = (t_after - t_before) * 1000`.

---

## Correctness Properties

Property 1: Bug Condition — Synthesis Produces Structured Log Entries

_For any_ synthesis request X where `isBugCondition(X)` holds (i.e., no
structured timing entry exists in `kokoclone.log` for X), the fixed pipeline
SHALL write at least one structured INFO entry to `kokoclone.log` containing
`request_id=X.request_id`, a phase name in `{"kokoro_tts", "kanade_vc",
"total"}`, and `elapsed_seconds > 0`.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.7**

Property 2: Preservation — Audio Output Is Unchanged

_For any_ synthesis request X where `isBugCondition(X)` does NOT hold (i.e.,
the logging infrastructure is already in place), the fixed pipeline SHALL
produce WAV audio bytes and a sample rate that are identical to those produced
by the original (pre-fix) pipeline, preserving audio quality, sample rate, and
waveform content.

**Validates: Requirements 3.1, 3.2, 3.4, 3.5**

---

## Fix Implementation

### Logger Setup (`kokoclone/core/logging_setup.py` — new file)

Create a single shared setup function so all kokoclone components use the same
`FileHandler` and formatter. This avoids duplicate handlers when modules are
imported multiple times.

```python
# kokoclone/core/logging_setup.py
import logging
import os

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "kokoclone.log")
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def get_kokoclone_logger(name: str) -> logging.Logger:
    """
    Return a logger named 'kokoclone.<name>' backed by kokoclone.log.
    Idempotent — calling twice with the same name returns the same logger
    without adding duplicate handlers.
    """
    logger = logging.getLogger(f"kokoclone.{name}")
    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(_FORMATTER)
        logger.addHandler(fh)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # don't double-log to root/basicConfig
    return logger
```

Log rotation is intentionally omitted from the initial fix to keep the change
minimal. If `kokoclone.log` grows large in production, a
`RotatingFileHandler(maxBytes=10*1024*1024, backupCount=3)` can be swapped in
without changing any call sites.

### Changes Required

#### File: `kokoclone/server.py`

**Function**: module-level setup + `synthesize()`

**Specific Changes**:
1. **Import `uuid` and `logging_setup`**: Add
   `import uuid` and `from core.logging_setup import get_kokoclone_logger`.
2. **Replace `logging.basicConfig`**: Remove the `basicConfig` call; obtain
   `logger = get_kokoclone_logger("server")` instead.
3. **Generate `request_id`**: At the top of `synthesize()`, generate
   `request_id = uuid.uuid4().hex[:8]`.
4. **Structured request entry**: Replace the existing `logger.info(f"Synthesising ...")` 
   with a structured entry:
   ```python
   logger.info(
       f"request_received text={req.text[:80]!r} lang={req.lang!r} "
       f"request_id={request_id} text_len={len(req.text)}"
   )
   ```
5. **Thread `request_id` into `cloner.generate()`**: Pass it as a keyword
   argument: `cloner.generate(..., request_id=request_id)`.
6. **Structured completion entry**: After reading `wav_bytes`, log:
   ```python
   logger.info(
       f"request_complete request_id={request_id} "
       f"response_bytes={len(wav_bytes)}"
   )
   ```
7. **Structured error entry**: In the `except` block, log:
   ```python
   logger.error(
       f"request_failed request_id={request_id} "
       f"exc_type={type(exc).__name__} message={exc}",
       exc_info=True,
   )
   ```

#### File: `kokoclone/core/cloner.py`

**Function**: `KokoClone.generate()`

**Specific Changes**:
1. **Import `logging_setup`**: Add
   `from core.logging_setup import get_kokoclone_logger` and obtain
   `_logger = get_kokoclone_logger("cloner")` at module level.
2. **Accept `request_id` kwarg**: Change signature to
   `def generate(self, text, lang, reference_audio, output_path="output.wav", request_id="")`.
3. **Kokoro TTS phase timing**: Wrap the `kokoro.create()` call:
   ```python
   _t0 = time.perf_counter()
   # ... existing kokoro.create() call ...
   _kokoro_elapsed = time.perf_counter() - _t0
   _audio_duration = len(samples) / sr
   _logger.info(
       f"phase=kokoro_tts request_id={request_id} "
       f"elapsed_seconds={_kokoro_elapsed:.3f} "
       f"audio_duration_seconds={_audio_duration:.3f} "
       f"lang={lang}"
   )
   ```
4. **Kanade VC phase timing**: Wrap the `chunked_voice_conversion()` call:
   ```python
   _t1 = time.perf_counter()
   converted_wav = chunked_voice_conversion(...)
   _vc_elapsed = time.perf_counter() - _t1
   _vc_duration = converted_wav.shape[-1] / self.sample_rate
   _logger.info(
       f"phase=kanade_vc request_id={request_id} "
       f"elapsed_seconds={_vc_elapsed:.3f} "
       f"audio_duration_seconds={_vc_duration:.3f}"
   )
   ```
5. **Total elapsed entry**: After `sf.write(output_path, ...)`:
   ```python
   _total_elapsed = _kokoro_elapsed + _vc_elapsed
   _logger.info(
       f"phase=total request_id={request_id} "
       f"total_elapsed_seconds={_total_elapsed:.3f}"
   )
   ```
6. **Exception logging**: In the `except` block of the `try/finally`:
   ```python
   _logger.error(
       f"phase=kanade_vc request_id={request_id} "
       f"exc_type={type(exc).__name__} message={exc}",
       exc_info=True,
   )
   raise  # re-raise so server.py can return HTTP 500
   ```
7. **Replace `print()` calls**: Replace all `print(f"Synthesizing ...")` and
   `print(f"Applying Voice Clone...")` with `_logger.info(...)` equivalents.
   Keep the `print(f"Success! ...")` as a `_logger.info(...)` call too.

#### File: `kokoclone/core/chunked_convert.py`

**Function**: `chunked_voice_conversion()`

**Specific Changes**:
1. **Import `logging_setup`**: Add
   `from core.logging_setup import get_kokoclone_logger` and obtain
   `_logger = get_kokoclone_logger("chunked_convert")` at module level.
2. **Accept `request_id` kwarg**: Change signature to
   `def chunked_voice_conversion(..., request_id="")`.
3. **Replace VRAM budget `print()`**: Replace with:
   ```python
   _logger.info(
       f"chunk_config request_id={request_id} "
       f"vram_budget_gb={budget_gb:.2f} "
       f"vram_fraction={vram_fraction:.0%} "
       f"total_vram_gb={total_vram_bytes / (1024**3):.2f} "
       f"chunk_seconds={chunk_seconds:.1f} "
       f"chunk_samples={chunk_samples} "
       f"rope_ceiling_seconds={rope_safe_seconds:.1f}"
   )
   ```
4. **Per-chunk timing**: Inside the `while pos < n_samples` loop, add a
   `_chunk_t0 = time.perf_counter()` before the `kanade.voice_conversion()`
   call and log after:
   ```python
   _chunk_elapsed = time.perf_counter() - _chunk_t0
   _chunk_duration = (win_end - win_start) / sample_rate
   _logger.info(
       f"chunk request_id={request_id} "
       f"chunk_index={chunk_index} "
       f"chunk_duration_s={_chunk_duration:.2f} "
       f"elapsed_s={_chunk_elapsed:.3f}"
   )
   ```
   (Maintain a `chunk_index` counter starting at 0.)
5. **Replace completion `print()`** (both single-chunk and multi-chunk paths):
   ```python
   _logger.info(
       f"chunked_convert_complete request_id={request_id} "
       f"elapsed_seconds={elapsed:.3f} "
       f"n_chunks={chunk_index + 1}"
   )
   ```
6. **Thread `request_id`**: Update the call site in `cloner.py` to pass
   `request_id=request_id`.

#### File: `server/tts/kokoclone_tts.py`

**Function**: `KokoCloneTTS.synthesize_stream()`

**Specific Changes**:
1. **Import `time`**: Add `import time` at the top.
2. **Capture start time**: Before the `httpx.AsyncClient()` context manager:
   ```python
   _t_start = time.perf_counter()
   ```
3. **Compute and log round-trip**: After `wav_bytes = resp.content`:
   ```python
   _round_trip_ms = (time.perf_counter() - _t_start) * 1000
   logger.info(
       f"[KokoCloneTTS] synthesis_complete "
       f"round_trip_ms={_round_trip_ms:.1f} "
       f"response_bytes={len(wav_bytes)}"
   )
   ```
   This uses the existing module-level `logger` (main server logger), which is
   correct — `kokoclone_tts.py` lives in the main server process, not the
   microservice.

### Request ID Threading

```
POST /synthesize (server.py)
  │  request_id = uuid4().hex[:8]          ← generated here
  │  logger.info("request_received ... request_id=...")
  │
  └─► KokoClone.generate(..., request_id=request_id)   (cloner.py)
        │  logger.info("phase=kokoro_tts ... request_id=...")
        │
        └─► chunked_voice_conversion(..., request_id=request_id)  (chunked_convert.py)
              │  logger.info("chunk ... request_id=...")
              └─► logger.info("chunked_convert_complete ... request_id=...")
        │
        └─► logger.info("phase=kanade_vc ... request_id=...")
        └─► logger.info("phase=total ... request_id=...")
```

`KokoCloneTTS.synthesize_stream()` (main server process) does not receive the
`request_id` from the microservice — it logs independently to the main server
logger with its own timing.

### Timing Measurement

All elapsed times use `time.perf_counter()` (monotonic, sub-microsecond
resolution). The pattern is:

```python
_t0 = time.perf_counter()
# ... work ...
elapsed = time.perf_counter() - _t0
```

`time.perf_counter()` is already imported in `chunked_convert.py`; it needs to
be added to `cloner.py`.

### Log Format

Each entry produced by `_FORMATTER` will look like:

```
2025-07-14 09:23:11.042 [INFO] [kokoclone.server] request_received text='こんにちは' lang='ja' request_id=a3f7c901 text_len=5
2025-07-14 09:23:11.891 [INFO] [kokoclone.cloner] phase=kokoro_tts request_id=a3f7c901 elapsed_seconds=0.847 audio_duration_seconds=1.230 lang=ja
2025-07-14 09:23:14.203 [INFO] [kokoclone.chunked_convert] chunk request_id=a3f7c901 chunk_index=0 chunk_duration_s=1.23 elapsed_s=2.311
2025-07-14 09:23:14.204 [INFO] [kokoclone.chunked_convert] chunked_convert_complete request_id=a3f7c901 elapsed_seconds=2.312 n_chunks=1
2025-07-14 09:23:14.205 [INFO] [kokoclone.cloner] phase=kanade_vc request_id=a3f7c901 elapsed_seconds=2.314 audio_duration_seconds=1.230
2025-07-14 09:23:14.206 [INFO] [kokoclone.cloner] phase=total request_id=a3f7c901 total_elapsed_seconds=3.161
2025-07-14 09:23:14.207 [INFO] [kokoclone.server] request_complete request_id=a3f7c901 response_bytes=59244
```

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface
counterexamples that demonstrate the bug on unfixed code (no log file, no
timing entries), then verify the fix works correctly and preserves existing
behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing
the fix. Confirm that `kokoclone.log` does not exist or contains no timing
entries after synthesis on the unfixed code.

**Test Plan**: Write tests that call `KokoClone.generate()` (or a lightweight
mock of it) and then inspect the filesystem for `kokoclone.log` and its
contents. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **Log file absent**: After calling `generate()` on unfixed code, assert
   `kokoclone.log` does NOT exist — this will pass on unfixed code, confirming
   the bug. (will fail on fixed code, confirming the fix)
2. **No timing entry**: After calling `generate()` on unfixed code, assert
   that no line in stdout/log contains `elapsed_seconds` — confirms the
   observability gap.
3. **No request_id**: Assert that no structured `request_id=` field appears in
   any output on unfixed code.
4. **HTTP client no round-trip**: Mock `httpx` to return a 200 response and
   assert no `round_trip_ms` field is logged by `KokoCloneTTS`.

**Expected Counterexamples**:
- `kokoclone.log` does not exist after synthesis
- No `elapsed_seconds` field in any log output
- Possible causes: no `FileHandler`, `print()` used instead of `logger`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed
pipeline produces structured log entries.

**Pseudocode:**
```
FOR ALL X WHERE isBugCondition(X) DO
  result := synthesize_fixed(X)
  ASSERT file_exists("kokoclone/kokoclone.log")
  ASSERT log_contains_entry WHERE
    entry.request_id = X.request_id
    AND entry.phase IN {"kokoro_tts", "kanade_vc", "total"}
    AND entry.elapsed_seconds > 0
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold
(i.e., logging is in place), the fixed pipeline produces audio output
identical to the original.

**Pseudocode:**
```
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT synthesize_original(X).audio_bytes = synthesize_fixed(X).audio_bytes
  ASSERT synthesize_original(X).sample_rate = synthesize_fixed(X).sample_rate
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation
checking because:
- It generates many waveform lengths and text inputs automatically
- It catches edge cases (single-sample waveforms, maximum-length chunks) that
  manual tests miss
- It provides strong guarantees that the logging side-effect does not alter
  any tensor or byte value

**Test Plan**: Capture the output of `chunked_voice_conversion()` on unfixed
code for a range of waveform lengths, then assert the fixed version produces
the same output.

**Test Cases**:
1. **Single-chunk preservation**: Generate random waveforms shorter than
   `chunk_samples` and assert the returned tensor is numerically identical
   before and after the fix.
2. **Multi-chunk preservation**: Generate random waveforms longer than
   `chunk_samples` and assert the assembled tensor is numerically identical.
3. **Audio bytes preservation**: Call `KokoClone.generate()` end-to-end and
   assert the WAV file written to `output_path` is byte-for-byte identical.
4. **HTTP client preservation**: Assert `synthesize_stream()` still yields
   the same WAV bytes after adding the timing log call.

### Unit Tests

- Test `get_kokoclone_logger()` is idempotent (calling twice returns the same
  logger with exactly one `FileHandler`).
- Test that `kokoclone.log` is created in the correct directory on first log
  call.
- Test that each log entry matches the format
  `YYYY-MM-DD HH:MM:SS.mmm [LEVEL] [component] message {key=value ...}`.
- Test that a logging exception inside `generate()` does not propagate (the
  try/except wrapper absorbs it).
- Test `GET /health` still returns `{"status": "ok", "sample_rate": <int>}`
  after the logging changes.

### Property-Based Tests

- **Property 1 (Fix Checking)**: For any `(text, lang)` pair that produces
  valid synthesis, `kokoclone.log` contains an entry with
  `elapsed_seconds > 0` and the correct `request_id`.
- **Property 2 (Preservation — waveform)**: For any waveform tensor of
  arbitrary length, `chunked_voice_conversion()` returns a tensor that is
  numerically identical before and after the logging changes.
- **Property 3 (Preservation — HTTP bytes)**: For any mocked WAV response
  body, `KokoCloneTTS.synthesize_stream()` yields the same bytes before and
  after adding the `round_trip_ms` log call.

### Integration Tests

- Test full synthesis flow (`POST /synthesize` → `generate()` →
  `chunked_voice_conversion()`) and assert `kokoclone.log` contains entries
  for all three phases (`kokoro_tts`, `kanade_vc`, `total`) with the same
  `request_id`.
- Test that switching between single-chunk and multi-chunk inputs produces the
  correct number of `chunk` log entries.
- Test that an exception during `kanade.voice_conversion()` produces a
  structured ERROR entry in `kokoclone.log` and still returns HTTP 500 to the
  caller.
- Test that `TTSRouter` falls back to `KokoroJapaneseTTS` when `KokoCloneTTS`
  produces no audio, and that the fallback path is unaffected by the logging
  changes.
