# Search Query Refactor — Implementation Plan & Coding Agent Prompt

---

## 1. Problem Summary

### Problem 1 — Japanese Query Quality
Raw Japanese user input sent directly to SearXNG returns low-quality results because most
indexed content and search engine optimisation is English-first. Japanese queries hit far
fewer indexed pages, and intent signals embedded in Japanese phrasing are lost on
Western-oriented ranking algorithms.

### Problem 2 — Conversational Input as Raw Query
The search layer receives the full conversational message from the user instead of an
extracted intent. This causes the search engine to match against filler words, politeness
markers, and irrelevant context rather than the actual information need.

---

## 2. Root Cause

There is no intermediate step between user input and SearXNG. The raw message string (or
its direct transcript from Whisper) is forwarded verbatim. The LLM that already has
query-extraction and translation capability is invoked only *after* search results are
returned, when it is too late.

---

## 3. The Fix — Query Reformulation Layer

Insert a **single, isolated, non-streaming LLM call** before the search request. This call:

1. Extracts a concise 3–6 word English search query from the user message.
2. Translates it if the detected language is Japanese (or any non-English language).

**Nothing else changes.** The main generation call, its prompt, its history, its streaming
pipeline, and the TTS pipeline remain completely untouched.

### Pipeline Before (Broken)

```
[User Input] ──────────────────────────────► [SearXNG] ──► [Main LLM (streaming)] ──► [TTS]
```

### Pipeline After (Fixed)

```
[User Input] ──► [Query Reformulator LLM call] ──► [SearXNG] ──► [Main LLM (streaming)] ──► [TTS]
                  (non-streaming, isolated,
                   ~100ms, reuses loaded model)
```

The reformulator is a **fire-and-forget synchronous call** that returns a single plain-text
string. It has no side effects on history, context, or streaming state.

---

## 4. Implementation Plan

### Step 1 — Create `query_reformulator.py` (new isolated module)

This module owns exactly one responsibility: given a raw user string, return a clean
English search query string. It must not import from or mutate anything in the main chat
pipeline.

```python
# query_reformulator.py

import re
import httpx  # or requests — whichever is already in the project

OLLAMA_BASE_URL = "http://localhost:11434"
REFORMULATOR_MODEL = "qwen2.5:3b"  # same model already loaded — zero extra VRAM

SYSTEM_PROMPT = """You are a search query extractor.
Given a user message in any language:
1. Identify the core information need.
2. Output ONLY a concise English web search query (3 to 6 words).
3. No explanation. No punctuation at the end. No quotes. One line only."""

def _is_japanese(text: str) -> bool:
    return bool(re.search(r'[\u3040-\u30FF\u4E00-\u9FAF]', text))

def extract_search_query(user_message: str) -> str:
    """
    Returns a clean English search query derived from user_message.
    Raises on network or model failure so the caller can fall back gracefully.
    """
    payload = {
        "model": REFORMULATOR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "stream": False,       # MUST be False — never stream this call
        "options": {
            "temperature": 0,  # deterministic output
            "num_predict": 32, # hard cap — query never needs more than 32 tokens
        },
    }
    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    query = response.json()["message"]["content"].strip()
    return query
```

### Step 2 — Wrap with Fallback in the Search Caller

In whatever module currently calls SearXNG, replace the direct use of `user_message` with
a wrapped call:

```python
# search_handler.py  (existing file — minimal edit)

from query_reformulator import extract_search_query

def get_search_results(user_message: str) -> list[dict]:
    try:
        search_query = extract_search_query(user_message)
    except Exception:
        # Graceful fallback: use raw input if reformulator fails
        search_query = user_message

    # Existing SearXNG call — unchanged
    return _call_searxng(search_query)
```

No other file changes. The main chat handler, history manager, and streaming loop never
see the reformulator.

### Step 3 — SearXNG Engine Tuning (config only, no code)

```yaml
# searxng/settings.yml — add / adjust engines block

engines:
  - name: google
    engine: google
    language: en-US          # keep English as primary
  - name: google_ja
    engine: google
    language: ja-JP          # secondary Japanese locale engine
    weight: 0.6
  - name: yahoo_japan
    engine: yahoo
    url: https://search.yahoo.co.jp/
    language: ja
    weight: 0.5
  - name: bing
    engine: bing
    language: en-US
```

This is a pure config change. Restart SearXNG; nothing in the app restarts.

---

## 5. What NOT To Do

These are the most dangerous mistakes — each one can silently break the current system.

| ❌ Do NOT | Why it breaks things |
|---|---|
| Inject the reformulated query into the conversation history | Poisons the LLM's understanding of what the user actually said. History must always contain the original user message. |
| Use `stream: true` for the reformulator call | The reformulator result must be a complete string before SearXNG is called. Streaming the reformulator adds complexity with zero benefit. |
| Pass the entire chat history to the reformulator | It only needs the latest user message. Sending history blows up context, increases latency, and risks leaking prior topics into the query. |
| Change the main generation system prompt | The main prompt is already tuned. This change lives entirely upstream of it. |
| Modify the TTS / audio pipeline | The reformulator output is never spoken. It is internal plumbing only. |
| Change how search results are injected into the main prompt | The results slot in exactly as before — only the query that fetched them has changed. |
| Use a different/larger model for reformulation | Qwen3b is already resident in VRAM. A second model would push you over the 6100 MB limit. |
| Add retry loops with back-off inside the reformulator | A hung reformulator will block the user response. Use a tight `timeout=10` and fall back immediately on any exception. |

---

## 6. Streaming Pipeline Safety

The streaming pipeline (`main LLM → token stream → TTS`) is downstream of search. The
reformulator inserts itself upstream of search. The two are separated by the SearXNG
call acting as a natural synchronisation barrier.

```
Reformulator call   ← synchronous, completes before search is called
        ↓
SearXNG call        ← synchronous, completes before main LLM is called
        ↓
Main LLM stream     ← streaming begins here, totally unaffected
        ↓
TTS pipeline        ← unaffected
```

As long as the reformulator is called before `_call_searxng()` and the result is just a
string, the streaming pipeline cannot be affected. The only risk is latency: the
reformulator adds ~150–300 ms. This is acceptable given the quality improvement and is
hidden within the existing search round-trip time.

---

## 7. Coding Agent Prompt

Paste this verbatim into your coding agent.

---

```
TASK: Insert a search query reformulation step into the existing chatbot pipeline.

CONTEXT:
- Stack: Python backend, Ollama (qwen2.5:3b), SearXNG (local), Faster-Whisper (STT), Kokoro (TTS)
- VRAM budget: ~600 MB free. Do NOT load any new model.
- The app currently passes raw user input directly to SearXNG. This must be replaced with
  a preprocessed English search query extracted by the already-loaded Ollama model.
- The main LLM generation call is streaming. Do NOT touch it.

DELIVERABLE:
Create one new file: `query_reformulator.py`
Make one minimal edit: in the existing search handler file, replace the raw user_message
passed to SearXNG with the output of `extract_search_query(user_message)`, wrapped in a
try/except that falls back to raw user_message on any failure.

RULES — follow these exactly:

1. `query_reformulator.py` must call Ollama's /api/chat endpoint with `stream: false`.
   Temperature must be 0. num_predict must be capped at 32 tokens.

2. The reformulator must receive ONLY the latest user message string. Do NOT pass chat
   history, system prompt, or search results to it.

3. The system prompt for the reformulator must instruct the model to output ONLY a
   concise 3–6 word English search query. One line. No quotes. No explanation.

4. The reformulator must detect Japanese characters (Unicode ranges \u3040-\u30FF and
   \u4E00-\u9FAF) and, if present, ensure the system prompt explicitly asks for an
   English translation of the query intent.

5. Do NOT modify:
   - The main LLM call or its system prompt
   - The conversation history / context management
   - The streaming response handler
   - The TTS pipeline
   - Any audio or STT code

6. The reformulated query string must NOT be added to conversation history or shown to
   the user. It is used only as the SearXNG search string.

7. Wrap the call to extract_search_query() in try/except Exception. On any failure,
   fall back to the raw user_message silently (no crash, no user-visible error).

8. Use httpx (preferred) or requests for the Ollama HTTP call. Timeout must be 10 seconds.

9. After making changes, list every file modified and confirm no streaming-related file
   was touched.

OUTPUT FORMAT:
- Full content of `query_reformulator.py`
- The specific diff (before/after lines) for the search handler file
- A one-line confirmation: "Streaming pipeline files modified: none"
```

---

## 8. Expected Outcome

| Metric | Before | After |
|---|---|---|
| Japanese query search quality | Low (raw JP text) | High (translated EN intent) |
| Conversational input search quality | Poor (filler words matched) | Good (3–6 word clean query) |
| VRAM usage | ~5500 MB | ~5500 MB (unchanged) |
| Streaming latency | baseline | +150–300 ms (search phase only) |
| Risk to existing pipeline | — | Near zero (isolated, fallback present) |