# Requirements Document

## Introduction

The search query reformulation layer is an isolated preprocessing step inserted between
the user's raw conversational input and the SearXNG web search call in the voice chatbot
pipeline. The current pipeline forwards the raw transcript verbatim to SearXNG, which
produces low-quality results for two reasons: (1) Japanese-language queries hit far fewer
indexed pages because most web content and SEO is English-first, and (2) conversational
phrasing (filler words, politeness markers, full sentences) causes the search engine to
match on noise rather than the user's actual information need.

The fix is a single, non-streaming LLM call — reusing the already-loaded `qwen2.5:3b`
model via Ollama — that extracts a concise 3–6 word English search query before the
SearXNG request is made. The reformulator is completely isolated: it receives only the
latest user message, returns only a plain string, and has no side effects on conversation
history, the main LLM call, the streaming pipeline, or the TTS pipeline.

---

## Glossary

- **Reformulator**: The new isolated module (`query_reformulator.py`) responsible for
  converting raw user input into a clean English search query.
- **Raw_Input**: The verbatim transcript string produced by Faster-Whisper STT and stored
  in `transcript.text`.
- **Reformulated_Query**: The concise English search query string returned by the
  Reformulator, used exclusively as the SearXNG search string.
- **Ollama**: The local LLM inference server running at `http://localhost:11434`.
- **SearXNG**: The self-hosted web search engine receiving the Reformulated_Query.
- **Pipeline**: The `VoicePipeline` class in `server/pipeline.py` that orchestrates STT,
  LLM, TTS, and search workers.
- **llm_worker**: The async worker method inside `Pipeline` that handles intent
  classification, context retrieval (RAG or search), prompt building, and LLM streaming.
- **Conversation_History**: The list of prior user/assistant turns maintained in
  `PipelineState.conversation_history`.
- **Japanese_Characters**: Unicode code points in the ranges U+3040–U+30FF (hiragana and
  katakana) and U+4E00–U+9FAF (CJK unified ideographs).

---

## Requirements

### Requirement 1: Query Extraction from Conversational Input

**User Story:** As a kiosk user, I want my conversational questions to produce relevant
web search results, so that I receive accurate and useful information even when I phrase
my question naturally.

#### Acceptance Criteria

1. WHEN the `llm_worker` classifies intent as `Intent.SEARCH`, THE `Reformulator` SHALL
   extract a concise English search query of 3 to 6 words from the Raw_Input before
   calling SearXNG.
2. THE `Reformulator` SHALL call the Ollama `/api/chat` endpoint with `stream` set to
   `false`, `temperature` set to `0`, and `num_predict` set to `32`.
3. THE `Reformulator` SHALL send only the latest Raw_Input string to Ollama; it SHALL NOT
   include Conversation_History, the main system prompt, or any prior search results.
4. THE `Reformulator` SHALL use the model identifier `qwen2.5:3b` for all reformulation
   calls.
5. WHEN the Ollama response is received, THE `Reformulator` SHALL strip leading and
   trailing whitespace from the returned content before returning the Reformulated_Query.

---

### Requirement 2: Japanese Language Detection and Translation

**User Story:** As a Japanese-speaking kiosk user, I want my Japanese questions to be
translated into English search queries, so that SearXNG returns high-quality results from
English-indexed content.

#### Acceptance Criteria

1. WHEN the Raw_Input contains one or more characters in the Unicode ranges U+3040–U+30FF
   or U+4E00–U+9FAF, THE `Reformulator` SHALL treat the input as Japanese and instruct
   Ollama to produce an English translation of the query intent.
2. THE `Reformulator` SHALL use a system prompt that explicitly instructs the model to
   output only a concise English web search query with no explanation, no punctuation at
   the end, no quotes, and one line only.
3. WHEN the Raw_Input contains no Japanese characters, THE `Reformulator` SHALL apply the
   same extraction logic without a language-specific translation instruction.

---

### Requirement 3: Fallback on Reformulator Failure

**User Story:** As a kiosk operator, I want the search pipeline to remain functional even
when the reformulation step fails, so that users always receive a search response rather
than an error.

#### Acceptance Criteria

1. IF the Ollama HTTP call raises any exception (network error, timeout, non-2xx status,
   JSON parse error, or any other exception), THEN THE `llm_worker` SHALL use the
   Raw_Input string as the SearXNG query without surfacing the error to the user.
2. THE `Reformulator` HTTP client SHALL enforce a 10-second total timeout on the Ollama
   call; IF the call exceeds 10 seconds, THEN THE `llm_worker` SHALL fall back to
   Raw_Input as described in criterion 1.
3. IF the fallback path is taken, THEN THE `Pipeline` SHALL log the exception at WARNING
   level and continue normal operation.

---

### Requirement 4: Pipeline Isolation — No Side Effects

**User Story:** As a developer, I want the reformulation step to be completely isolated
from the rest of the pipeline, so that adding it cannot break the main LLM call,
conversation history, streaming, or TTS.

#### Acceptance Criteria

1. THE `Reformulator` SHALL NOT modify `PipelineState.conversation_history` or append
   the Reformulated_Query to any history structure.
2. THE `Reformulator` SHALL NOT be visible to the user; the Reformulated_Query SHALL NOT
   be sent to the client via WebSocket.
3. THE `Reformulator` SHALL NOT modify the main LLM system prompt, the main LLM call
   parameters, or the streaming token pipeline.
4. THE `Reformulator` SHALL NOT modify the TTS pipeline, the STT pipeline, or any audio
   processing code.
5. WHEN the `Reformulator` is called, THE `llm_worker` SHALL pass only the
   `transcript.text` string; it SHALL NOT pass the WebSocket object, the config object,
   or any pipeline state.

---

### Requirement 5: HTTP Transport and Configuration

**User Story:** As a developer, I want the reformulator to use the existing HTTP client
library and a configurable Ollama URL, so that it integrates cleanly with the project's
dependencies and deployment configuration.

#### Acceptance Criteria

1. THE `Reformulator` SHALL use `httpx` (already present in `requirements.txt`) for the
   synchronous HTTP POST to the Ollama `/api/chat` endpoint.
2. THE `Reformulator` SHALL read the Ollama base URL from a module-level constant
   defaulting to `http://localhost:11434`; the constant SHALL be named `OLLAMA_BASE_URL`.
3. THE `Reformulator` SHALL read the model name from a module-level constant defaulting
   to `qwen2.5:3b`; the constant SHALL be named `REFORMULATOR_MODEL`.
4. THE `Reformulator` SHALL NOT load any new model into memory; it SHALL reuse the
   already-resident `qwen2.5:3b` model.

---

### Requirement 6: Module Structure and Integration Point

**User Story:** As a developer, I want the reformulator to live in a single, self-contained
module with a clear public API, so that it is easy to test, replace, or disable
independently of the rest of the pipeline.

#### Acceptance Criteria

1. THE `Reformulator` SHALL be implemented as a single Python module at
   `server/search/query_reformulator.py` with one public function:
   `extract_search_query(user_message: str) -> str`.
2. WHEN `extract_search_query` is called with a non-empty string, THE `Reformulator`
   SHALL return a non-empty string.
3. THE `llm_worker` SHALL call `extract_search_query(transcript.text)` inside a
   `try/except Exception` block and assign the result to a local variable used as the
   SearXNG query; the existing `searxng_search` call signature SHALL remain unchanged.
4. THE `Reformulator` module SHALL NOT import from `server.pipeline`, `server.llm`,
   `server.tts`, or `server.stt`; it SHALL only import from the Python standard library
   and `httpx`.

---

### Requirement 7: Anaphoric Query Resolution via Recent Conversation Context

**User Story:** As a kiosk user, I want the reformulator to understand messages that
refer to something mentioned earlier in the conversation (e.g. "Search about it please",
"Look that up", "調べてみて"), so that anaphoric queries produce a meaningful search
result instead of failing silently.

#### Acceptance Criteria

1. THE `Reformulator` SHALL accept an optional second parameter
   `recent_history: list[dict] | None = None` on `extract_search_query`, making the full
   signature `extract_search_query(user_message: str, recent_history: list[dict] | None = None) -> str`.
2. WHEN `recent_history` is provided and non-empty, THE `Reformulator` SHALL slice it to
   the last 6 elements (`recent_history[-6:]`) before use, regardless of the length
   supplied by the caller, enforcing a hard limit of 3 prior user/assistant pairs.
3. WHEN building the Ollama `/api/chat` request, THE `Reformulator` SHALL prepend the
   sliced history messages before the current user message in the `messages` array, so
   the model receives sufficient context to resolve anaphoric references such as "it",
   "that", "this topic", or "それ".
4. THE `Reformulator` SHALL NOT append to, mutate, or return `recent_history`; the
   parameter is consumed read-only and discarded after the Ollama request is built.
5. THE `Reformulator` SHALL NOT modify the system prompt when `recent_history` is
   provided; the existing system prompt SHALL remain unchanged.
6. IF `recent_history` is `None` or an empty list, THEN THE `Reformulator` SHALL behave
   identically to the pre-anaphora behaviour, with no regression in existing functionality.
7. THE `llm_worker` SHALL pass a slice of the existing `Conversation_History` as
   `recent_history`; it SHALL NOT create a new history store to satisfy this parameter.
8. WHEN `extract_search_query` is called with `recent_history`, THE `Reformulator` SHALL
   still return only a plain string (the Reformulated_Query); it SHALL NOT return or
   expose any part of `recent_history` to the caller.
