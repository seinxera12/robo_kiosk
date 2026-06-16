# Design Document: qwen3-tts-fallback

## Overview

This feature adds `Qwen3TTSEngine` as the final fallback TTS engine in both the
English and Japanese synthesis chains. The engine wraps the vLLM-Omni WebSocket
streaming endpoint (`/v1/audio/speech/stream`) and converts raw PCM16 output to
WAV format before yielding chunks — matching the interface contract already
established by `KokoroTTS` and `KokoCloneTTS`.

**Fallback chains after this feature:**

| Language | Priority 1 | Priority 2 | Priority 3 (new) |
|----------|-----------|-----------|-----------------|
| English  | KokoroTTS | —         | Qwen3TTSEngine  |
| Japanese | KokoCloneTTS | KokoroJapaneseTTS | Qwen3TTSEngine |

The feature is opt-in: `QWEN3_TTS_ENABLED=false` by default. When disabled, all
existing code paths are completely unchanged.

### Files Changed

| File | Change type | Summary |
|------|-------------|---------|
| `server/tts/qwen3_tts.py` | **New** | `Qwen3TTSEngine` class |
| `server/config.py` | Modified | 4 new fields + `from_env` entries |
| `server/tts/tts_router.py` | Modified | Init, `synthesize_stream` (both langs), `health_check_all` |
| `server/main.py` | Modified | `/health` endpoint — `qwen3_tts` key |

---

## Architecture

The new engine slots into the existing pipeline without touching any other stage.
The `tts_worker` in `pipeline.py` calls `tts_router.synthesize_stream(text, lang)`
and consumes the yielded WAV chunks — no changes needed there.

```
tts_worker (pipeline.py)
  └─ TTSRouter.synthesize_stream(text, lang)
       ├─ lang="en"
       │    ├─ KokoroTTS.synthesize_stream(text)   [primary]
       │    └─ Qwen3TTSEngine.synthesize_stream(text)  [fallback, new]
       └─ lang="ja"
            ├─ KokoCloneTTS.synthesize_stream(text)    [primary]
            ├─ KokoroJapaneseTTS.synthesize_stream(text) [secondary]
            └─ Qwen3TTSEngine.synthesize_stream(text)  [tertiary, new]
```

`Qwen3TTSEngine` is a pure async transformer: it accepts `text: str` and yields
`bytes` (WAV chunks). It holds no reference to any queue, WebSocket, or other
pipeline stage object.

---

## Components and Interfaces

### `server/tts/qwen3_tts.py` — New File

```python
class Qwen3TTSEngine:
    """
    Async TTS engine backed by a vLLM-Omni WebSocket streaming endpoint.

    Implements the same synthesize_stream / health_check interface as
    KokoroTTS and KokoCloneTTS so TTSRouter can treat it identically.

    Audio output: WAV bytes at 24 kHz, mono, PCM16 — same as all other engines.

    The vLLM-Omni server must be started with:
        vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --port 8001 --async-chunk

    Configuration is read exclusively from the Config object:
        config.qwen3_tts_enabled  — bool, must be True for any operation
        config.qwen3_tts_ws_url   — WebSocket URL of the vLLM-Omni endpoint
        config.qwen3_tts_voice    — voice preset name (e.g. "Ono_Anna")
        config.qwen3_tts_language — BCP-47 language tag (e.g. "ja")
    """

    def __init__(self, config) -> None:
        """
        Store configuration. No I/O is performed at construction time.

        Args:
            config: Server Config object with qwen3_tts_* fields.
        """

    async def health_check(self) -> bool:
        """
        Return True if the vLLM-Omni WebSocket endpoint is reachable.

        Opens a WebSocket connection with a 3-second timeout, closes it
        immediately, and returns True.  Returns False on any exception or
        when qwen3_tts_enabled is False.

        Returns:
            bool: True = endpoint reachable, False = disabled or unreachable.
        """

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Synthesise text via the vLLM-Omni WebSocket endpoint.

        Follows the vLLM-Omni session protocol:
          1. Open WebSocket connection
          2. Send session.config (voice, language, stream_audio, response_format)
          3. Send input.text
          4. Send input.end
          5. Receive binary frames (PCM16) → wrap in WAV header → yield
          6. Receive JSON frames → handle audio.done, log others
          7. Stop on ConnectionClosed (normal completion)

        Guards:
          - If qwen3_tts_enabled is False: yield nothing, return immediately.
          - If text.strip() is empty: log warning, yield nothing, return.
          - On connection error: log error, yield nothing (no exception raised).
          - On asyncio.CancelledError: propagate immediately (do NOT suppress).

        Args:
            text: Text to synthesise (one sentence, as provided by tts_worker).

        Yields:
            bytes: Complete WAV file (header + PCM16 data) for each PCM chunk
                   received from the server. Empty PCM frames are discarded.
        """
```

### `_pcm_to_wav` — Module-level helper

```python
def _pcm_to_wav(pcm_bytes: bytes) -> bytes | None:
    """
    Wrap raw int16 PCM bytes in a WAV file header.

    Args:
        pcm_bytes: Raw 16-bit signed PCM audio at 24 kHz, mono.
                   This is the direct output of the vLLM-Omni server —
                   NOT float32 like Kokoro's output.

    Returns:
        Complete WAV file bytes, or None if pcm_bytes is empty.

    Audio parameters (fixed):
        channels:   1  (mono)
        sampwidth:  2  (16-bit = 2 bytes per sample)
        framerate:  24000 Hz
    """
```

---

## Data Models

### Config Fields (additions to `server/config.py`)

```python
@dataclass
class Config:
    # ... existing fields ...

    # Qwen3 TTS fallback engine
    qwen3_tts_enabled: bool = False
    qwen3_tts_ws_url: str = "ws://localhost:8001/v1/audio/speech/stream"
    qwen3_tts_voice: str = "Ono_Anna"
    qwen3_tts_language: str = "ja"
```

`from_env` additions:

```python
qwen3_tts_enabled=os.getenv("QWEN3_TTS_ENABLED", "false").lower() in ("true", "1", "yes"),
qwen3_tts_ws_url=os.getenv("QWEN3_TTS_WS_URL", "ws://localhost:8001/v1/audio/speech/stream"),
qwen3_tts_voice=os.getenv("QWEN3_TTS_VOICE", "Ono_Anna"),
qwen3_tts_language=os.getenv("QWEN3_TTS_LANGUAGE", "ja"),
```

### vLLM-Omni Session Messages

All messages are JSON-encoded strings sent over the WebSocket.

**`session.config`** (sent first, once per connection):
```json
{
  "type": "session.config",
  "voice": "<config.qwen3_tts_voice>",
  "task_type": "CustomVoice",
  "language": "<config.qwen3_tts_language>",
  "split_granularity": "sentence",
  "stream_audio": true,
  "response_format": "pcm"
}
```

**`input.text`** (sent after session.config):
```json
{
  "type": "input.text",
  "text": "<text argument>"
}
```

**`input.end`** (sent after input.text):
```json
{
  "type": "input.end"
}
```

**Server response — binary frame**: raw int16 PCM bytes at 24 kHz, mono.

**Server response — `audio.done`** (JSON):
```json
{
  "type": "audio.done"
}
```
Treated as a sentence-boundary marker; no action required.

---

## WebSocket Session Protocol Flow

```
Client (Qwen3TTSEngine)          vLLM-Omni Server
        |                               |
        |--- WS connect --------------->|
        |                               |
        |--- session.config (JSON) ---->|  voice, language, stream_audio=true, response_format=pcm
        |                               |
        |--- input.text (JSON) -------->|  {"type":"input.text","text":"..."}
        |                               |
        |--- input.end (JSON) --------->|  {"type":"input.end"}
        |                               |
        |<-- binary frame (PCM16) ------|  raw int16 bytes, 24kHz mono
        |    → _pcm_to_wav() → yield   |
        |                               |
        |<-- binary frame (PCM16) ------|  (more chunks as synthesis progresses)
        |    → _pcm_to_wav() → yield   |
        |                               |
        |<-- {"type":"audio.done"} -----|  sentence boundary marker, log debug
        |                               |
        |<-- binary frame (PCM16) ------|  (next sentence, if any)
        |    → _pcm_to_wav() → yield   |
        |                               |
        |<-- WS close ------------------|  normal completion after all audio sent
        |    → stop iteration          |
        |                               |
```

**Concurrency model**: The vLLM-Omni protocol requires concurrent send and
receive. `asyncio.gather(sender(), receiver())` is used inside an internal
`_run()` coroutine. An `asyncio.Queue` bridges the gather and the outer
`async for` loop so the method can remain an async generator:

```
synthesize_stream()
  ├─ chunk_queue = asyncio.Queue()
  ├─ task = asyncio.ensure_future(_run())   # runs sender+receiver concurrently
  │    ├─ sender():  sends session.config, input.text, input.end
  │    └─ receiver(): puts WAV chunks into chunk_queue; puts None sentinel when done
  └─ while True:
       chunk = await chunk_queue.get()
       if chunk is None: break
       yield chunk
  (finally: task.cancel())
```

---

## TTSRouter Changes

### `__init__` — additions

After the existing `kokoro_jp` block, add:

```python
# Qwen3 TTS (final fallback for both English and Japanese)
qwen3_tts_enabled = getattr(config, "qwen3_tts_enabled", False)
if qwen3_tts_enabled:
    try:
        from server.tts.qwen3_tts import Qwen3TTSEngine
        self.qwen3_tts = Qwen3TTSEngine(config)
        logger.info(
            f"Qwen3TTSEngine initialised (final fallback) -- "
            f"url={config.qwen3_tts_ws_url!r}"
        )
    except Exception as exc:
        logger.warning(f"Failed to initialise Qwen3TTSEngine: {exc}")
        self.qwen3_tts = None
else:
    logger.info("Qwen3TTSEngine disabled via config (qwen3_tts_enabled=False)")
    self.qwen3_tts = None
```

### `synthesize_stream` — English path

Current code calls `engine.synthesize_stream(text)` directly with no fallback.
Change to collect chunks and fall back to Qwen3 if zero chunks were yielded:

```python
if lang == "en":
    engine = self.get_engine("en")
    if engine is None:
        logger.error("TTSRouter.synthesize_stream: no English engine available")
        return
    chunks_yielded = 0
    async for chunk in engine.synthesize_stream(text):
        chunks_yielded += 1
        yield chunk
    if chunks_yielded == 0 and self.qwen3_tts is not None:
        logger.warning(
            "TTSRouter: KokoroTTS produced no audio -- "
            "falling back to Qwen3TTSEngine (English)"
        )
        async for chunk in self.qwen3_tts.synthesize_stream(text):
            yield chunk
    return
```

### `synthesize_stream` — Japanese path

Append `("Qwen3TTSEngine", self.qwen3_tts)` to `ja_engines` when not None:

```python
ja_engines = []
if self.kokoclone is not None:
    ja_engines.append(("KokoCloneTTS", self.kokoclone))
if self.kokoro_jp is not None:
    ja_engines.append(("KokoroJapaneseTTS", self.kokoro_jp))
if self.qwen3_tts is not None:                          # NEW
    ja_engines.append(("Qwen3TTSEngine", self.qwen3_tts))  # NEW
```

The rest of the loop (try each engine, fall back on zero chunks) is unchanged.

### `health_check_all` — addition

```python
if self.qwen3_tts is not None:
    results["qwen3_tts"] = await self.qwen3_tts.health_check()
```

---

## Health Endpoint Changes (`server/main.py`)

After the existing `kokoro_ja` block in the `/health` handler, add:

```python
# Qwen3 TTS (final fallback)
if config and not config.qwen3_tts_enabled:
    tts_status["qwen3_tts"] = "disabled"
elif tts_router and tts_router.qwen3_tts:
    try:
        is_ready = await tts_router.qwen3_tts.health_check()
        tts_status["qwen3_tts"] = "ready" if is_ready else "unavailable"
    except Exception as e:
        tts_status["qwen3_tts"] = f"error: {str(e)}"
```

Example health response when enabled and reachable:

```json
{
  "status": "healthy",
  "tts": {
    "kokoro_en": "ready",
    "kokoclone_ja": "ready",
    "kokoro_ja": "ready",
    "qwen3_tts": "ready"
  }
}
```

---

## Error Handling Strategy

| Scenario | Behaviour |
|----------|-----------|
| `qwen3_tts_enabled = False` | `synthesize_stream` yields nothing immediately; `health_check` returns `False` |
| Empty / whitespace-only text | Log `WARNING`, yield nothing, return |
| WebSocket connection refused | Log `ERROR`, yield nothing, no exception raised to caller |
| WebSocket connection timeout | Log `ERROR`, yield nothing, no exception raised to caller |
| Binary frame with 0 bytes | `_pcm_to_wav` returns `None`; frame is silently discarded |
| JSON frame with unknown `type` | Log `DEBUG`, continue receiving |
| `audio.done` JSON frame | Log `DEBUG`, continue receiving (sentence boundary marker) |
| `ConnectionClosed` after `input.end` | Normal completion — stop iteration |
| `asyncio.CancelledError` | Propagate immediately; `finally` block cancels the internal `_run` task |
| `_run` task raises unexpected exception | Log `ERROR`, put `None` sentinel into queue so the generator terminates cleanly |

**CancelledError propagation detail**: The `tts_worker` in `pipeline.py` creates
synthesis tasks via `asyncio.create_task` and cancels them on interrupt via
`self._synthesis_tasks`. The `finally` block in `synthesize_stream` cancels the
internal `_run` task and awaits it (suppressing its `CancelledError`) so no
dangling tasks remain. The `CancelledError` from the outer `await chunk_queue.get()`
propagates normally to the caller.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all
valid executions of a system — essentially, a formal statement about what the
system should do. Properties serve as the bridge between human-readable
specifications and machine-verifiable correctness guarantees.*

### Property 1: PCM-to-WAV round-trip

*For any* non-empty `bytes` value `p` (representing raw int16 PCM data),
`_pcm_to_wav(p)` SHALL produce a valid WAV file `w` such that opening `w` with
the `wave` module yields: `channels == 1`, `sampwidth == 2`,
`framerate == 24000`, and `wf.readframes(wf.getnframes()) == p`.

**Validates: Requirements 2.1, 2.3, 1.5**

---

### Property 2: Disabled engine always yields nothing

*For any* text string `t` (including valid non-empty strings), when
`qwen3_tts_enabled` is `False`, `Qwen3TTSEngine.synthesize_stream(t)` SHALL
yield zero chunks and `health_check()` SHALL return `False`.

**Validates: Requirements 1.7, 7.1 (partial)**

---

### Property 3: Whitespace-only input yields nothing

*For any* string `t` composed entirely of whitespace characters (spaces, tabs,
newlines, carriage returns, etc.), `Qwen3TTSEngine.synthesize_stream(t)` SHALL
yield zero chunks regardless of the `qwen3_tts_enabled` setting.

**Validates: Requirements 1.3**

---

### Property 4: Protocol message ordering and content

*For any* non-empty text string `t`, when `synthesize_stream(t)` is called with
a mock WebSocket, the sequence of JSON messages sent SHALL satisfy:
(a) the first message has `type == "session.config"` and contains `voice`,
`language`, `stream_audio: true`, and `response_format: "pcm"`;
(b) a subsequent message has `type == "input.text"` and `text == t`;
(c) the final sent message has `type == "input.end"`;
(d) `input.end` appears after `input.text` in the send sequence.

**Validates: Requirements 3.1, 3.2, 3.3**

---

### Property 5: Unexpected JSON message types are handled gracefully

*For any* JSON message with a `type` field that is not `"audio.done"`, when the
mock WebSocket emits that message followed by a valid binary PCM frame,
`synthesize_stream` SHALL yield the WAV chunk for the binary frame without
raising an exception.

**Validates: Requirements 3.6**

---

### Property 6: English fallback — Qwen3 used when Kokoro yields nothing

*For any* non-empty text string `t`, when `TTSRouter.synthesize_stream(t, "en")`
is called with a mock Kokoro that yields zero chunks and a mock Qwen3 that
yields one or more chunks, the router SHALL yield all of Qwen3's chunks and
SHALL have called `Qwen3TTSEngine.synthesize_stream`.

**Validates: Requirements 4.2**

---

### Property 7: English no-fallback — Qwen3 NOT invoked when Kokoro succeeds

*For any* non-empty text string `t`, when `TTSRouter.synthesize_stream(t, "en")`
is called with a mock Kokoro that yields at least one chunk, the router SHALL
NOT call `Qwen3TTSEngine.synthesize_stream` for that request.

**Validates: Requirements 4.3**

---

### Property 8: Japanese cascading fallback reaches Qwen3

*For any* non-empty text string `t`, when `TTSRouter.synthesize_stream(t, "ja")`
is called with mock KokoClone and mock KokoroJP both yielding zero chunks, and
mock Qwen3 yielding one or more chunks, the router SHALL yield all of Qwen3's
chunks.

**Validates: Requirements 5.3**

---

### Property 9: Truthy env var parsing is case-insensitive

*For any* string that is a case variation of `"true"`, `"1"`, or `"yes"` (e.g.
`"True"`, `"TRUE"`, `"tRuE"`, `"YES"`, `"Yes"`, `"1"`), setting
`QWEN3_TTS_ENABLED` to that string and calling `Config.from_env()` SHALL
produce `qwen3_tts_enabled == True`.

**Validates: Requirements 6.4**

---

## Testing Strategy

### Property-Based Testing Library

Use **[Hypothesis](https://hypothesis.readthedocs.io/)** (Python), the standard
PBT library for the Python ecosystem. Configure each property test with
`@settings(max_examples=100)`.

Tag format for each test:
```python
@settings(max_examples=100)
@given(...)
def test_property_N_description(...)
    # Feature: qwen3-tts-fallback, Property N: <property text>
```

### Unit Tests (example-based)

Focus on specific protocol behaviors and error conditions:

- `health_check` returns `True` when mock WebSocket connects successfully
- `health_check` returns `False` when connection is refused
- `synthesize_stream` yields nothing and does not raise when connection is refused
- `session.config` is the first message sent (protocol ordering)
- `audio.done` JSON frame does not stop the stream prematurely
- `ConnectionClosed` after `input.end` is treated as normal completion
- `asyncio.CancelledError` propagates out of `synthesize_stream`
- `Config.from_env()` defaults `qwen3_tts_enabled` to `False` when env var absent
- Health endpoint returns `"disabled"` when `qwen3_tts_enabled=False`
- Health endpoint returns `"ready"` / `"unavailable"` based on `health_check` result
- Health endpoint returns `"error: <msg>"` when `health_check` raises

### Integration Tests

Run against a live vLLM-Omni server (CI optional, manual verification):

- `synthesize_stream` yields at least one WAV chunk for a non-empty Japanese sentence
- `health_check` returns `True` when the server is running
- End-to-end: TTSRouter routes Japanese text through Qwen3 when KokoClone is down

### Property Test Configuration

```python
# Property 1: PCM-to-WAV round-trip
@settings(max_examples=200)
@given(st.binary(min_size=2).filter(lambda b: len(b) % 2 == 0))
def test_pcm_to_wav_round_trip(pcm_bytes):
    # Feature: qwen3-tts-fallback, Property 1: PCM-to-WAV round-trip
    wav = _pcm_to_wav(pcm_bytes)
    assert wav is not None
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000
        assert wf.readframes(wf.getnframes()) == pcm_bytes
```

---

## Setup Guide

### Starting the vLLM-Omni Server

```bash
pip install vllm-omni

# Default model (0.6B — suitable for single-user real-time on lighter hardware)
vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice \
  --port 8001 \
  --async-chunk

# Higher quality / multi-user upgrade option
vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --port 8001 \
  --async-chunk
```

The `--async-chunk` flag is **required** for streaming output. Without it,
`response_format="pcm"` streaming will not work.

### Environment Variables

| Variable | Type | Default | Accepted values |
|----------|------|---------|----------------|
| `QWEN3_TTS_ENABLED` | bool | `false` | `true`, `1`, `yes` (case-insensitive) to enable |
| `QWEN3_TTS_WS_URL` | str | `ws://localhost:8001/v1/audio/speech/stream` | Any valid `ws://` or `wss://` URL |
| `QWEN3_TTS_VOICE` | str | `Ono_Anna` | Any voice preset supported by the model |
| `QWEN3_TTS_LANGUAGE` | str | `ja` | BCP-47 language tag (e.g. `ja`, `en`, `zh`) |

### Fallback Chain Summary

- **English**: Kokoro TTS → *(Qwen3 TTS if Kokoro yields nothing)*
- **Japanese**: KokoClone TTS → KokoroJP → *(Qwen3 TTS if both yield nothing)*

Qwen3 TTS is only invoked when all higher-priority engines in the chain produce
zero audio chunks for a given sentence. If `QWEN3_TTS_ENABLED=false` (the
default), the chains behave exactly as before this feature.

### Verification

Before enabling the fallback, confirm the server is reachable:

```bash
# Quick connectivity check (Python one-liner)
python -c "
import asyncio, websockets

async def check():
    try:
        async with websockets.connect('ws://localhost:8001/v1/audio/speech/stream',
                                      open_timeout=3.0):
            print('OK — vLLM-Omni server is reachable')
    except Exception as e:
        print(f'FAIL — {e}')

asyncio.run(check())
"
```

Or use the `/health` endpoint once the main server is running:

```bash
curl -s http://localhost:8765/health | python -m json.tool | grep qwen3_tts
# Expected: "qwen3_tts": "ready"
```

### Model Selection

| Use case | Model |
|----------|-------|
| Single-user real-time, lighter GPU | `Qwen3-TTS-12Hz-0.6B-CustomVoice` (default) |
| Higher quality or ~6 concurrent streams | `Qwen3-TTS-12Hz-1.7B-CustomVoice` |
| Voice cloning from reference audio | `Qwen3-TTS-12Hz-1.7B-Base` (requires `task_type: "Base"` and `reference_audio`) |
