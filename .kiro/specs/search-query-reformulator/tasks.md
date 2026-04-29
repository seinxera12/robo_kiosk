# Implementation Plan: Search Query Reformulator

## Overview

Implement a thin, isolated preprocessing module (`server/search/query_reformulator.py`)
that converts raw conversational transcripts into concise English search queries via a
non-streaming Ollama call, then wire it into the `Intent.SEARCH` branch of `pipeline.py`
with a single-line change. Add `hypothesis` to `requirements.txt` and write both unit
and property-based tests.

**Do NOT touch:** main LLM call, conversation history management, streaming pipeline,
TTS, STT, or any code outside the `Intent.SEARCH` branch of `llm_worker`.

---

## Tasks

- [x] 1. Add `hypothesis` to `server/requirements.txt`
  - Append `hypothesis==6.112.2` (latest stable, compatible with Python 3.10+) to
    `server/requirements.txt` under the `# Utilities` section.
  - Verify `httpx` is already present (it is — `httpx==0.25.1`).
  - _Requirements: Testing Strategy (design §Testing Strategy)_

- [x] 2. Implement `server/search/query_reformulator.py`
  - [x] 2.1 Create the module file with module-level constants and logger
    - Create `server/search/query_reformulator.py`.
    - Define `OLLAMA_BASE_URL: str = "http://localhost:11434"`.
    - Define `REFORMULATOR_MODEL: str = "qwen2.5:3b"`.
    - Set up `logger = logging.getLogger(__name__)`.
    - _Requirements: 5.2, 5.3_

  - [x] 2.2 Implement Japanese character detection helper
    - Write `_is_japanese(text: str) -> bool` (private helper).
    - Return `True` if any character falls in U+3040–U+30FF or U+4E00–U+9FAF.
    - _Requirements: 2.1_

  - [x] 2.3 Implement system prompt builder
    - Write `_build_system_prompt(is_japanese: bool) -> str` (private helper).
    - English path: instructs model to extract a concise 3–6 word English query,
      output only the query, no explanation, no punctuation at end, no quotes, one line.
    - Japanese path: same structure but second sentence says "translate the user's
      Japanese message into a concise English web search query of 3 to 6 words".
    - System prompt must NOT change based on `recent_history` presence.
    - _Requirements: 2.2, 2.3, 7.5_

  - [x] 2.4 Implement `extract_search_query` — core logic
    - Full signature:
      `def extract_search_query(user_message: str, recent_history: list[dict] | None = None) -> str`
    - Enforce hard history slice: `history_slice = (recent_history or [])[-6:]`.
    - Build `messages` array: `[system_msg] + history_slice + [current_user_msg]`.
    - Pass `history_slice` entries through as-is (role/content preserved; `lang` field
      ignored but not stripped).
    - Use `httpx.Client` (synchronous) with `httpx.Timeout(10.0)`.
    - POST to `f"{OLLAMA_BASE_URL}/api/chat"` with body:
      `{"model": REFORMULATOR_MODEL, "stream": False, "options": {"temperature": 0, "num_predict": 32}, "messages": messages}`.
    - Parse `response.json()["message"]["content"].strip()` and return it.
    - Wrap entire logic in `try/except Exception`: log at WARNING level
      (`"Query reformulation failed: {e}; falling back to raw input"`) and
      `return user_message`.
    - Do NOT mutate `recent_history`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 3.2, 3.3, 5.1, 6.1, 6.2, 6.4,
      7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.8_

  - [ ]* 2.5 Write unit tests for `query_reformulator.py`
    - Create `server/search/test_query_reformulator.py`.
    - Use `unittest.mock.patch` to mock `httpx.Client.post`.
    - Cover:
      - Successful English reformulation returns stripped content.
      - Successful Japanese reformulation returns stripped content and uses translation prompt.
      - `httpx.ConnectError` triggers fallback to `user_message`.
      - `httpx.TimeoutException` triggers fallback to `user_message`.
      - Non-2xx HTTP status triggers fallback.
      - Malformed JSON / missing key triggers fallback.
      - `recent_history=None` and `recent_history=[]` produce identical `messages` arrays.
      - `recent_history` with 10 entries is sliced to 6 in the request.
      - `OLLAMA_BASE_URL` defaults to `"http://localhost:11434"`.
      - `REFORMULATOR_MODEL` defaults to `"qwen2.5:3b"`.
      - Request body contains `stream=False`, `temperature=0`, `num_predict=32`.
      - WARNING is logged on any exception.
      - Current user message is always the last element in `messages`.
    - _Requirements: 1.2, 1.5, 2.1, 3.1, 3.2, 3.3, 5.2, 5.3, 6.2, 7.2, 7.3, 7.6_

- [x] 3. Checkpoint — unit tests pass
  - Ensure all unit tests in `test_query_reformulator.py` pass.
  - Ask the user if any questions arise before proceeding.

- [x] 4. Write property-based tests for `query_reformulator.py`
  - Create `server/search/test_query_reformulator_properties.py`.
  - Use `hypothesis` with `@given` / `@settings(max_examples=100)`.
  - Implement a `capture_ollama_request` helper that patches `httpx.Client.post`,
    captures the JSON body sent to Ollama, and returns it (used by Properties 4–9).
  - Implement a `mock_ollama_success(response_text)` context manager that patches
    `httpx.Client.post` to return a valid Ollama-shaped response.
  - Implement a `mock_ollama_raises(exc)` context manager that patches
    `httpx.Client.post` to raise the given exception.

  - [ ]* 4.1 Property 1 — Non-empty output invariant
    - `@given(st.text(min_size=1))`
    - Mock Ollama to return a valid non-empty response.
    - Assert `len(result.strip()) > 0`.
    - **Property 1: Non-empty output invariant**
    - **Validates: Requirements 6.2, 3.1**

  - [ ]* 4.2 Property 2 — Fallback preserves original input
    - `@given(st.text(min_size=1))` combined with a set of exception classes
      (`ConnectError`, `TimeoutException`, `KeyError`, `ValueError`).
    - Mock Ollama to raise each exception class.
    - Assert `result == user_message`.
    - **Property 2: Fallback preserves original input**
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 4.3 Property 3 — Whitespace is always stripped
    - `@given(st.text(), st.text(alphabet=" \t\n\r", min_size=0))`
    - Construct `raw_response = padding + core_content + padding`.
    - Mock Ollama to return `raw_response`.
    - Assert `result == raw_response.strip()`.
    - **Property 3: Whitespace is always stripped**
    - **Validates: Requirements 1.5**

  - [ ]* 4.4 Property 4 — Japanese detection drives system prompt selection
    - Two sub-cases:
      1. `@given(st.text(alphabet=st.characters(min_codepoint=0x3040, max_codepoint=0x30FF), min_size=1))` — assert `"translate"` in system prompt (case-insensitive).
      2. `@given(st.text(alphabet=st.characters(max_codepoint=0x302F), min_size=1))` — assert `"translate"` NOT in system prompt.
    - Use `capture_ollama_request` to inspect `messages[0]["content"]`.
    - **Property 4: Japanese detection drives system prompt selection**
    - **Validates: Requirements 2.1, 2.3**

  - [ ]* 4.5 Property 5 — History slice hard limit
    - `@given(st.lists(st.fixed_dictionaries({"role": st.sampled_from(["user","assistant"]), "content": st.text()}), min_size=7, max_size=50))`
    - Use `capture_ollama_request` to inspect `messages`.
    - Assert `len(messages[1:-1]) <= 6` (history messages between system and current user).
    - **Property 5: History slice hard limit**
    - **Validates: Requirements 7.2**

  - [ ]* 4.6 Property 6 — Current message is always last
    - `@given(st.text(min_size=1), st.lists(st.fixed_dictionaries({"role": st.sampled_from(["user","assistant"]), "content": st.text()}), min_size=1))`
    - Use `capture_ollama_request`.
    - Assert `messages[-1]["role"] == "user"` and `messages[-1]["content"] == user_message`.
    - **Property 6: Current message is always last**
    - **Validates: Requirements 7.3**

  - [ ]* 4.7 Property 7 — `recent_history` is not mutated
    - `@given(st.lists(st.fixed_dictionaries({"role": st.sampled_from(["user","assistant"]), "content": st.text()})))`
    - Take a `copy.deepcopy` of `history` before the call.
    - Mock Ollama to return a valid response.
    - Assert `history == original` after the call.
    - **Property 7: recent_history is not mutated**
    - **Validates: Requirements 7.4**

  - [ ]* 4.8 Property 8 — System prompt is invariant to `recent_history` presence
    - `@given(st.text(min_size=1), st.lists(st.fixed_dictionaries({"role": st.sampled_from(["user","assistant"]), "content": st.text()})))`
    - Capture request with `recent_history=None` and with the generated list.
    - Assert `captured_none["messages"][0]["content"] == captured_hist["messages"][0]["content"]`.
    - **Property 8: System prompt invariant to recent_history**
    - **Validates: Requirements 7.5**

  - [ ]* 4.9 Property 9 — `None` and empty list are equivalent
    - `@given(st.text(min_size=1))`
    - Capture request with `recent_history=None` and `recent_history=[]`.
    - Assert `captured_none["messages"] == captured_empty["messages"]`.
    - **Property 9: None and [] are equivalent**
    - **Validates: Requirements 7.6**

- [x] 5. Checkpoint — property tests pass
  - Ensure all property tests in `test_query_reformulator_properties.py` pass.
  - Ask the user if any questions arise before proceeding.

- [x] 6. Wire `extract_search_query` into `pipeline.py`
  - [x] 6.1 Modify the `Intent.SEARCH` branch in `llm_worker`
    - In `server/pipeline.py`, locate the `elif intent == Intent.SEARCH:` block.
    - Add import: `from server.search.query_reformulator import extract_search_query`
      (alongside the existing `from server.search.searxng_client import searxng_search`).
    - Before the `searxng_search` call, add:
      ```python
      search_query = extract_search_query(
          transcript.text,
          recent_history=self.state.conversation_history,
      )
      logger.info(f"Reformulated query: '{search_query}' (original: '{transcript.text[:50]}')")
      ```
    - Replace `query=transcript.text` in the `searxng_search` call with
      `query=search_query`.
    - Update the existing `logger.info(f"Search returned {len(results)} results for query: ...")` 
      line to reference `search_query` instead of `transcript.text`.
    - Do NOT change any other code in `pipeline.py`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.3_

- [x] 7. Final checkpoint — full test suite passes
  - Run `python -m pytest server/search/test_query_reformulator.py server/search/test_query_reformulator_properties.py -v`.
  - Ensure all tests pass with no errors.
  - Ask the user if any questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- The reformulated query is a local variable only — it is never appended to
  `conversation_history`, never sent over WebSocket, and never passed to the main LLM.
- `extract_search_query` is synchronous (uses `httpx.Client`, not `AsyncClient`);
  it blocks the event loop for at most 10 seconds, which is acceptable given the
  existing `searxng_search` call already blocks for up to 8 seconds.
- All 9 correctness properties from the design are covered by tasks 4.1–4.9.
- Property tests use `@settings(max_examples=100)` minimum per the design spec.
- The `capture_ollama_request` helper is the key test utility — it intercepts the
  `httpx.Client.post` call and returns the parsed JSON body for assertion.
