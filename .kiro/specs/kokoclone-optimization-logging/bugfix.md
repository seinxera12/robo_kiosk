# Bugfix Requirements Document

## Introduction

The KokoClone TTS pipeline (Japanese voice cloning) currently has no structured,
file-based logging. `kokoclone/server.py` and `kokoclone/core/cloner.py` emit
plain `print()` calls and basic `logging.basicConfig` output to stdout only.
`server/tts/kokoclone_tts.py` logs to the main server logger with no timing
data. `kokoclone/core/chunked_convert.py` uses `print()` for timing but writes
to stdout rather than a log file.

Because there is no persistent, structured log, it is impossible to:
- Observe the timing of each synthesis phase (Kokoro TTS, Kanade voice
  conversion, HTTP transport) after the fact
- Confirm that inference is completing correctly or identify where it stalls
- Track errors, warnings, or resource usage (VRAM, chunk sizes) across requests
- Diagnose performance regressions or silent failures in the pipeline

The fix is to implement structured, file-based logging to `kokoclone.log` across
all four components, then use the resulting log data to identify and address any
performance issues or bugs.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a synthesis request is received by `kokoclone/server.py` THEN the
    system logs only a single unstructured INFO line to stdout with no request
    ID, no text length, and no timing breakdown.

1.2 WHEN `KokoClone.generate()` executes the Kokoro TTS phase in
    `kokoclone/core/cloner.py` THEN the system emits a bare `print()` to stdout
    with no elapsed time measurement for that phase.

1.3 WHEN `KokoClone.generate()` executes the Kanade voice conversion phase in
    `kokoclone/core/cloner.py` THEN the system emits a bare `print()` to stdout
    with no elapsed time measurement for that phase.

1.4 WHEN `chunked_voice_conversion()` runs in
    `kokoclone/core/chunked_convert.py` THEN the system writes chunk-level
    timing via `print()` to stdout, which is not captured in any log file and
    is lost after the process exits.

1.5 WHEN `KokoCloneTTS.synthesize_stream()` in `server/tts/kokoclone_tts.py`
    sends an HTTP request to the microservice THEN the system logs the request
    start and response size but records no HTTP round-trip duration.

1.6 WHEN any synthesis phase raises an exception THEN the system logs the error
    to stdout/stderr only, with no structured entry in a persistent log file
    that can be reviewed after the fact.

1.7 WHEN the KokoClone microservice is running THEN no log file (`kokoclone.log`)
    is created, making post-hoc analysis of inference timing and correctness
    impossible.

### Expected Behavior (Correct)

2.1 WHEN a synthesis request is received by `kokoclone/server.py` THEN the
    system SHALL write a structured INFO entry to `kokoclone.log` containing
    the request timestamp, a short text preview (≤ 80 chars), language, and
    a unique request identifier.

2.2 WHEN `KokoClone.generate()` completes the Kokoro TTS phase THEN the system
    SHALL write a structured INFO entry to `kokoclone.log` containing the phase
    name ("kokoro_tts"), elapsed time in seconds, and output audio duration in
    seconds.

2.3 WHEN `KokoClone.generate()` completes the Kanade voice conversion phase
    THEN the system SHALL write a structured INFO entry to `kokoclone.log`
    containing the phase name ("kanade_vc"), elapsed time in seconds, and
    output audio duration in seconds.

2.4 WHEN `chunked_voice_conversion()` runs THEN the system SHALL write
    structured INFO entries to `kokoclone.log` for chunk-level timing (chunk
    index, chunk duration, elapsed time) and a final summary entry with total
    elapsed time, number of chunks, and VRAM budget (on CUDA).

2.5 WHEN `KokoCloneTTS.synthesize_stream()` receives a response from the
    microservice THEN the system SHALL write a structured INFO entry to the
    main server log containing the HTTP round-trip duration in milliseconds and
    the response size in bytes.

2.6 WHEN any synthesis phase raises an exception THEN the system SHALL write a
    structured ERROR entry to `kokoclone.log` with the phase name, exception
    type, message, and stack trace.

2.7 WHEN the KokoClone microservice starts THEN the system SHALL create (or
    append to) `kokoclone.log` in the kokoclone service directory, with each
    entry formatted as:
    `YYYY-MM-DD HH:MM:SS.mmm [LEVEL] [component] message {key=value ...}`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a valid synthesis request is processed end-to-end THEN the system
    SHALL CONTINUE TO return correct WAV audio bytes to the caller with no
    change in audio quality or sample rate.

3.2 WHEN `KokoClone.generate()` is called with a valid text, language, and
    reference audio path THEN the system SHALL CONTINUE TO write the output
    WAV file to the specified `output_path`.

3.3 WHEN the KokoClone microservice is healthy THEN `GET /health` SHALL
    CONTINUE TO return `{"status": "ok", "sample_rate": <int>}` with HTTP 200.

3.4 WHEN `chunked_voice_conversion()` processes audio that fits in a single
    chunk THEN the system SHALL CONTINUE TO return the converted waveform
    without splitting.

3.5 WHEN `chunked_voice_conversion()` processes audio that requires multiple
    chunks THEN the system SHALL CONTINUE TO apply overlap-based boundary
    smoothing and return a correctly assembled waveform.

3.6 WHEN `KokoCloneTTS.synthesize_stream()` encounters a connection error,
    timeout, or HTTP error THEN the system SHALL CONTINUE TO catch the
    exception, log it, and yield zero chunks so TTSRouter falls back to the
    next Japanese engine.

3.7 WHEN the KokoClone microservice is unavailable THEN `TTSRouter` SHALL
    CONTINUE TO fall back to `KokoroJapaneseTTS` (or subsequent engines) and
    produce audio without raising an unhandled exception.

3.8 WHEN the Kokoro model file is already cached in `KokoClone.kokoro_cache`
    THEN the system SHALL CONTINUE TO reuse the cached instance without
    reloading from disk.

---

## Bug Condition

**Bug Condition Function** — identifies requests that expose the observability gap:

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type SynthesisRequest
  OUTPUT: boolean

  // The bug condition is met whenever a synthesis request is processed
  // and no structured log entry with timing data is written to kokoclone.log.
  RETURN NOT exists(log_file("kokoclone.log"))
      OR log_file("kokoclone.log") does NOT contain timing entry for X
END FUNCTION
```

**Property: Fix Checking**

```pascal
// For every synthesis request, kokoclone.log must contain structured timing entries.
FOR ALL X WHERE isBugCondition(X) DO
  result ← synthesize'(X)
  ASSERT log_file("kokoclone.log") contains entry WHERE
    entry.request_id = X.id
    AND entry.phase IN {"kokoro_tts", "kanade_vc", "total"}
    AND entry.elapsed_seconds > 0
END FOR
```

**Property: Preservation Checking**

```pascal
// For all requests, the audio output must be identical before and after the fix.
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT synthesize(X).audio_bytes = synthesize'(X).audio_bytes
    AND synthesize(X).sample_rate  = synthesize'(X).sample_rate
END FOR
```
