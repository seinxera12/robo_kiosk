# System Design Guide — Voice Kiosk Chatbot

This document explains how the system works at the architecture and execution level. Not a tutorial — a mental model. Read this once and you'll understand why things are wired the way they are, what's happening at any given millisecond, and why the design choices were made.

---

## The Big Picture

The system is a real-time voice pipeline. A user speaks, the system listens, understands, thinks, and speaks back — all as fast as possible. The core design challenge is latency: every stage (audio capture, transcription, intent classification, context retrieval, LLM inference, speech synthesis, audio playback) takes time, and they must be orchestrated so they overlap as much as possible rather than running one after another.

The architecture is split into two processes:

```
[Client Process — PyQt6 UI on WSL2]
  Microphone → VAD → WebSocket → (audio bytes out)
  WebSocket → (JSON tokens in) → UI display
  WebSocket → (binary WAV in) → Speaker

[Server Process — FastAPI/uvicorn on WSL2]
  WebSocket → audio_input_worker → STT
           → llm_worker → LLM inference
           → tts_worker → TTS synthesis
           → audio_output_worker → WebSocket
```

They communicate over a single persistent WebSocket connection. The client sends raw PCM audio bytes and JSON control messages. The server sends back JSON text tokens and binary WAV audio chunks.

---

## Concurrency Model — The Foundation

Everything in the server runs inside a single Python process with a single asyncio event loop. This is the key architectural decision. Understanding it explains everything else.

### What asyncio actually is

asyncio is a cooperative multitasking system. There is one thread. Tasks take turns running. A task runs until it hits an `await`, at which point it voluntarily yields control back to the event loop, which picks the next ready task.

This means:
- No true parallelism for CPU-bound work (Python's GIL prevents that anyway)
- Perfect for I/O-bound work: waiting for HTTP responses, WebSocket messages, database queries
- Zero overhead for context switching between tasks (no OS thread scheduling)

The server's entire pipeline — STT, LLM, TTS, WebSocket I/O — is built on this model.

### Where real parallelism happens

CPU-heavy work (Whisper transcription, embedding computation) is offloaded to a thread pool via `asyncio.get_event_loop().run_in_executor(None, fn)`. This spawns the work on a separate OS thread, freeing the event loop to keep processing other tasks while the GPU/CPU grinds through the model inference. The result comes back as an awaitable future.

```python
# In whisper_stt.py — transcription runs in a thread pool
segments, info = await loop.run_in_executor(
    None,
    self._transcribe_sync,  # runs on a thread, not blocking the event loop
    audio_float
)
```

So the actual execution model is:
- asyncio event loop: handles all I/O, routing, coordination
- Thread pool workers: handle CPU/GPU model inference (Whisper, embeddings)
- External HTTP services: CosyVoice (port 5002), VOICEVOX (port 50021), Ollama (port 11434), SearXNG (port 8081) — all called asynchronously via httpx

---

## Server Startup — Pre-loading Everything

`server/main.py` uses FastAPI's `lifespan` context manager. Before the server accepts a single WebSocket connection, it pre-loads all heavy components:

```
startup sequence:
  1. WhisperSTT — loads faster-whisper model into GPU/CPU memory (~1.5 GB)
  2. LLMFallbackChain — initializes Ollama/vLLM/Grok clients
  3. BuildingKB — connects to ChromaDB, loads sentence-transformer embedder
  4. TTSRouter — initializes CosyVoice and VOICEVOX HTTP clients
```

This takes 10–30 seconds on first run. After that, every WebSocket connection gets these pre-loaded instances injected directly — no model loading per connection. This is why the first connection is instant after startup.

The pre-loaded instances are stored in `app_state` dict and passed into each `VoicePipeline` constructor via dependency injection.

---

## The Pipeline Workers — Five Concurrent Coroutines

When a WebSocket connection arrives, `VoicePipeline.run()` is called. It launches five coroutines concurrently using `asyncio.gather()`:

```python
await asyncio.gather(
    self.audio_input_worker(),   # STT
    self.llm_worker(),           # LLM + RAG/Search
    self.tts_worker(),           # TTS sentence assembly
    self.audio_output_worker(),  # WebSocket audio sender
    self.websocket_receiver(),   # Incoming message handler
)
```

These five coroutines run "simultaneously" — they interleave on the event loop. Each one loops forever, waiting on its input queue, doing work, putting results in the next queue. This is the pipeline pattern: data flows through a chain of queues.

```
websocket_receiver
    ↓ (audio bytes → audio_input queue)
audio_input_worker
    ↓ (TranscriptionResult → transcript queue)
llm_worker
    ↓ (tokens → token queue)
tts_worker
    ↓ (WAV bytes → audio_output queue)
audio_output_worker
    ↓ (WAV bytes → WebSocket → client)
```

Each queue is an `asyncio.Queue`. Putting something in a queue is instant. Getting from a queue suspends the coroutine until something arrives — this is the `await` that yields control back to the event loop.

### Why this design achieves low latency

The key insight: the LLM starts generating tokens before TTS has finished the previous sentence. The TTS starts synthesizing the first sentence before the LLM has finished generating the full response. The audio starts playing on the client before the server has finished synthesizing all sentences.

This is pipeline parallelism. Each stage is always busy with the next piece of work while downstream stages are still processing the previous piece.

---

## Stage 1 — WebSocket Receiver

`websocket_receiver()` is the entry point. It loops on `await self.ws.receive()`, which suspends until a message arrives from the client.

Two message types:
- **Binary bytes**: raw PCM16 audio from the microphone → pushed to `audio_input` queue
- **JSON text**: control messages (`session_start`, `text_input`, `interrupt`) → handled inline

For `text_input` (keyboard mode), the receiver bypasses the STT stage entirely — it constructs a fake `TranscriptionResult`-like object and pushes it directly to the `transcript` queue, skipping `audio_input_worker` completely.

---

## Stage 2 — STT (audio_input_worker)

`audio_input_worker()` waits on `audio_input` queue. When audio bytes arrive:

1. Calls `await self.stt.transcribe(audio_bytes)`
2. Inside `WhisperSTT.transcribe()`:
   - Converts PCM16 bytes → float32 numpy array (normalization: divide by 32768)
   - Calls `await loop.run_in_executor(None, self._transcribe_sync, audio_float)` — this offloads Whisper inference to a thread pool worker, freeing the event loop
   - `_transcribe_sync` calls `faster_whisper.WhisperModel.transcribe()` — this runs on GPU via CUDA, consuming ~100–500ms depending on audio length
   - The generator returned by faster-whisper is fully consumed inside the thread (`list(segments)`) — important because generators are not thread-safe to pass back to the event loop
3. Language detection: if Whisper's confidence ≥ 0.6, use Whisper's detected language. Otherwise, scan the transcript text for Japanese Unicode characters (ratio > 0.1 → Japanese)
4. Pushes `TranscriptionResult(text, language, confidence, duration_ms)` to `transcript` queue
5. Sends `{"type": "transcript", "text": ..., "lang": ...}` back to client so the UI can show what was heard

---

## Stage 3 — LLM Worker (the most complex stage)

`llm_worker()` waits on `transcript` queue. When a transcript arrives, it does several things in sequence:

### 3a. Intent Classification (zero latency)

`IntentClassifier.classify()` runs synchronously — no await, no network call. It uses a two-tier approach:

**Tier 1 — Keyword matching**: scans the query text for pre-defined keyword sets (`_BUILDING_KEYWORDS`, `_SEARCH_KEYWORDS`). Counts hits per category. Winner by count gets the intent. This takes microseconds.

**Tier 2 — Embedding similarity** (only if keyword confidence < 0.7): encodes the query with the same sentence-transformer already loaded for RAG, then computes cosine similarity against pre-computed anchor phrase embeddings. The anchor embeddings are computed once at startup in `_precompute_anchors()`. This takes ~30ms.

Result: one of `Intent.BUILDING`, `Intent.SEARCH`, or `Intent.GENERAL`.

### 3b. Context Retrieval (parallel opportunity)

Depending on intent:

**BUILDING intent** → RAG retrieval via `BuildingKB.retrieve()`:
- Embeds the query using `multilingual-e5-large` sentence transformer (CPU, ~30ms)
- Queries ChromaDB with the embedding + language filter (`where={"lang": lang}`)
- Returns top-3 most similar document chunks as concatenated text
- ChromaDB query is synchronous but fast (~5ms for small collections)

**SEARCH intent** → Web search via `searxng_search()`:
- Makes an async HTTP GET to SearXNG at `http://localhost:8081/search`
- Uses `httpx.AsyncClient` — fully non-blocking, event loop stays free during the network round-trip
- Returns up to 3 results with title, content snippet, URL
- Timeout: 8 seconds read, 3 seconds connect
- On failure (timeout, connection refused): returns empty list, intent falls back to GENERAL

**GENERAL intent** → no retrieval, empty context string

### 3c. Prompt Building

`build_messages()` in `prompt_builder.py` assembles the message list:

1. Selects the right system prompt template (`_BUILDING_SYSTEM`, `_SEARCH_SYSTEM`, or `_GENERAL_SYSTEM`)
2. Fills in: building name, datetime, kiosk location, retrieved context, detected language
3. Trims conversation history to fit within the token budget (3000 tokens max input, ~12000 chars). Oldest turns are dropped first, always keeping at least the last 1 turn.
4. Appends the current user message
5. Appends a language enforcement reminder as a final system message (English or Japanese few-shot examples)

Result: a list of `{"role": ..., "content": ...}` dicts — the standard OpenAI chat format.

### 3d. LLM Streaming via Fallback Chain

`LLMFallbackChain.stream_with_fallback()` tries backends in order, starting from the last successful one (`_healthy_index` cache):

For each backend:
1. Health check: `await asyncio.wait_for(backend.ping(), timeout=5.0)` — if it times out or fails, skip this backend
2. Call `backend.stream(messages)` — this returns an async generator
3. Iterate the generator: each `async for token in backend.stream(...)` yields one text token

For `OllamaBackend`, `stream()` calls the OpenAI-compatible `/v1/chat/completions` endpoint with `stream=True`. The response is a server-sent events stream. The `AsyncOpenAI` client handles chunked HTTP reading internally — each `await` in the `async for` loop suspends until the next chunk arrives from Ollama.

Each token is:
- Put into the `token` queue for the TTS worker
- Sent to the client as `{"type": "llm_text_chunk", "text": token, "final": false}`

This means the client sees text appearing word-by-word in real time, and the TTS worker starts synthesizing the first sentence before the LLM has finished generating the full response.

After all tokens: sends `{"type": "llm_text_chunk", "text": "", "final": true}` to signal completion. Updates conversation history (max 20 messages = 10 turns).

---

## Stage 4 — TTS Worker (sentence-boundary streaming)

`tts_worker()` does not wait for the LLM to finish. It runs concurrently with `llm_worker()`, consuming tokens from the `token` queue as they arrive.

The key design: it accumulates tokens into a buffer until it detects a sentence boundary (`.?!。？！…`) with at least 8 characters. Then it synthesizes that sentence immediately, without waiting for the rest of the response.

```
LLM generates: "The cafeteria is on the 3rd floor."
                                                   ↑ sentence boundary detected here
TTS synthesizes "The cafeteria is on the 3rd floor." immediately
LLM continues:  " Take the elevator near the main entrance."
                                                            ↑ next boundary
TTS synthesizes second sentence while client plays first
```

This is why the user hears the first sentence of the response before the LLM has finished generating the full answer.

**Language routing**: `TTSRouter.get_engine(lang)` returns the right engine:
- `lang == "en"` → `CosyVoiceTTS` (HTTP POST to `localhost:5002/synthesize`)
- `lang == "ja"` → `VoicevoxTTS` (two HTTP calls: `audio_query` then `synthesis` to `localhost:50021`)

Both TTS calls are async HTTP via `httpx.AsyncClient` — non-blocking.

The synthesized WAV bytes are pushed to the `audio_output` queue.

**Timeout handling**: if no token arrives within 0.5 seconds (`asyncio.wait_for(..., timeout=0.5)`), the buffer is flushed — this handles the end of the response where the last sentence may not end with punctuation.

---

## Stage 5 — Audio Output Worker

`audio_output_worker()` is the simplest stage. It waits on `audio_output` queue and sends each WAV chunk to the client as binary WebSocket bytes:

```python
await self.ws.send_bytes(audio_chunk)
```

The client receives these binary frames and plays them through the speaker.

---

## Interrupt Handling (Barge-in)

When the user presses the Speak button while the assistant is talking, the client sends `{"type": "interrupt"}`. The server's `handle_interrupt()`:

1. Sets `self.state.interrupt_event` — all five workers check this flag at the top of their loops and pause
2. Drains all four queues (discards any pending audio, tokens, transcripts)
3. Resets state to "listening"
4. Clears the interrupt event so workers resume

This stops TTS playback mid-sentence and resets the pipeline to accept new input.

---

## Client Architecture — Two Threads

The client has a fundamentally different concurrency model because it uses PyQt6, which requires all UI operations on the main thread.

### Thread 1 — Qt Main Thread

Runs the PyQt6 event loop. Handles all UI: button clicks, text display, status updates. Never does I/O or blocking work.

### Thread 2 — PipelineWorker (QThread + asyncio)

`PipelineWorker.run()` creates a new asyncio event loop on this thread and runs `_main()` inside it. This thread owns:
- `WebSocketClient` — persistent WebSocket connection to server
- `AudioCapture` — sounddevice microphone stream
- `SileroVAD` — voice activity detection
- `AudioPlayback` — speaker output

Communication between threads uses Qt signals/slots:
- Worker emits signals (`token_received`, `transcript_ready`, `status_changed`) → Qt main thread receives them and updates UI
- Main thread calls worker methods (`start_manual_speak`, `send_text`, `stop`) → these write to shared state that the asyncio loop reads

### Audio Capture Flow

`AudioCapture.stream()` opens a `sounddevice.InputStream`. The sounddevice library calls `_audio_callback()` from a separate audio thread (not the asyncio thread) every 32ms with a new frame of PCM16 audio. The callback converts the frame to bytes and puts it in `self._queue` using `put_nowait()` (non-blocking).

The asyncio coroutine `_capture_loop()` does `frame = await self._queue.get()` — this suspends until a frame arrives, then processes it through VAD.

### VAD (Silero VAD)

`SileroVAD.process_frame()` runs synchronously on each 32ms frame. It:
1. Converts PCM16 bytes → float32 tensor, normalizes to [-1, 1]
2. Runs `self.model(audio_tensor, 16000)` — a small ONNX model, ~1ms on CPU
3. Returns speech probability (0.0–1.0)
4. State machine: silence → speech_start (when prob > 0.3 for ≥200ms) → speech_chunk → speech_end (when silence > 800ms)

When `speech_end` fires, the accumulated `speech_buffer` (all audio since speech_start) is sent to the server as binary WebSocket bytes.

### Audio Playback

`AudioPlayback.queue_audio()` receives WAV bytes from the server, decodes them with Python's `wave` module, and queues the raw PCM16 data. `_start_playback()` opens a `sounddevice.OutputStream` and writes PCM16 numpy arrays to it. The sounddevice library handles the actual hardware I/O.

---

## Data Formats Through the Pipeline

Understanding what format data is in at each stage:

| Stage | Format | Details |
|-------|--------|---------|
| Microphone → VAD | float32 numpy array | 32ms frames, 16kHz, normalized [-1,1] |
| VAD → WebSocket | PCM16 bytes | int16, 16kHz, mono, variable length |
| WebSocket → audio_input queue | PCM16 bytes | same |
| STT input | float32 numpy array | converted back: divide by 32768 |
| STT output | TranscriptionResult | text str, language "en"/"ja", confidence float |
| LLM input | list[dict] | OpenAI chat format: [{role, content}, ...] |
| LLM output | str tokens | one word/subword at a time |
| TTS input | str | complete sentence (8+ chars, ends with punctuation) |
| TTS output | WAV bytes | PCM16, 22050Hz, mono |
| WebSocket → client | WAV bytes | same |
| Playback input | PCM16 bytes | decoded from WAV header |

---

## The Embedding Model — Shared Between RAG and Intent Classification

`multilingual-e5-large` (1024-dim embeddings) is loaded once in `BuildingKB.__init__()` as `self.embedder`. This same `Embedder` instance is passed to `IntentClassifier`:

```python
self.intent_classifier = IntentClassifier(
    embedder=self.rag.embedder  # reuse, don't load twice
)
```

At startup, `IntentClassifier._precompute_anchors()` encodes all anchor phrases once and caches the embeddings. During inference, only the user query needs to be encoded (~30ms). This avoids loading a second model and keeps GPU/CPU memory usage down.

---

## LLM Fallback Chain — Resilience Pattern

The fallback chain implements a priority-ordered list of backends with health checking:

```
Priority: vLLM (disabled) → Ollama → Grok API
```

`_healthy_index` caches the index of the last successful backend. On the next request, it starts from that index rather than always starting from index 0. This means if Ollama is working, it goes straight to Ollama without wasting time health-checking vLLM first.

Health checks use `asyncio.wait_for(..., timeout=5.0)` — if the backend doesn't respond within 5 seconds, it's skipped. This prevents one slow backend from blocking the entire response.

All backends implement the same `BaseLLMBackend` protocol (duck typing via `Protocol` class): `ping()` and `stream()`. The fallback chain doesn't care which backend it's talking to.

---

## Why Things Are Fast (Summary)

1. **Pre-loading**: models loaded once at startup, not per request
2. **Thread pool for CPU work**: Whisper runs on a thread, event loop stays free
3. **Async HTTP everywhere**: all external service calls (Ollama, CosyVoice, VOICEVOX, SearXNG) are non-blocking
4. **Pipeline parallelism**: LLM generates while TTS synthesizes while client plays
5. **Sentence-boundary streaming**: TTS starts on first sentence, not after full response
6. **Intent classification in microseconds**: keyword matching before embedding fallback
7. **Anchor pre-computation**: embedding similarity anchors computed once at startup
8. **Backend caching**: fallback chain remembers last working backend

---

## Latency Budget (Approximate, GPU Mode)

| Stage | Time |
|-------|------|
| VAD speech detection | ~800ms silence threshold (by design) |
| Whisper transcription | 100–500ms (GPU) |
| Intent classification | <1ms (keyword) or ~30ms (embedding) |
| RAG retrieval | ~35ms (embed + ChromaDB query) |
| SearXNG search | 500ms–3s (network) |
| LLM first token (Ollama, 3B) | ~300–800ms |
| TTS first sentence (CosyVoice) | 150–300ms |
| Audio playback start | ~50ms |
| **Total: user stops speaking → first audio** | **~1.5–5 seconds** |

The dominant costs are Whisper (unavoidable — model inference) and LLM first token (unavoidable — autoregressive generation). Everything else is optimized to overlap with these.
