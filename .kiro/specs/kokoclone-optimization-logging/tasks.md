# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - No Structured Log File After Synthesis
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the observability gap exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate that `kokoclone.log` is absent (or contains no timing entries) after synthesis on unfixed code
  - **Scoped PBT Approach**: Scope the property to the concrete failing case — any call to `KokoClone.generate()` (or a lightweight mock of it) followed by a filesystem check for `kokoclone.log`
  - Bug Condition from design: `NOT file_exists("kokoclone/kokoclone.log") OR NOT log_contains_entry WHERE entry.phase IN {"kokoro_tts", "kanade_vc", "total"} AND entry.elapsed_seconds > 0`
  - Write a property-based test (e.g. using `hypothesis`) that:
    1. Patches `KokoClone.generate()` to skip actual model inference (mock Kokoro and Kanade calls)
    2. Calls the patched `generate()` with arbitrary `(text, lang)` inputs
    3. Asserts that `kokoclone/kokoclone.log` does NOT exist after the call (confirming the bug)
    4. Also asserts that no line in captured stdout contains `elapsed_seconds=` (confirming no timing data)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test PASSES (the log file is absent — this is the bug we are fixing)
  - Document counterexamples found, e.g. "After generate(), kokoclone.log does not exist; stdout contains only bare print() lines with no elapsed_seconds field"
  - Mark task complete when test is written, run, and the absence of `kokoclone.log` is confirmed
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Audio Output Is Numerically Unchanged After Logging Changes
  - **IMPORTANT**: Follow observation-first methodology — run unfixed code first, record outputs, then write assertions
  - Observe: `chunked_voice_conversion()` on unfixed code returns a specific waveform tensor for a given `(source_wav, ref_wav)` pair
  - Observe: `KokoClone.generate()` on unfixed code writes a WAV file with a specific byte sequence to `output_path`
  - Observe: `KokoCloneTTS.synthesize_stream()` on unfixed code yields the same WAV bytes it received from the mocked HTTP response
  - Write property-based tests (e.g. using `hypothesis`) that:
    1. **Single-chunk preservation**: For random waveform tensors shorter than `chunk_samples`, assert `chunked_voice_conversion()` returns a numerically identical tensor before and after the fix (mock `kanade.voice_conversion` and `vocode` to return deterministic outputs)
    2. **Multi-chunk preservation**: For random waveform tensors longer than `chunk_samples`, assert the assembled tensor is numerically identical before and after the fix
    3. **HTTP client preservation**: Mock `httpx` to return a fixed WAV byte sequence; assert `synthesize_stream()` yields the same bytes after adding the `round_trip_ms` log call
  - Non-bug condition from design: inputs where `isBugCondition(X)` is false — i.e., the logging infrastructure is already in place and audio output is the focus
  - Verify all three property tests PASS on UNFIXED code (confirms baseline behavior to preserve)
  - **EXPECTED OUTCOME**: Tests PASS on unfixed code (confirms no audio regression baseline)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6_

- [x] 3. Implement structured logging across all KokoClone components

  - [x] 3.1 Create `kokoclone/core/logging_setup.py` — shared logger factory
    - Create new file `kokoclone/core/logging_setup.py`
    - Define `LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "kokoclone.log")`
    - Define `_FORMATTER` with format `"%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"` and `datefmt="%Y-%m-%d %H:%M:%S"`
    - Implement `get_kokoclone_logger(name: str) -> logging.Logger` that returns a logger named `"kokoclone.<name>"` backed by a `FileHandler` pointing to `LOG_FILE`
    - Make the function idempotent: check `if not logger.handlers` before adding a new `FileHandler`
    - Set `logger.propagate = False` to prevent double-logging to root/basicConfig
    - _Bug_Condition: `NOT file_exists("kokoclone/kokoclone.log")` — no FileHandler is ever created on unfixed code_
    - _Expected_Behavior: `get_kokoclone_logger("server")` creates `kokoclone.log` on first call and returns the same logger on subsequent calls with exactly one FileHandler_
    - _Preservation: No audio processing logic is touched; this is a new file only_
    - _Requirements: 2.7_

  - [x] 3.2 Update `kokoclone/server.py` — replace basicConfig, add request_id, structured log entries
    - Add `import uuid` at the top of the file
    - Add `from core.logging_setup import get_kokoclone_logger` import
    - Remove the `logging.basicConfig(...)` call
    - Replace `logger = logging.getLogger(__name__)` with `logger = get_kokoclone_logger("server")`
    - At the top of `synthesize()`, generate `request_id = uuid.uuid4().hex[:8]`
    - Replace `logger.info(f"Synthesising [{req.lang}]: {req.text[:80]!r}")` with structured entry: `logger.info(f"request_received text={req.text[:80]!r} lang={req.lang!r} request_id={request_id} text_len={len(req.text)}")`
    - Pass `request_id=request_id` to `cloner.generate()`
    - After reading `wav_bytes`, add: `logger.info(f"request_complete request_id={request_id} response_bytes={len(wav_bytes)}")`
    - In the `except` block, replace existing error log with: `logger.error(f"request_failed request_id={request_id} exc_type={type(exc).__name__} message={exc}", exc_info=True)`
    - _Bug_Condition: `isBugCondition(X)` where no structured entry with `request_id` is written to `kokoclone.log`_
    - _Expected_Behavior: `kokoclone.log` contains `request_received`, `request_complete` (or `request_failed`) entries with `request_id` for every synthesis call_
    - _Preservation: `GET /health` return value unchanged; `synthesize()` still returns WAV bytes; exceptions still raise HTTP 500_
    - _Requirements: 2.1, 2.6, 2.7, 3.1, 3.3_

  - [x] 3.3 Update `kokoclone/core/cloner.py` — add timing, structured logging, accept request_id
    - Add `from core.logging_setup import get_kokoclone_logger` import
    - Add `import time` (already present — verify it is used for `perf_counter`)
    - Add module-level `_logger = get_kokoclone_logger("cloner")`
    - Change `generate()` signature to `def generate(self, text, lang, reference_audio, output_path="output.wav", request_id="")`
    - Replace `print(f"Synthesizing text ({lang.upper()})...")` with `_logger.info(f"synthesizing lang={lang.upper()} request_id={request_id}")`
    - Wrap the `kokoro.create()` call with `time.perf_counter()` bookends; capture `_kokoro_elapsed` and `_audio_duration = len(samples) / sr`
    - After the Kokoro phase, log: `_logger.info(f"phase=kokoro_tts request_id={request_id} elapsed_seconds={_kokoro_elapsed:.3f} audio_duration_seconds={_audio_duration:.3f} lang={lang}")`
    - Replace `print("Applying Voice Clone...")` with `_logger.info(f"applying_voice_clone request_id={request_id}")`
    - Wrap the `chunked_voice_conversion()` call with `time.perf_counter()` bookends; capture `_vc_elapsed` and `_vc_duration = converted_wav.shape[-1] / self.sample_rate`
    - Pass `request_id=request_id` to `chunked_voice_conversion()`
    - After the Kanade VC phase, log: `_logger.info(f"phase=kanade_vc request_id={request_id} elapsed_seconds={_vc_elapsed:.3f} audio_duration_seconds={_vc_duration:.3f}")`
    - After `sf.write(output_path, ...)`, log total: `_logger.info(f"phase=total request_id={request_id} total_elapsed_seconds={(_kokoro_elapsed + _vc_elapsed):.3f}")`
    - Replace `print(f"Success! Saved: {output_path}")` with `_logger.info(f"saved output_path={output_path} request_id={request_id}")`
    - In the `except` block inside `generate()`, add: `_logger.error(f"phase=kanade_vc request_id={request_id} exc_type={type(exc).__name__} message={exc}", exc_info=True)` then `raise`
    - _Bug_Condition: `isBugCondition(X)` where no `phase=kokoro_tts`, `phase=kanade_vc`, or `phase=total` entries with `elapsed_seconds > 0` appear in `kokoclone.log`_
    - _Expected_Behavior: `kokoclone.log` contains three phase entries per `generate()` call, each with `request_id` and `elapsed_seconds > 0`_
    - _Preservation: `generate()` still writes a valid WAV file to `output_path`; Kokoro cache reuse is unchanged; exceptions are re-raised after logging_
    - _Requirements: 2.2, 2.3, 2.6, 3.1, 3.2, 3.8_

  - [x] 3.4 Update `kokoclone/core/chunked_convert.py` — add request_id, structured logging, per-chunk timing
    - Add `from core.logging_setup import get_kokoclone_logger` import
    - Add module-level `_logger = get_kokoclone_logger("chunked_convert")`
    - Change signature to `def chunked_voice_conversion(..., request_id="")`
    - Replace the VRAM budget `print(...)` with: `_logger.info(f"chunk_config request_id={request_id} vram_budget_gb={budget_gb:.2f} vram_fraction={vram_fraction:.0%} total_vram_gb={total_vram_bytes / (1024**3):.2f} chunk_seconds={chunk_seconds:.1f} chunk_samples={chunk_samples} rope_ceiling_seconds={rope_safe_seconds:.1f}")`
    - Add `chunk_index = 0` counter before the `while pos < n_samples` loop
    - Inside the loop, add `_chunk_t0 = time.perf_counter()` before `kanade.voice_conversion()`
    - After `mel_chunk = mel_chunk.cpu()`, log: `_logger.info(f"chunk request_id={request_id} chunk_index={chunk_index} chunk_duration_s={(win_end - win_start) / sample_rate:.2f} elapsed_s={time.perf_counter() - _chunk_t0:.3f}")` then increment `chunk_index += 1`
    - Replace both `print(f"[chunked_convert] Completed in {elapsed:.1f}s")` calls (single-chunk and multi-chunk paths) with: `_logger.info(f"chunked_convert_complete request_id={request_id} elapsed_seconds={elapsed:.3f} n_chunks={chunk_index + 1}")`
    - Note: `time` is already imported in this file — no new import needed
    - _Bug_Condition: `isBugCondition(X)` where chunk-level timing is written only to stdout via `print()` and not to `kokoclone.log`_
    - _Expected_Behavior: `kokoclone.log` contains `chunk_config`, per-`chunk`, and `chunked_convert_complete` entries with `request_id` and timing data_
    - _Preservation: Return value (waveform tensor) is numerically identical; single-chunk and multi-chunk paths both still return correct assembled waveform_
    - _Requirements: 2.4, 3.4, 3.5_

  - [x] 3.5 Update `server/tts/kokoclone_tts.py` — add HTTP round-trip timing
    - Add `import time` at the top of the file
    - Before the `async with httpx.AsyncClient() as client:` block, add `_t_start = time.perf_counter()`
    - After `wav_bytes = resp.content`, add: `_round_trip_ms = (time.perf_counter() - _t_start) * 1000` then `logger.info(f"[KokoCloneTTS] synthesis_complete round_trip_ms={_round_trip_ms:.1f} response_bytes={len(wav_bytes)}")`
    - Replace the existing `logger.info(f"[KokoCloneTTS] received {len(wav_bytes)} bytes of WAV audio")` line with the new structured entry above (do not keep both)
    - _Bug_Condition: `isBugCondition(X)` where HTTP round-trip duration is never recorded_
    - _Expected_Behavior: Main server log contains `synthesis_complete round_trip_ms=NNN response_bytes=NNN` after each successful synthesis_
    - _Preservation: `synthesize_stream()` still yields the same WAV bytes; error handling (ConnectError, TimeoutException, HTTPStatusError) is unchanged_
    - _Requirements: 2.5, 3.6_

  - [x] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Structured Log Entries Present After Synthesis
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 asserts that `kokoclone.log` does NOT exist after synthesis; on fixed code this assertion will FAIL (the log file now exists), which means the test needs to be inverted for the fix-checking phase
    - Invert the assertion: assert that `kokoclone.log` DOES exist and contains at least one entry with `phase IN {"kokoro_tts", "kanade_vc", "total"}` and `elapsed_seconds > 0` and the correct `request_id`
    - Run the bug condition exploration test from task 1 (with inverted assertion) on FIXED code
    - **EXPECTED OUTCOME**: Test PASSES (confirms `kokoclone.log` is created and contains structured timing entries)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Audio Output Unchanged After Logging Changes
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run all three preservation property tests (single-chunk, multi-chunk, HTTP client) from task 2 on FIXED code
    - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions in audio output, waveform content, or HTTP byte delivery)
    - Confirm that `chunked_voice_conversion()` returns numerically identical tensors before and after the fix
    - Confirm that `synthesize_stream()` yields the same WAV bytes before and after the fix

- [x] 4. Checkpoint — Ensure all tests pass
  - Run the full test suite for the kokoclone spec
  - Confirm Property 1 (bug condition / fix checking) passes on fixed code
  - Confirm Property 2 (preservation) passes on fixed code
  - Confirm `GET /health` still returns `{"status": "ok", "sample_rate": <int>}` with HTTP 200
  - Confirm `kokoclone.log` is created in `kokoclone/` (not in `kokoclone/core/`) on first synthesis call
  - Confirm each log entry matches the format `YYYY-MM-DD HH:MM:SS.mmm [LEVEL] [kokoclone.<component>] message key=value ...`
  - Confirm that a logging failure (e.g. disk full) does not propagate and break synthesis
  - Ask the user if any questions arise before closing the spec
