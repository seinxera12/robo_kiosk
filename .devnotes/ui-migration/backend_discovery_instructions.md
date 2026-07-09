# ROLE
You are a senior Software Architect and Technical Auditor reverse-engineering a
Local-first AI chatbot backend. Your output is the single source of truth another
AI agent will use to migrate the PyQt6 desktop client to a browser frontend —
WITHOUT reading the backend source.

# SCOPE
- Analyze: `server/`, `client/`
- Ignore: archived, deprecated, experimental, or legacy code (unless still
  referenced by active code paths)
- Known components (starting points only — verify, don't assume completeness):
  FastAPI, WebSockets, PyQt6 client, vLLM, Ollama (fallback), Faster-Whisper (STT),
  Kokoro/Kokoclone (TTS), ChromaDB, multilingual-e5-large embeddings, SearXNG,
  RAG pipeline, audio streaming, interrupt/barge-in handling.

# METHOD (do this before writing anything)
1. Read the full codebase in `server/` and `client/`.
2. Trace these lifecycles end-to-end across files before documenting any single
   module: startup → request → conversation → audio capture/playback → AI
   pipeline (retrieval → prompt → generation → TTS) → interrupt → disconnect/reconnect.
3. Cross-reference every module against how it's actually called elsewhere —
   do not document a module in isolation from its callers/consumers.
4. If a later discovery contradicts an earlier assumption, revise before writing.
5. Never guess. If something can't be confirmed from code, write
   **"Unconfirmed — not found in code"** rather than inferring.
6. Distinguish, throughout: **Confirmed fact** (cite file/function) vs.
   **Recommendation** vs. **Speculation** — label every claim in the audit sections.

# WHAT TO SKIP
Trivial helpers, boilerplate, and utility functions that don't affect system
behavior, contracts, or state. Document behavior and contracts, not file listings.

# OUTPUT STRUCTURE
Produce one document with these sections, in order:

## 1. Architecture Overview
Core modules, service boundaries, dependency graph, runtime interactions.
Explain *why* the system is shaped this way, not just what exists.

## 2. Module Reference
Per major module: purpose, responsibilities, dependencies, entry points,
exports, consumers, lifecycle, async/threading behavior, shared state, config.

## 3. Frontend Integration Guide  ⭐ (highest priority — be exhaustive here)
For every frontend-facing interaction, specify:
- Endpoint + protocol (REST/WebSocket), method, path
- Payload format (JSON/binary/PCM/WAV/base64/multipart), headers, content-type
- Auth (if any)
- Request/response schema, with example payloads
- Streaming behavior (chunking, framing, end-of-stream signal)
- Connection lifecycle: connect, disconnect, reconnect, timeout, retry
- Cancellation / interrupt handling
- Error responses and status codes
- Required call ordering and state preconditions
- Any implicit assumptions the PyQt client makes that a browser client must replicate

## 4. API Reference
Every REST and WebSocket endpoint: input/output schema, message types,
status/error codes, example payloads, producer/consumer, including internal
WebSocket events not exposed as "official" API.

## 5. Audio Pipeline
Full mic-to-playback lifecycle: capture format, sample rate/channels/chunking,
VAD, STT (Whisper) handoff, streaming/buffering, barge-in/interrupt behavior,
TTS (Kokoro) output, binary transport format, and everything exchanged over
the wire between client and server.

## 6. AI Pipeline
Conversation lifecycle: prompt construction, context assembly, memory, search,
RAG/retrieval, embedding, reranking, LLM routing + fallback logic, token
streaming, response assembly, TTS handoff.

## 7. End-to-End Data Flows
Diagram/narrate complete flows for: text request, voice request, interrupt,
reconnect, search/RAG, STT, TTS, model fallback. Show every format/protocol/
ownership transformation the data undergoes.

## 8. State Management
Conversation, connection, pipeline, playback, recording, and interrupt state;
queues, locks, async primitives, synchronization, shared memory.

## 9. Services & Configuration
Per service: purpose, start/stop, ports, health checks, dependencies, fallback
behavior, expected latency, warm-up/caching. Then: env vars, config files, CLI
args, model paths, Docker config, defaults/overrides.

## 10. Error Handling & Performance
Exception/retry/fallback behavior, recoverable vs. fatal failures, timeouts,
graceful degradation. Then: known bottlenecks, blocking calls, long-running
tasks, threading/async concerns, memory usage, likely sources of frontend-visible latency.

## 11. Migration Audit (written directly for the frontend migration agent)
For each subsystem: current desktop responsibility → browser equivalent →
can it stay unchanged? → backend changes required? → hidden PyQt coupling? →
shared-state assumptions? → migration risks? → recommended abstraction/API
additions. Be actionable, not descriptive.

## 12. Technical Audit
Hidden coupling, architectural debt, missing abstractions, protocol/payload
inconsistencies, API design issues, concurrency risks, streaming inefficiencies,
maintainability concerns, migration blockers. Label each item Confirmed /
Recommendation / Speculation.

# SUCCESS CRITERION
A separate AI agent should be able to build a working browser frontend using
only this document — no access to backend source. Every protocol, schema,
state transition, and behavioral edge case the frontend depends on must be
captured accurately and unambiguously.