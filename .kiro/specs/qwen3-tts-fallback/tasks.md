# Implementation Plan: qwen3-tts-fallback

## Overview

Add `Qwen3TTSEngine` as the final fallback TTS engine for both English and
Japanese synthesis chains. The implementation touches four files: a new engine
module, config additions, router changes, and a health-endpoint update. Tests
use Hypothesis for property-based coverage and pytest for unit tests.

Fallback chains after this feature:
- **English**: KokoroTTS → Qwen3TTSEngine
- **Japanese**: KokoCloneTTS → KokoroJapaneseTTS → Qwen3TTSEngine

---

## Tasks

- [x] 1. Add Qwen3 TTS configuration fields to `server/config.py`
  - Add four new dataclass fields after the `kokoclone_url` field:
    `qwen3_tts_enabled: bool = False`, `qwen3_tts_ws_url: str`, `qwen3_tts_voice: str`, `qwen3_tts_language: str`
  - Add corresponding `from_env()` entries reading `QWEN3_TTS_ENABLED`, `QWEN3_TTS_WS_URL`, `QWEN3_TTS_VOICE`, `QWEN3_TTS_LANGUAGE`
  - `QWEN3_TTS_ENABLED` truthy values: `"true"`, `"1"`, `"yes"` (case-insensitive); default `False`
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 2. Implement `server/tts/qwen3_tts.py` — module helper and engine class
  - [x] 2.1 Implement `_pcm_to_wav(pcm_bytes: bytes) -> bytes | None`
    - Module-level function using stdlib `wave` module (no new dependencies)
    - Parameters: channels=1, sampwidth=2, framerate=24000
    - Input is raw int16 bytes (NOT float32 like Kokoro)
    - Return `None` when `pcm_bytes` is empty (zero length)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 2.2 Write property test for `_pcm_to_wav` round-trip
    - **Property 1: PCM-to-WAV round-trip**
    - Use `@given(st.binary(min_size=2).filter(lambda b: len(b) % 2 == 0))` with `@settings(max_examples=200)`
    - Assert `wav is not None`, channels==1, sampwidth==2, framerate==24000, readframes==pcm_bytes
    - **Validates: Requirements 2.1, 2.3, 1.5**

  - [x] 2.3 Implement `Qwen3TTSEngine.__init__` and `health_check`
    - `__init__(self, config)`: store `_enabled`, `_ws_url`, `_voice`, `_language` from config; no I/O
    - `async def health_check(self) -> bool`: when disabled return `False`; otherwise try
      `websockets.connect(url, open_timeout=3.0)`, close immediately, return `True`; return `False` on any exception
    - _Requirements: 1.2, 1.6, 1.7_

  - [x] 2.4 Implement `Qwen3TTSEngine.synthesize_stream` — guards and internal concurrency model
    - Async generator method `async def synthesize_stream(self, text: str)`
    - Guard: `_enabled` is False → yield nothing, return immediately
    - Guard: `text.strip()` is empty → log WARNING, yield nothing, return
    - Internal `asyncio.Queue` bridges `asyncio.gather(sender(), receiver())` with outer generator
    - `sender()`: send `session.config` JSON (type, voice, task_type, language, split_granularity, stream_audio=true, response_format="pcm"), then `input.text` JSON, then `input.end` JSON
    - `receiver()`: binary frames → `_pcm_to_wav` → put in queue (skip if None); `audio.done` JSON → log DEBUG; unknown JSON → log DEBUG; put `None` sentinel when done
    - Outer loop: `await chunk_queue.get()`, break on `None`, yield chunk
    - `finally`: cancel internal `_run` task
    - Connection errors: log ERROR, yield nothing, no exception raised to caller
    - `asyncio.CancelledError`: propagate immediately (do NOT suppress)
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.2, 7.4_

  - [ ]* 2.5 Write property test: disabled engine always yields nothing
    - **Property 2: Disabled engine always yields nothing**
    - Use `@given(st.text())` — for any text, engine with `qwen3_tts_enabled=False` yields zero chunks and `health_check()` returns `False`
    - **Validates: Requirements 1.7**

  - [ ]* 2.6 Write property test: whitespace-only input yields nothing
    - **Property 3: Whitespace-only input yields nothing**
    - Use `@given(st.text(alphabet=st.characters(whitespace=True), min_size=1))` — any whitespace-only string yields zero chunks regardless of enabled state
    - **Validates: Requirements 1.3**

  - [ ]* 2.7 Write property test: protocol message ordering and content
    - **Property 4: Protocol message ordering and content**
    - Use `@given(st.text(min_size=1).filter(lambda t: t.strip()))` with a mock WebSocket
    - Assert: first sent message has `type=="session.config"` with `voice`, `language`, `stream_audio==True`, `response_format=="pcm"`; a subsequent message has `type=="input.text"` and `text==t`; final message has `type=="input.end"`; `input.end` appears after `input.text`
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [ ]* 2.8 Write property test: unknown JSON message types handled gracefully
    - **Property 5: Unexpected JSON message types are handled gracefully**
    - Use `@given(st.text(min_size=1).filter(lambda t: t not in ("audio.done",)))` — mock WebSocket emits unknown-type JSON then a valid binary PCM frame; assert WAV chunk is yielded without exception
    - **Validates: Requirements 3.6**

  - [ ]* 2.9 Write unit tests for `Qwen3TTSEngine`
    - `health_check` returns `True` when mock WebSocket connects successfully
    - `health_check` returns `False` when connection is refused
    - `synthesize_stream` yields nothing and does not raise on connection refused
    - `asyncio.CancelledError` propagates out of `synthesize_stream`
    - _Requirements: 1.2, 1.4, 7.2_

- [x] 3. Checkpoint — core engine complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Integrate `Qwen3TTSEngine` into `server/tts/tts_router.py`
  - [x] 4.1 Initialise `Qwen3TTSEngine` in `TTSRouter.__init__`
    - After the `kokoro_jp` block, read `getattr(config, "qwen3_tts_enabled", False)`
    - When enabled: import and instantiate `Qwen3TTSEngine(config)`, log URL; on exception log WARNING and set `self.qwen3_tts = None`
    - When disabled: log INFO and set `self.qwen3_tts = None`
    - _Requirements: 4.1, 5.1_

  - [x] 4.2 Update English synthesis path in `TTSRouter.synthesize_stream`
    - Track `chunks_yielded` counter while iterating `engine.synthesize_stream(text)`
    - After the loop, if `chunks_yielded == 0` and `self.qwen3_tts is not None`, log WARNING and iterate `self.qwen3_tts.synthesize_stream(text)`, yielding all chunks
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 4.3 Update Japanese synthesis path in `TTSRouter.synthesize_stream`
    - Append `("Qwen3TTSEngine", self.qwen3_tts)` to `ja_engines` when `self.qwen3_tts is not None`
    - The existing cascading-fallback loop already handles zero-chunk detection and logging — no other changes needed
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 4.4 Update `TTSRouter.health_check_all`
    - After the `kokoro_jp` block, add: `if self.qwen3_tts is not None: results["qwen3_tts"] = await self.qwen3_tts.health_check()`
    - _Requirements: 4.5_

  - [ ]* 4.5 Write property test: English fallback — Qwen3 used when Kokoro yields nothing
    - **Property 6: English fallback — Qwen3 used when Kokoro yields nothing**
    - Use `@given(st.text(min_size=1).filter(lambda t: t.strip()))` — mock Kokoro yields zero chunks, mock Qwen3 yields ≥1 chunk; assert router yields all Qwen3 chunks and `synthesize_stream` was called on Qwen3
    - **Validates: Requirements 4.2**

  - [ ]* 4.6 Write property test: English no-fallback — Qwen3 NOT invoked when Kokoro succeeds
    - **Property 7: English no-fallback — Qwen3 NOT invoked when Kokoro succeeds**
    - Use `@given(st.text(min_size=1).filter(lambda t: t.strip()))` — mock Kokoro yields ≥1 chunk; assert `Qwen3TTSEngine.synthesize_stream` is never called
    - **Validates: Requirements 4.3**

  - [ ]* 4.7 Write property test: Japanese cascading fallback reaches Qwen3
    - **Property 8: Japanese cascading fallback reaches Qwen3**
    - Use `@given(st.text(min_size=1).filter(lambda t: t.strip()))` — mock KokoClone and KokoroJP both yield zero chunks, mock Qwen3 yields ≥1 chunk; assert router yields all Qwen3 chunks
    - **Validates: Requirements 5.3**

- [x] 5. Update `/health` endpoint in `server/main.py`
  - After the `kokoro_ja` block in the `/health` handler, add the Qwen3 TTS status block:
    - When `config and not config.qwen3_tts_enabled`: set `tts_status["qwen3_tts"] = "disabled"`
    - When `tts_router and tts_router.qwen3_tts`: call `health_check()`, set `"ready"` or `"unavailable"`; on exception set `"error: <message>"`
  - _Requirements: 8.1, 8.2, 8.3_

- [x] 6. Checkpoint — integration complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Write remaining unit and property tests in `tests/tts/test_qwen3_tts.py`
  - [ ]* 7.1 Write property test: truthy env var parsing is case-insensitive
    - **Property 9: Truthy env var parsing is case-insensitive**
    - Use `@given(st.sampled_from(["true","1","yes"]).flatmap(lambda s: st.builds(lambda c: "".join(c.upper() if b else c.lower() for c, b in zip(s, st.lists(st.booleans(), min_size=len(s), max_size=len(s)).example())), st.just(s))))` or equivalent case-variation strategy
    - For each variation, set `QWEN3_TTS_ENABLED` env var and call `Config.from_env()`; assert `qwen3_tts_enabled == True`
    - **Validates: Requirements 6.4**

  - [ ]* 7.2 Write unit tests for config defaults and health endpoint
    - `Config.from_env()` defaults `qwen3_tts_enabled` to `False` when `QWEN3_TTS_ENABLED` env var is absent
    - Health endpoint returns `"disabled"` when `qwen3_tts_enabled=False`
    - Health endpoint returns `"ready"` / `"unavailable"` based on `health_check` result
    - Health endpoint returns `"error: <msg>"` when `health_check` raises
    - _Requirements: 6.3, 8.1, 8.2, 8.3_

- [x] 8. Write operator setup guide `qwen3tts.md` at workspace root
  - Document exact `vllm serve` command for `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` with `--port 8001 --async-chunk`
  - List all four environment variables with types, defaults, and accepted values
  - Describe English and Japanese fallback chains
  - Include Python one-liner verification step and `/health` curl check
  - Note `0.6B-CustomVoice` as default and `1.7B-CustomVoice` as upgrade option
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests use Hypothesis (`pip install hypothesis`) — add to dev dependencies if not present
- The `websockets` library is required for `Qwen3TTSEngine` — verify it is in `requirements.txt`
- All property tests live in `tests/tts/test_qwen3_tts.py`; create `tests/tts/__init__.py` if it does not exist
- The `_run` internal task in `synthesize_stream` must be cancelled in the `finally` block to avoid dangling tasks on `CancelledError`
