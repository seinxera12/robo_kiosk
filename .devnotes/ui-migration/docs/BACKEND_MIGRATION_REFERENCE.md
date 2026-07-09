# Backend Reference for Browser Frontend Migration

> **Purpose:** Single source of truth for building a browser frontend against this
> local-first voice chatbot backend, **without reading the backend source**.
>
> **Scope analyzed:** `server/`, `client/` (PyQt6 desktop client being replaced).
> **Method:** Every protocol/schema/state claim below is traced to the file and
> function that implements it. Claims are labeled **[Confirmed]** (cited),
> **[Recommendation]**, or **[Speculation]**.
>
> **Golden rule for the frontend agent:** The server is the source of truth for
> language, turn state, and interrupt handling. The browser client's job is
> narrow: capture mic audio in the exact PCM format the server expects, send
> control JSON, render streamed text, and play streamed WAV audio. Do **not**
> re-implement STT, VAD-gating semantics, or language detection on the client —
> though you **do** need client-side VAD to decide *when* to send audio (see §5).

---

## 1. Architecture Overview

### 1.1 What the system is

A **local-first, real-time bilingual (English/Japanese) voice kiosk assistant.**
A user speaks (or types); the server transcribes, classifies intent, retrieves
context (building knowledge base, or web search, or nothing), generates an LLM
response streamed token-by-token, synthesizes speech sentence-by-sentence, and
streams audio back — all over **one WebSocket connection**. Barge-in (interrupt
by speaking while the assistant talks) is supported.

### 1.2 Runtime shape (why it looks like this)

**[Confirmed]** The server (`server/main.py`) is a **FastAPI** app with exactly
two HTTP surfaces:
- `GET /health` — health/status JSON.
- `WS /ws` — the entire interactive protocol.

All heavy models are **pre-loaded once at process startup** in a FastAPI
`lifespan` handler (`server/main.py:39-77`): Whisper STT, the LLM fallback chain,
the ChromaDB RAG store, and the TTS router. They are stored in a module-level
`app_state` dict and **shared across all WebSocket connections**. This is why a
new WebSocket connects instantly — no per-connection model load. (Consequence for
migration: models are process-global; per-connection state lives only in the
`VoicePipeline`/`PipelineState` created per socket.)

**[Confirmed]** Each WebSocket connection creates **one** `VoicePipeline`
(`server/main.py:174-184`, `server/pipeline.py:72`). That pipeline spins up
**five concurrent asyncio worker coroutines** (`server/pipeline.py:181-188`):

```
websocket_receiver ─► audio_input(STT) ─► llm_worker ─► tts_worker ─► audio_output_worker
        │  (also handles control JSON + interrupts)      (per-sentence async synth tasks)
        └───────────────────────────────────────────────────────────────────► WebSocket out
```

Data flows stage-to-stage through four `asyncio.Queue`s (`server/pipeline.py:54-57`):
`audio_input → transcript → token → audio_output`. Workers coordinate via a
single `asyncio.Event` (`interrupt_event`) for barge-in.

### 1.3 Dependency graph (server)

```
main.py (FastAPI, lifespan, /health, /ws)
 └─ pipeline.py  VoicePipeline (orchestrator, protocol handler)
     ├─ stt/whisper_stt.py         WhisperSTT (faster-whisper)
     ├─ llm/fallback_chain.py      LLMFallbackChain
     │    ├─ llm/vllm_backend.py   VLLMBackend (OpenAI-compatible)
     │    ├─ llm/ollama_backend.py OllamaBackend (OpenAI-compatible)
     │    └─ llm/grok_backend.py   GrokBackend (added only if GROK_API_KEY set)
     ├─ llm/intent_classifier.py   IntentClassifier (keyword + embedding tiers)
     ├─ llm/prompt_builder.py      build_messages() (intent-specific system prompts)
     ├─ rag/chroma_store.py        BuildingKB (ChromaDB) ─ rag/embedder.py (e5-large)
     ├─ search/searxng_client.py   searxng_search() ─ search/query_reformulator.py
     ├─ lang/detector.py           detect_language() (Whisper conf + Unicode fallback)
     └─ tts/tts_router.py          TTSRouter
          ├─ tts/kokoro_tts.py     KokoroTTS (en) / KokoroJapaneseTTS (ja secondary)
          └─ tts/kokoclone_tts.py  KokoCloneTTS (ja primary, HTTP microservice)
```

**[Confirmed]** `tts/opus_encoder.py` exists but is a **placeholder passthrough**
(`OpusEncoder.encode_frame` returns input unchanged, `server/tts/opus_encoder.py:48-61`).
**It is not wired into the pipeline.** Despite docstrings mentioning "Opus," the
wire audio format is **WAV** (see §5).

### 1.4 Service boundaries (external processes)

| Service | Role | Transport | In-process? |
|---|---|---|---|
| FastAPI voice-server | Orchestration, STT, RAG, prompt, TTS routing | — | this process |
| vLLM | Primary LLM (OpenAI API) | HTTP `:8001/v1` | separate (often disabled) |
| Ollama | Fallback LLM (OpenAI API) | HTTP `:11434/v1` | separate container |
| Grok API | Last-resort cloud LLM | HTTPS | external, optional |
| SearXNG | Web search | HTTP `:8080` (`:8081` host) | separate container |
| KokoClone | Japanese voice-clone TTS | HTTP `:5003` | separate microservice |
| ChromaDB | RAG vector store | embedded (PersistentClient) | in-process (file-backed) |
| Whisper / Kokoro / e5 | STT / TTS / embeddings | in-process models | this process |

---

## 2. Module Reference

Only modules that affect frontend-visible behavior/contract/state are documented.
Trivial helpers are skipped per instruction.

### 2.1 `server/pipeline.py` — VoicePipeline (the contract owner)
- **Purpose:** Owns the WebSocket protocol and per-connection state. Everything
  the frontend sees on the wire is produced/consumed here.
- **Entry point:** `run()` (`pipeline.py:152`) — gathers the five workers.
- **Consumers:** `server/main.py` websocket endpoint.
- **Shared state:** `PipelineState` (`pipeline.py:22-69`) — the four queues,
  `interrupt_event`, `conversation_history` (max 20 messages = 10 turns),
  `status` (`idle`/`listening`/`thinking`/`speaking`), `current_turn` (holds
  detected `lang`). Also `self._synthesis_tasks` (set of in-flight per-sentence
  TTS tasks) used to cancel synthesis on interrupt.
- **Async/threading:** Pure asyncio; STT and TTS model inference are offloaded to
  thread-pool executors inside their modules so the event loop never blocks.
- **Lifecycle:** Created on WS accept, `run()` blocks until disconnect/error,
  `cleanup()` clears history + drains queues (`pipeline.py:1064`).

### 2.2 `server/stt/whisper_stt.py` — WhisperSTT
- **Purpose:** Transcribe PCM16 → text + detected language.
- **Input contract:** raw **PCM16, 16 kHz, mono** bytes (`transcribe()`).
  Internally `np.frombuffer(dtype=np.int16) / 32768.0`.
- **Guards:** rejects clips `< 8000 samples` (0.5 s) → empty result
  (`whisper_stt.py:124`). Pipeline also rejects `< 16000 bytes` upstream.
- **Output:** `TranscriptionResult{text, language∈{"en","ja"}, confidence, duration_ms}`.
- **Decoding:** greedy (`beam_size=1`), `vad_filter=False`,
  `condition_on_previous_text=False` for low latency (`whisper_stt.py:184`).
- **Config:** `stt_model` (default `large-v3`), `stt_device` (default `cuda`,
  auto-falls back to CPU/int8), `stt_compute_type` (default `float16`).

### 2.3 `server/llm/fallback_chain.py` — LLMFallbackChain
- **Order:** vLLM → Ollama → Grok (`fallback_chain.py:34-47`). vLLM skipped if
  `VLLM_MODEL_NAME == "disabled"`; Grok added only if `GROK_API_KEY` set.
- **Behavior:** health-checks each backend (`ping()` = models.list, 5 s timeout)
  before use; caches last-successful index; streams tokens; raises
  `RuntimeError("All LLM backends failed")` if none work.
- **Backend params:** `max_tokens=512, temperature=0.3, stream=True`
  (`vllm_backend.py:59`, `ollama_backend.py:62`). Tools are accepted but **not
  emitted** to the client (tool-call handling is a TODO).

### 2.4 `server/llm/intent_classifier.py` — IntentClassifier
- **Purpose:** Route each query to `BUILDING` / `SEARCH` / `GENERAL`.
- **Tiers:** (0) conversational guard for greetings → GENERAL; (1) keyword rules
  (EN+JA keyword sets); (1b) history carry-over for follow-ups; (2) embedding
  cosine similarity vs. pre-computed anchors (reuses the RAG e5 embedder).
- **Latency target:** <15 ms; no extra LLM/network call.
- **Frontend relevance:** none directly — but it explains *why* the same text can
  produce a building answer, a web-searched answer, or plain chat.

### 2.5 `server/llm/prompt_builder.py` — build_messages()
- Builds an OpenAI-style `messages` list with an intent-specific system prompt,
  trimmed history (budget 3000 input tokens, ~4 chars/token), a language rule
  appended to the system message, **and a language tag prepended to the user
  message** (`[Reply in English]` / `[日本語で回答してください]`).
- **Cross-language history filtering:** history pairs whose stored `lang` doesn't
  match the current turn are dropped (`prompt_builder.py:138-184`).
- **Frontend relevance:** the boilerplate patterns are stripped server-side before
  text is sent to the client and before TTS (`pipeline.py:563-578, 714-726`), so
  the browser should never see `[Reply in English]` etc. If it does, that's a bug.

### 2.6 `server/rag/chroma_store.py` — BuildingKB
- `retrieve(query, lang, n=3)` embeds the query (e5-large, 1024-dim), queries
  Chroma with a `where={"lang": lang}` filter, returns concatenated top-N chunk
  text (or `""` on empty collection / any error — RAG failures are non-fatal).

### 2.7 `server/tts/tts_router.py` — TTSRouter
- **English →** Kokoro-82M (in-process). **Japanese →** KokoClone (HTTP
  microservice, only if enabled + ref audio exists) → Kokoro Japanese fallback.
- `synthesize_stream(text, lang)` yields **WAV bytes chunks**; Japanese engines
  are tried in order and the router transparently falls back if one yields zero
  chunks.
- **Output format (all engines):** **WAV file bytes, 24 kHz, mono, PCM16**
  (`kokoro_tts.py:14-15, 55, 98`; KokoClone `/health` reports `sample_rate: 24000`).

### 2.8 Client modules (being replaced — read for the contract they encode)
- `client/ws_client.py` — WebSocket wrapper (auto-reconnect, exp backoff).
- `client/audio_capture.py` — mic → 16 kHz mono PCM16, 32 ms frames (512 samples).
- `client/vad.py` — Silero VAD; emits `speech_start`/`speech_end` with buffered audio.
- `client/audio_playback.py` — decodes WAV chunks, plays via sounddevice.
- `client/ui/app.py` — PyQt6 window + `PipelineWorker` (the state machine you must
  reproduce in the browser). **This is the most important client file to mirror.**

---

## 3. Frontend Integration Guide ⭐ (exhaustive — build from this)

### 3.0 The one connection

Everything happens over a single WebSocket. There is **no auth**, **no REST for
chat**, **no session token**. The URL is `ws://<host>:8765/ws` (default; see §9).

- **Server → client** messages are either **JSON text frames** (events) or
  **binary frames** (WAV audio bytes).
- **Client → server** messages are either **JSON text frames** (control) or
  **binary frames** (PCM16 mic audio).

The message *kind* is discriminated purely by frame type (text vs binary), then
by the JSON `type` field. **[Confirmed]** `client/ws_client.py:113-139`,
`pipeline.py:847-891`.

### 3.1 CORS / connection

**[Confirmed]** CORS is wide open: `allow_origins=["*"]`, all methods/headers,
credentials allowed (`main.py:90-96`). A browser can connect from any origin.
WebSocket itself is not subject to CORS, so this only matters for the `/health`
fetch.

### 3.2 Required call ordering & state preconditions

1. **Connect** to `ws://host:8765/ws`. Server calls `accept()` immediately.
2. **Send** `{"type":"session_start", "kiosk_id":"...", "kiosk_location":"..."}`.
   Server resets `current_turn` and replies `{"type":"session_ack","status":"ready"}`.
   **[Confirmed]** `pipeline.py:899-905`, client sends it first thing
   (`client/main.py:53`, `ui/app.py:80`).
   - *Is it strictly required?* The server also accepts a bare `text_input` or
     audio without a prior `session_start` (each control message is handled
     independently). But `session_ack` is your readiness signal — **send it and
     wait for the ack** before enabling input. **[Recommendation]**
3. **Then** either send audio (binary) or `text_input` (JSON) any number of times.
4. Server streams back `transcript` (voice only) → `llm_text_chunk`* → final
   `llm_text_chunk{final:true}`, interleaved with binary WAV audio frames.

### 3.3 Client → server messages

#### 3.3.1 `session_start` (JSON)
```json
{ "type": "session_start", "kiosk_id": "kiosk-01", "kiosk_location": "Floor 1 Lobby" }
```
Response: `{ "type": "session_ack", "status": "ready" }`. `kiosk_id`/`kiosk_location`
are logged and `kiosk_location` feeds the system prompt's "Kiosk Location". Defaults
`"unknown"` if omitted (`pipeline.py:900-901`).

#### 3.3.2 `text_input` (JSON) — typed query path
```json
{ "type": "text_input", "text": "Where is the cafeteria?", "lang": "auto" }
```
- `lang` may be `"en"`, `"ja"`, or `"auto"`. **The server always re-detects
  language from the text** and only honors a client `lang` if it's `en`/`ja`,
  the text is ≥4 chars, AND server detection agrees; otherwise server wins
  (`pipeline.py:906-928`). **→ Frontend recommendation: always send
  `"lang":"auto"`** and let the server decide. **[Confirmed]**
- Sending `text_input` **first calls `handle_interrupt(notify_client=False)`**
  (drains queues, cancels in-flight TTS) so a new typed query cleanly preempts
  any in-progress response (`pipeline.py:932-941`).
- The transcript is **not** echoed back for typed input (the server pushes the
  text straight into the transcript queue). The PyQt client shows the user's own
  typed text locally and immediately (`ui/app.py:342`). **→ Do the same: render
  the user's typed message locally; don't expect a `transcript` event for it.**

#### 3.3.3 `interrupt` (JSON) — explicit barge-in
```json
{ "type": "interrupt" }
```
Triggers `handle_interrupt(notify_client=True)`: cancels TTS synthesis, drains all
queues, resets to `listening`, and replies with a `status` event
(`pipeline.py:897-898, 945-1029`). **[Confirmed]**

#### 3.3.4 Binary audio frame (mic) — voice path
- **Format: raw PCM16, 16 kHz, mono, little-endian.** No header, no container,
  no length prefix. Just Int16 samples as bytes.
- **[Confirmed]** Client sends `event.audio_buffer` bytes directly
  (`client/main.py:91`, `ui/app.py:198`); server reads `message["bytes"]` and puts
  it on `audio_input` (`pipeline.py:860-870`).
- **What to send:** one **complete utterance** (the whole speech segment between
  speech-start and speech-end), **not** individual 32 ms frames. The client
  accumulates frames in its VAD until `speech_end`, then sends the buffered
  utterance as one binary message (`client/vad.py:206-220`, `client/main.py:87-91`).
- **Minimum length:** the server drops audio `< 16000 bytes` (= 8000 samples =
  0.5 s) without transcribing (`pipeline.py:242-248`). Send at least 0.5 s.
- **Implicit interrupt:** when a binary audio frame arrives *while the pipeline is
  speaking/has queued audio/tokens*, the server auto-interrupts the current
  response before enqueuing the new audio (barge-in) — but **only** then, to avoid
  clearing turn state on every frame (`pipeline.py:862-870`). **[Confirmed]**

  > ⚠️ **Frame-size caveat for the browser (§12):** the implicit-interrupt logic
  > was tuned for *whole-utterance* sends. If a browser streams many small binary
  > frames mid-utterance, each frame that arrives during "speaking" fires an
  > interrupt. **Mirror the desktop client: send one binary message per complete
  > utterance.**

#### 3.3.5 `session_reset` (JSON) — ⚠️ sent by client, NOT handled by server
The PyQt "Clear Session" button sends `{"type":"session_reset"}`
(`ui/app.py:345-351`), but the server's `handle_control_message` has **no branch
for it** — it falls to the `else` and logs `Unknown control message type`
(`pipeline.py:942-943`). **[Confirmed bug/gap]** So server-side conversation
history is **not** cleared by this message. See §11/§12 for the migration action
(add a real `session_reset` handler, or clear history via reconnect).

### 3.4 Server → client messages (events)

All are JSON text frames unless noted.

| `type` | Fields | When | Frontend action |
|---|---|---|---|
| `session_ack` | `status:"ready"` | after `session_start` | mark connection ready, enable input |
| `transcript` | `text`, `lang`, `final:true` | after STT of a voice utterance (voice only) | render user bubble with `text`; set status "thinking" |
| `llm_text_chunk` | `text`, `final:false` | per LLM token | append `text` to current assistant bubble |
| `llm_text_chunk` | `text:""`, `final:true` | end of response (or on interrupt if was active) | close bubble; set status "listening" |
| `status` | `state` (e.g. `"listening"`) | after an interrupt with `notify_client=true` | set UI status |
| *(binary frame)* | WAV bytes | per synthesized sentence chunk | decode + play (see §5) |

**Exact payload shapes [Confirmed]:**
```json
{ "type": "session_ack", "status": "ready" }
{ "type": "transcript", "text": "カフェはどこですか", "lang": "ja", "final": true }
{ "type": "llm_text_chunk", "text": "The cafeteria ", "final": false }
{ "type": "llm_text_chunk", "text": "", "final": true }
{ "type": "status", "state": "listening" }
```
Sources: `pipeline.py:268-273` (transcript), `520-524` & `538` (chunks),
`905` (ack), `1020-1023` (status).

**Token granularity:** `text` is a raw model token/delta — often a word fragment,
sometimes with leading/trailing spaces. Concatenate verbatim; do **not** insert
spaces. The final chunk always has `text:""` and `final:true`. **[Confirmed]**

### 3.5 Streaming, framing, end-of-stream

- **Text stream:** N × `llm_text_chunk{final:false}` then exactly one
  `{final:true, text:""}`. That terminator is your "response complete" signal.
- **Audio stream:** independent of the text stream. TTS runs behind the text —
  each completed sentence produces one or more binary WAV frames. **Each frame is
  a complete standalone WAV file** (RIFF header + PCM16 @ 24 kHz), not a slice of a
  larger stream. Play them in arrival order.
- **Audio chunking on the wire:** the server splits each WAV blob into ≤64 KB
  binary WebSocket frames to stay under client `max_size` (`pipeline.py:826-831`).
  **⚠️ This means a single logical WAV file may arrive as multiple binary frames.**
  A 64 KB slice is *not* independently decodable. See §5.3 for how the desktop
  client gets away with it and what the browser must do differently.
- **No explicit end-of-audio signal.** There is no "audio done" event. The
  `llm_text_chunk{final:true}` marks text completion; audio simply stops arriving
  once the last sentence is synthesized. **[Confirmed]** (§12 flags this.)

### 3.6 Cancellation / interrupt (frontend responsibilities)

To barge-in (user starts speaking, or types, while assistant is talking):
- **Voice:** just send the new utterance's binary audio — the server auto-interrupts
  (§3.3.4). Also **stop local playback immediately** (the desktop client calls
  `playback.stop()` on manual-speak activation, `ui/app.py:255-257`).
- **Typed:** send `text_input`; server interrupts internally. Client also stops
  playback locally (`ui/app.py:332-334`).
- **Explicit:** send `{"type":"interrupt"}` and stop local playback.

On interrupt the server sends `llm_text_chunk{final:true}` (if it was
speaking/thinking) so your bubble closes cleanly (`pipeline.py:1002-1006`), plus a
`status` event if `notify_client` was true.

### 3.7 Error responses & status codes

- **`/health`:** always HTTP **200** with a JSON status body (see §4.1). It does
  not return non-200 on degradation; inspect the body.
- **WebSocket:** on an unhandled server exception the socket is closed with
  **code 1011** and the exception string as reason (`main.py:189-194`). Normal
  disconnects are clean. There are **no application-level error events** — the
  server logs errors and workers "continue processing despite errors"
  (`pipeline.py:284-286` etc.), so a failed turn may simply produce no output.
- **LLM total failure** raises `RuntimeError` inside `llm_worker`, which is caught
  and logged; the turn yields no tokens and no final chunk. **→ Frontend needs a
  client-side timeout** to recover a UI stuck in "thinking" (the desktop client
  has no such timeout — a real gap; §12). **[Recommendation]**

### 3.8 Connection lifecycle: reconnect / timeout / retry

- **Desktop client behavior [Confirmed]** (`client/ws_client.py`): `connect()`
  with `ping_interval=20, ping_timeout=10`; auto-reconnect with exponential
  backoff 1 s → 30 s cap; reconnect on send failure or `ConnectionClosed`.
- **Server-side keepalive:** FastAPI/uvicorn default WS ping. No idle timeout is
  set server-side beyond the framework default.
- **On reconnect, server state is fresh:** a new `VoicePipeline` with empty
  history is created (`cleanup()` cleared the old one on disconnect,
  `pipeline.py:1082-1085`). **→ Reconnect = new session.** Re-send `session_start`.
- **Browser guidance [Recommendation]:** use the standard `WebSocket` API with
  `binaryType = "arraybuffer"`; implement your own backoff reconnect; on reopen,
  re-send `session_start`.

### 3.9 Hidden assumptions the PyQt client makes (a browser MUST replicate)

1. **Client does its own VAD and only sends complete utterances.** The server has
   no server-side VAD on the live mic stream; it expects each binary message to be
   a full, ≥0.5 s utterance. A browser must run VAD (or push-to-talk) client-side.
   **[Confirmed]** (`client/vad.py`, `client/main.py:85-91`).
2. **Mic audio must be exactly 16 kHz / mono / PCM16.** Browsers capture at
   44.1/48 kHz float — you MUST resample to 16 kHz and convert to Int16.
   **[Confirmed]** (`audio_capture.py:44-46`, `whisper_stt.py:90-95`).
3. **Playback audio is 24 kHz WAV** — different rate from capture. Decode the WAV
   header per chunk; don't assume 16 kHz. **[Confirmed]** (`kokoro_tts.py:98`,
   `audio_playback.py:150-160`).
4. **The user's own typed text is rendered locally**, not echoed by the server
   (§3.3.2).
5. **`_response_started` gating:** the client opens a new assistant bubble on the
   *first non-empty* `llm_text_chunk`, and closes it on `final:true` **only if a
   bubble was opened** — to ignore spurious `final:true` from idle-state interrupts
   (`ui/app.py:124-139`). Replicate this or you'll get empty/duplicate bubbles.
6. **Language is server-authoritative.** Never hardcode `en`/`ja`; send `"auto"`.

---

## 4. API Reference

### 4.1 `GET /health` (REST)
- **Producer:** `main.py:99-162`. **Consumer:** Docker healthcheck / monitoring / a
  browser status page.
- **Auth:** none. **Status:** always 200.
- **Response body (fields present depend on what's initialized):**
```json
{
  "status": "healthy",
  "service": "voice-kiosk-chatbot",
  "version": "1.0.0",
  "config": { "building_name": "Office Building", "stt_model": "large-v3" },
  "tts": {
    "kokoro_en": "ready|not_loaded|not_initialized|error: ...",
    "kokoclone_ja": "ready|unavailable|not_initialized|error: ...",
    "kokoro_ja": "ready|not_loaded|not_initialized|error: ..."
  }
}
```
> Note: health check port is **8000** per Docker/main, while the WS port is
> **8765** (config default; §9). In docker-compose both are exposed.

### 4.2 `WS /ws` — message catalog

**Client → server**

| Frame | `type` | Schema | Effect |
|---|---|---|---|
| text | `session_start` | `{kiosk_id?, kiosk_location?}` | resets turn; returns `session_ack` |
| text | `text_input` | `{text, lang: "en"\|"ja"\|"auto"}` | interrupt+enqueue transcript; generate response |
| text | `interrupt` | `{}` | barge-in: cancel+drain, reset, send `status` |
| text | `session_reset` | `{}` | **⚠️ NOT handled — logged as unknown** |
| binary | — | PCM16 16 kHz mono bytes (≥16000 bytes) | (implicit interrupt if speaking)+enqueue for STT |

**Server → client**

| Frame | `type` | Schema | Producer |
|---|---|---|---|
| text | `session_ack` | `{status:"ready"}` | `pipeline.py:905` |
| text | `transcript` | `{text, lang, final:true}` | `pipeline.py:268` |
| text | `llm_text_chunk` | `{text, final:bool}` | `pipeline.py:520,538,1004` |
| text | `status` | `{state:string}` | `pipeline.py:1020` |
| binary | — | WAV bytes (24 kHz mono PCM16), ≤64 KB frames | `pipeline.py:830-831` |

**Unknown/unlisted types:** any other `type` is logged and ignored
(`pipeline.py:942-943`). There are no "official vs internal" hidden events beyond
this table — the catalog above is complete.

---

## 5. Audio Pipeline (mic → wire → playback)

### 5.1 Capture (browser must produce this)
- **Desktop [Confirmed]:** `sounddevice.InputStream`, 16 kHz, mono, float32,
  512-sample (32 ms) blocks (`audio_capture.py:44-63`). Float is converted to
  Int16 (`indata * 32767`) → PCM16 bytes.
- **Browser equivalent [Recommendation]:** `getUserMedia({audio})` →
  `AudioContext` (or `AudioWorklet`) → **resample to 16 kHz** → convert Float32
  `[-1,1]` to Int16 (`Math.max(-1,Math.min(1,x))*32767`) → accumulate into a buffer.

### 5.2 VAD & segmentation (client-side, required)
- **Desktop [Confirmed]:** Silero VAD (`client/vad.py`), threshold 0.3,
  min-speech 200 ms, min-silence 800 ms, with a rolling ~300 ms **pre-speech
  buffer** so the onset isn't clipped (`vad.py:81-84,175-185`). On `speech_end`
  the full buffered utterance (pre-speech + speech) is emitted and sent.
- **Manual "Speak" mode:** VAD is reset, a 15 s timeout is armed, and on Stop the
  buffer is flushed even mid-speech (`ui/app.py:229-318`, `vad.py:103-123`).
- **Browser equivalent [Recommendation]:** either (a) push-to-talk (simplest —
  record between button down/up, send on release), or (b) a JS VAD
  (`@ricky0123/vad-web`, which wraps Silero) to auto-detect end-of-speech. Include
  a small pre-roll. Enforce the ≥0.5 s minimum before sending.

### 5.3 Transport & playback (the tricky part)
- **Server → client:** each synthesized sentence = one or more binary WS frames.
  Each *logical* unit is a **complete WAV file** (RIFF/`WAVE`, PCM16, 24 kHz mono),
  but the server slices blobs >64 KB into multiple ≤64 KB frames
  (`pipeline.py:826-831`). **[Confirmed]**
- **How the desktop client decodes [Confirmed]:** `AudioPlayback.queue_audio` runs
  `wave.open()` on **each received frame**; if it isn't a valid WAV it falls back
  to treating the bytes as raw PCM at 24 kHz (`audio_playback.py:63-76,150-160`).
  It opens/reopens a `sounddevice.OutputStream` at the WAV's declared rate and
  plays in 20 ms sub-frames so `stop()` can abort within ~20 ms
  (`audio_playback.py:182-210`).

  > ⚠️ **This is fragile and the #1 browser migration hazard.** Because most TTS
  > sentences are < 64 KB, each frame usually *is* a full WAV and decodes fine. But
  > when a sentence exceeds 64 KB, the trailing frames are raw PCM slices with no
  > header — the desktop client's "raw PCM @ 24 kHz" fallback happens to play them
  > correctly *only because* the rate matches. A browser using `decodeAudioData`
  > (which requires a full valid container) will **fail on the non-first slices.**

- **Browser recommendation [Recommendation]:** Do **not** rely on `decodeAudioData`
  per frame. Instead, treat the binary stream as **24 kHz / mono / PCM16** and
  build a small player that:
  1. Reassembles/normalizes: strip the 44-byte WAV header if the frame starts with
     `RIFF`; otherwise treat the whole frame as raw PCM16.
  2. Feeds Int16→Float32 samples into a Web Audio `AudioWorklet`/ScriptProcessor
     ring buffer at a fixed 24 kHz output, or schedules `AudioBufferSourceNode`s
     back-to-back.
  3. Supports instant **flush/stop** for barge-in (clear the queue, stop the
     source).
  Alternatively, request a backend change to send **one WAV per sentence without
  the 64 KB split**, or add an explicit per-sentence framing/length prefix (§11).

### 5.4 Barge-in end-to-end
User speaks over TTS → browser stops playback + sends new utterance → server sees
audio while `status=="speaking"` → `handle_interrupt` cancels synthesis tasks,
drains `audio_output`, sends `llm_text_chunk{final:true}` → new turn proceeds. The
critical server fix (`pipeline.py:979-991`) is that it **cancels in-flight
synthesis tasks and awaits them** so no stale audio resumes after the interrupt.
The browser must correspondingly **drop any already-queued audio frames**.

---

## 6. AI Pipeline (conversation lifecycle)

1. **Transcript in** (from STT, or injected from `text_input`).
2. **Intent classification** → BUILDING / SEARCH / GENERAL (§2.4).
3. **Context retrieval** by intent:
   - BUILDING (+`use_rag`): Chroma top-3 chunks filtered by `lang`.
   - SEARCH: `extract_search_query()` reformulates → SearXNG (3 results, lang-mapped
     `en-US`/`ja-JP`) → formatted context; on empty/exception → **fall back to
     GENERAL** (`pipeline.py:444-453`).
   - GENERAL: no external context.
4. **Prompt build** (`build_messages`) with intent-specific system prompt,
   language rules, trimmed+language-filtered history, and a per-message language tag.
5. **LLM stream** via fallback chain; each token is (a) pushed to the `token` queue
   for TTS and (b) sent to client as `llm_text_chunk`.
6. **Response assembly:** full text collected; boilerplate stripped; language of
   the response re-detected; the `{user, assistant}` pair appended to history
   (capped at 20 messages). A `None` sentinel is pushed to the token queue to flush
   TTS (`pipeline.py:556`).
7. **TTS handoff:** `tts_worker` buffers tokens until a sentence boundary
   (`.?!。？！…`; min length 8 en / 2 ja), strips boilerplate, then spawns an async
   task that streams WAV chunks into `audio_output` (§5).

**Frontend relevance:** all of this is invisible except its outputs (`transcript`,
`llm_text_chunk`, audio). You cannot influence intent/routing from the client
except via the text you send.

---

## 7. End-to-End Data Flows

**Text request:**
`text_input JSON` → server re-detects lang → interrupt/drain → transcript queue →
intent → context → prompt → LLM stream → `llm_text_chunk`* + `{final:true}` →
(parallel) sentences → WAV frames. Client renders local user bubble + streamed
assistant text + plays audio.

**Voice request:**
mic PCM16 frames → *client VAD* → one binary utterance → server STT (PCM16→text) →
`transcript` event → [same as text from "intent" on]. Client shows transcript
bubble from the event.

**Interrupt:**
new audio (while speaking) OR `text_input` OR `interrupt` → cancel synth tasks +
drain 4 queues → `llm_text_chunk{final:true}` (if was active) → optional `status` →
`listening`. Client stops playback, closes bubble.

**Reconnect:**
socket drop → server `cleanup()` (history cleared, queues drained) → client
backoff reconnect → new `VoicePipeline` → client re-sends `session_start` → `ack`.

**Search/RAG:** see §6 step 3. **STT/TTS transforms:** PCM16@16k → text (STT);
text → WAV@24k (TTS).

**Ownership/format transforms summary:**
```
mic float32@48k → [client] Int16@16k PCM → [wire binary] → [server] np.int16/32768 float
  → Whisper → text → LLM tokens → [wire JSON] → [client] text bubble
text → TTS float32@24k → [server] WAV PCM16@24k bytes → ≤64KB [wire binary]
  → [client] WAV/PCM decode → OutputStream@24k
```

---

## 8. State Management

**Server, per connection** (`PipelineState`, `pipeline.py:22-69`):
- `status` ∈ {`idle`,`listening`,`thinking`,`speaking`} — advisory; drives the
  implicit-interrupt guard and the `status` event.
- `current_turn` — `{lang}` for the active turn; used to pick the TTS engine.
  Reset to `None` on interrupt.
- `conversation_history` — list of `{role, content, lang}`, capped at 20 messages;
  cleared on disconnect and (intended) on `session_reset` (currently not — §3.3.5).
- Four `asyncio.Queue`s + one `interrupt_event` + `_synthesis_tasks` set.
- **Concurrency primitives:** interrupt is a set/clear `asyncio.Event`; workers
  poll it each loop and `sleep(0.1)` while set. Interrupt handling cancels+awaits
  synthesis tasks then drains queues. No locks (single-threaded event loop; model
  inference offloaded to executors).

**Client state you must reproduce** (from `ui/app.py` `PipelineWorker`):
- `listening_enabled` (always-listen toggle) vs `_manual_speak_active`
  (push-to-talk) — gates whether VAD events are acted on.
- `_response_started` — bubble open/close gating (§3.9.5).
- `_speak_timeout_task` — 15 s manual-speak timeout.
- Local playback stop on barge-in / new input.

---

## 9. Services & Configuration

### 9.1 Server config (`server/config.py`, all via env)
| Env var | Default | Meaning |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | bind host |
| `SERVER_PORT` | `8765` | **WebSocket port** (health via 8000 in Docker) |
| `VLLM_BASE_URL` | `http://localhost:8000` | vLLM OpenAI base; set `VLLM_MODEL_NAME=disabled` to skip |
| `VLLM_MODEL_NAME` | `Qwen/Qwen2.5-7B-Instruct-AWQ` | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | fallback LLM |
| `OLLAMA_MODEL_NAME` | `qwen2.5:7b-instruct` | |
| `GROK_API_KEY` | unset | enables Grok fallback if set |
| `STT_MODEL` / `STT_DEVICE` / `STT_COMPUTE_TYPE` | `large-v3` / `cuda` / `float16` | Whisper |
| `CHROMADB_PATH` | `/chroma` | RAG store path |
| `BUILDING_NAME` | `Office Building` | system-prompt building name |
| `USE_RAG` | `true` | disable RAG retrieval entirely |
| `SEARXNG_URL` | `http://searxng:8080` | web search |
| `KOKORO_VOICE`/`_SPEED`/`_DEVICE`/`_LANG` | `af_heart`/`1.0`/`cpu`/`a` | English TTS |
| `KOKORO_JP_VOICE` / `KOKORO_JP_ENABLED` | `jf_alpha` / `true` | Japanese fallback TTS |
| `KOKOCLONE_URL` / `KOKOCLONE_REF_AUDIO` / `KOKOCLONE_ENABLED` | `:5003` / unset / `true` | Japanese primary TTS (needs ref audio file to activate) |

### 9.2 Client config (`client/config.py`)
| Env var | Default |
|---|---|
| `SERVER_WS_URL` | `ws://localhost:8765/ws` |
| `KIOSK_ID` | `kiosk-01` |
| `KIOSK_LOCATION` | `Floor 1 Lobby` |

**→ Browser equivalent:** expose `SERVER_WS_URL` (or derive from
`window.location`), `kiosk_id`, `kiosk_location` as build-time/runtime config.

### 9.3 Service start/stop, ports, health (from `docker-compose.yml`)
- `voice-server`: ports 8765 (WS) + 8000 (health); GPU reserved; healthcheck curls
  `:8000/health`; depends on ollama/voicevox/searxng. (Note: compose still
  references a `voicevox` dependency and `TTS_JP_URL`/`TTS_EN_ENGINE=cosyvoice`
  env vars that the **current** code does not use — legacy; the code uses
  Kokoro/KokoClone. **[Confirmed drift]**)
- `ollama`: `:11434`, GPU-optional. `searxng`: host `:8081`→container `:8080`.
- `vllm` service is **commented out** — so by default the LLM path is
  Ollama (unless a vLLM is run separately). **[Confirmed]**
- KokoClone microservice (`kokoclone/`) runs separately on `:5003` in its own venv.

### 9.4 Latency / warm-up [Confirmed facts + Speculation]
- Models pre-loaded at startup (§1.2) — first WS connect is fast, but **Kokoro and
  the e5 embedder load lazily on first use**, so the *first* synthesis/RAG call
  pays a one-time load cost. **[Confirmed]** (`kokoro_tts.py:117`, lazy `_ensure_loaded`).
- Whisper transcribe is offloaded to a thread; STT target <150 ms (docstring —
  **[Speculation]** as a guarantee). Embedding ~30 ms/query (docstring).
- KokoClone first chunk ~0.5–1 s; full ~3–7 s (module docstring). **[Confirmed as
  documented expectation]**

---

## 10. Error Handling & Performance

- **Recoverable, silent:** STT empty/short (skipped), RAG failure (`""` context),
  SearXNG failure (→ GENERAL), one TTS engine failing (router fallback), one LLM
  backend failing (chain fallback). None surface to the client as errors.
- **Fatal to a turn:** all LLM backends down → `RuntimeError`, caught+logged, turn
  produces **no output and no final chunk** → **UI can hang** (no client timeout).
  **[Confirmed gap]**
- **Fatal to connection:** unhandled exception → WS close 1011.
- **Bottlenecks / blocking:** LLM generation (network-bound), TTS synthesis
  (CPU/GPU, per-sentence), Whisper (thread-offloaded). The 64 KB audio framing and
  per-frame WAV re-decode add overhead. `interrupt_event` polling uses
  `sleep(0.1)` loops — up to 100 ms latency to notice an interrupt in a worker.
- **Memory:** models are process-global and shared; conversation history bounded
  at 10 turns.
- **Frontend-visible latency sources [Speculation/Recommendation]:** first-token
  time (LLM), first-audio time (first sentence must complete before TTS starts),
  and cold-start on the first request after boot.

---

## 11. Migration Audit (for the frontend agent — actionable)

| Subsystem | Desktop responsibility | Browser equivalent | Unchanged? | Backend change needed? | Hidden PyQt coupling | Risk |
|---|---|---|---|---|---|---|
| Transport | `websockets` lib, auto-reconnect | `WebSocket` API, `binaryType="arraybuffer"`, own backoff | Protocol unchanged | No | none | Low |
| Mic capture | sounddevice 16k/mono/PCM16 | getUserMedia + AudioWorklet + **resample to 16k** + Int16 | No (format identical, source differs) | No | WSL PulseAudio hacks (irrelevant) | **Med** (resampling correctness) |
| VAD/segmentation | Silero VAD client-side | JS VAD (`vad-web`) or push-to-talk | Must reproduce | No | manual-speak state machine | **Med** |
| Send audio | one binary msg per utterance | same | Must reproduce | No | implicit-interrupt tuned for whole utterances | **High if streamed frame-by-frame** |
| Text send | `text_input {lang:"auto"}` | same | Yes | No | local echo of user text | Low |
| Receive text | append `llm_text_chunk` | same | Yes | No | `_response_started` gating | Low |
| Receive audio | per-frame WAV/raw-PCM decode @24k | ring-buffer PCM16@24k player | **Reproduce carefully** | *Recommend* remove 64 KB split OR add length-prefix framing | raw-PCM-fallback masks header loss | **High** |
| Barge-in | send audio/text + `playback.stop()` | send + flush audio queue | Yes | No | playback.stop internals | Med |
| Clear session | sends `session_reset` (**no-op server-side**) | reconnect to reset, OR request server handler | — | **Yes: add `session_reset` handler** to clear history | button state | Med |
| Status/health | none in UI | fetch `/health` | new capability | No | none | Low |
| Error recovery | none | **add client timeout** for stuck "thinking" | new capability | *Recommend* server error event | none | Med |

**Recommended backend additions (small, high-value) [Recommendation]:**
1. **Handle `session_reset`** in `handle_control_message` → `conversation_history.clear()`
   + ack. Removes the silent no-op.
2. **Per-sentence audio framing:** either stop splitting WAV at 64 KB, or prepend a
   4-byte length prefix per WAV (like KokoClone's internal format) so the browser
   can reassemble deterministically without relying on the raw-PCM fallback.
3. **Explicit `audio_end` / `speaking_done` event** so the browser knows when
   playback for a turn is complete (currently inferred).
4. **Optional error event** (`{type:"error", detail}`) when a turn fails, so the UI
   isn't left hanging on total LLM failure.

---

## 12. Technical Audit

| # | Item | Label | Detail |
|---|---|---|---|
| 1 | `session_reset` sent by client, unhandled by server | **Confirmed** | `ui/app.py:345` vs `pipeline.py:942`. Server history never cleared by it; falls to "unknown type" log. |
| 2 | 64 KB WAV splitting breaks per-frame decodability | **Confirmed** | `pipeline.py:826-831`. Non-first slices are headerless PCM; only playable via the client's raw-PCM-@24k fallback (`audio_playback.py:68-72`). A browser `decodeAudioData` will fail on them. |
| 3 | OpusEncoder/Decoder are placeholders; wire audio is WAV not Opus | **Confirmed** | `tts/opus_encoder.py:48-61` passthrough; docstrings elsewhere say "Opus" (`pipeline.py:93`). Misleading; audio is 24 kHz WAV. |
| 4 | No end-of-audio signal for a turn | **Confirmed** | Client infers completion from text `final:true`; audio just stops. Race: audio can lag text. |
| 5 | No client-side timeout on stuck turns | **Confirmed** | Total LLM failure yields no `final` chunk; UI hangs. |
| 6 | Implicit-interrupt fires per binary frame during "speaking" | **Confirmed** | `pipeline.py:862-870`. Safe for whole-utterance sends; a browser streaming small frames mid-utterance would self-interrupt repeatedly. |
| 7 | `text_input` transcript not echoed; relies on client local render | **Confirmed** | `pipeline.py:938-941`. Voice path echoes `transcript`; text path does not — asymmetric contract the browser must know. |
| 8 | Client `lang` field effectively ignored (server re-detects) | **Confirmed** | `pipeline.py:906-928`. Send `"auto"`; document that `"en"`/`"ja"` may be overridden. |
| 9 | Interrupt detection latency up to ~100 ms | **Confirmed** | Workers poll `interrupt_event` in `sleep(0.1)` loops. |
| 10 | docker-compose references legacy TTS (voicevox/cosyvoice) unused by code | **Confirmed** | `docker-compose.yml:35-36,63`. Config drift; current code uses Kokoro/KokoClone. |
| 11 | vLLM commented out in compose → Ollama is the effective default LLM | **Confirmed** | `docker-compose.yml:72-112`. |
| 12 | Capture 16 kHz vs playback 24 kHz mismatch | **Confirmed** | Two different rates on the same socket; browser must handle each independently. |
| 13 | No auth on WS or `/health`; CORS `*` | **Confirmed** | `main.py:90-96`. Fine for LAN kiosk; a browser deployment on the open internet would need auth/origin control. |
| 14 | `conversation_history` is per-connection only; reconnect loses context | **Confirmed** | `cleanup()` clears it (`pipeline.py:1082-1085`). No persistence. |
| 15 | Boilerplate language tags could leak to client if strip patterns miss a variant | **Speculation** | Stripping is regex-based (`pipeline.py:563-578`); an unmatched variant would appear in `llm_text_chunk`. Browser should tolerate/strip defensively. |

---

## Appendix A — Minimal browser client checklist

1. Open `WebSocket(SERVER_WS_URL)`, `binaryType = "arraybuffer"`.
2. On open → send `session_start`; wait for `session_ack`.
3. **Mic:** getUserMedia → AudioWorklet → resample 16 kHz → Int16 PCM → VAD →
   on end-of-speech, send the whole utterance as **one binary frame** (≥0.5 s).
4. **Text:** send `{type:"text_input", text, lang:"auto"}`; render user text locally.
5. **On message:**
   - `ArrayBuffer` → audio player (treat as 24 kHz PCM16; strip `RIFF` header if
     present; queue for gapless playback; support flush).
   - JSON `transcript` → user bubble. `llm_text_chunk` → append (open bubble on
     first non-empty; close on `final:true` only if opened). `status` → UI state.
6. **Barge-in:** on new speech/text/`interrupt` → flush audio queue + stop playback.
7. **Reconnect:** backoff; on reopen re-send `session_start`.
8. **Timeouts:** if no `final:true` within N seconds of a request, surface a soft
   error and re-enable input.

## Appendix B — Confidence & unconfirmed items

- **Unconfirmed — not found in code:** any server-side idle/session timeout beyond
  framework WS ping defaults; any rate limiting; any persistence of conversation
  history across reconnects; any `audio_end` signal.
- All schemas and the message catalog (§4) are **Confirmed** against
  `server/pipeline.py` and `server/main.py`. The audio-framing hazard (§5.3, §12
  item 2) is **Confirmed** by reading the send path and the client decode path
  together.
