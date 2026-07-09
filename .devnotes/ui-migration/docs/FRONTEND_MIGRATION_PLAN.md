# Frontend Migration Plan — PyQt6 Desktop → Browser Client

> **Reference:** All backend claims cite `BACKEND_MIGRATION_REFERENCE.md` (herein "REF")
> by section (§) or technical-audit item (#). Every backend/config change traces to a
> specific frontend requirement. **No application code appears here** — descriptions only.
>
> **Audience:** a coding agent implementing task-by-task. Each task in §5 is
> self-contained: it can be executed and validated against its acceptance criteria
> without re-reading the whole plan.

---

## 1. Migration Summary

We replace the PyQt6 desktop kiosk client with a browser SPA that speaks the **exact
same single-WebSocket protocol** (`ws://host:8765/ws`) — the server is untouched for
core functionality. The browser reproduces the desktop client's narrow contract:
capture mic audio and **resample to 16 kHz mono PCM16**, run **client-side VAD** to
emit one binary frame per complete utterance, render streamed `llm_text_chunk` text,
and play streamed **24 kHz WAV/PCM16** audio with barge-in flush (REF §3, §5, Appendix A).
The single biggest architectural decision: **audio playback will treat the inbound
binary stream as raw 24 kHz PCM16 fed to a Web Audio ring buffer — NOT `decodeAudioData`
per frame** — because the server splits WAVs into ≤64 KB frames whose non-first slices
are headerless and would break `decodeAudioData` (REF §5.3, #2). **Overall risk: Medium**,
concentrated in two areas: mic resampling correctness and audio reassembly/playback.
Backend changes are **optional and small** (session_reset handler, audio-end signal,
error event); the existing API surface is sufficient to ship a working client without
any of them, so they are staged as an optional Phase.

---

## 2. Backend Change Requirements

**The existing API surface is sufficient to build a functional browser client with
zero backend changes.** The protocol is transport-agnostic (JSON text + binary frames
over standard WebSocket), CORS is already `*`, and every event the UI needs is emitted
(REF §3.1, §4.2). The following are **optional, low-risk, high-value** additions. Each
has a frontend-only fallback, so none blocks Phase 0–3. They are cited because the docs
themselves flag them as gaps (REF §11 "Recommended backend additions", §12).

### BE-1 — `session_reset` handler (optional)
- **Gap:** Client sends `{"type":"session_reset"}`; server has no branch and logs
  "Unknown control message type" — history is never cleared (REF §3.3.5, #1).
- **Proposed change:** Add a `session_reset` branch to the control handler that clears
  `conversation_history` and returns an ack.
- **Why frontend-only isn't sufficient:** The browser cannot reach server-side history;
  the *only* client-side way to clear it is to drop and reopen the socket.
- **Risk of NOT making it:** "Clear conversation" must be implemented as a full
  reconnect (works, but loses the socket and re-pays session_start). Acceptable.
- **Risk of making it:** Minimal — new branch, no change to existing paths; desktop
  client already sends the message and currently ignores the no-op response.
- **Frontend fallback (default):** implement "Clear" as reconnect (see FE-14).

### BE-2 — Deterministic per-sentence audio framing (optional)
- **Gap:** Server splits each WAV >64 KB into multiple ≤64 KB binary frames; non-first
  slices are headerless PCM only playable via a raw-PCM-@24k fallback (REF §5.3, #2).
- **Proposed change:** Either stop splitting WAV at 64 KB, or prepend a 4-byte
  length prefix per logical WAV so the client can reassemble deterministically.
- **Why frontend-only isn't sufficient:** Without framing the client cannot know where
  one logical WAV ends — BUT because all engines emit fixed 24 kHz mono PCM16, the
  client *can* sidestep this by ignoring WAV boundaries entirely and treating the whole
  binary stream as raw PCM16 (FE-11). So frontend-only IS sufficient here; this change
  only makes the client simpler/more robust.
- **Risk of NOT making it:** none if FE-11's raw-PCM approach is used as specified.
- **Risk of making it:** Changing framing could break the desktop client's per-frame
  `wave.open()` decode path (REF §5.3). **Do not make this change while the desktop
  client is still in use.**
- **Frontend fallback (default):** FE-11 raw-PCM ring buffer — **this is the chosen
  approach regardless.** BE-2 is not recommended.

### BE-3 — Explicit `audio_end` / `speaking_done` event (optional)
- **Gap:** No end-of-audio signal; completion is inferred from `llm_text_chunk{final:true}`,
  but audio can lag text (REF §3.5, #4).
- **Proposed change:** Emit `{"type":"audio_end"}` after the last WAV frame of a turn.
- **Why frontend-only isn't sufficient:** The client genuinely cannot know the true end
  of audio; it can only detect "no frames for T ms" heuristically.
- **Risk of NOT making it:** "Speaking" status may clear slightly early or the client
  relies on an idle-timeout heuristic. Cosmetic.
- **Risk of making it:** Minimal (additive event; unknown types are already ignored by
  any client — REF §4.2).
- **Frontend fallback (default):** treat playback as done when the audio queue drains
  AND `final:true` text was received AND no new frame arrived for a short idle window (FE-12).

### BE-4 — Error event on turn failure (optional)
- **Gap:** Total LLM failure yields no tokens and no `final` chunk; UI can hang (REF §3.7, #5, §10).
- **Proposed change:** Emit `{"type":"error","detail":"..."}` when a turn produces no output.
- **Why frontend-only isn't sufficient:** The client cannot distinguish "slow" from
  "failed" without a signal.
- **Risk of NOT making it:** UI must rely on a client-side timeout to recover a stuck
  "thinking" state. Fully workable.
- **Risk of making it:** Minimal (additive).
- **Frontend fallback (default):** client-side response timeout (FE-13). **Required
  regardless**, because even with BE-4 the socket could stall.

**Net recommendation:** Ship Phases 0–4 with **no backend changes**. If a backend owner
is available, BE-1 and BE-4 are the only two worth doing (both trivial, both additive);
BE-2 is discouraged; BE-3 is nice-to-have.

---

## 3. Configuration & Environment Changes

Only load-bearing entries. The backend already binds `0.0.0.0` and sets CORS `*`
(REF §3.1, §9.1), so **no server config change is required** for a LAN/kiosk browser
deployment.

| Config | Current value/behavior | Required value/behavior | Reason | Affected service |
|---|---|---|---|---|
| `SERVER_HOST` | `0.0.0.0` (REF §9.1) | unchanged | Already binds all interfaces; browser can reach it | voice-server |
| CORS `allow_origins` | `["*"]` (REF §3.1) | unchanged | Only affects the `/health` fetch; WS is not CORS-gated. Already permissive | voice-server |
| `SERVER_PORT` | `8765` (WS) (REF §9.1) | unchanged | Browser connects to `ws://host:8765/ws` | voice-server |
| Health port | `8000` in Docker (REF §4.1) | unchanged | Browser status page fetches `http://host:8000/health` | voice-server |
| **`VITE_SERVER_WS_URL`** (new, frontend) | — | `ws://<host>:8765/ws`, or derive from `window.location` | Frontend must know the WS endpoint; mirrors client `SERVER_WS_URL` (REF §9.2) | new frontend |
| **`VITE_HEALTH_URL`** (new, frontend) | — | `http://<host>:8000/health` | Status page fetch target (REF §4.1) | new frontend |
| **`VITE_KIOSK_ID`** (new, frontend) | — | e.g. `kiosk-01` (REF §9.2) | Sent in `session_start` | new frontend |
| **`VITE_KIOSK_LOCATION`** (new, frontend) | — | e.g. `Floor 1 Lobby` (REF §9.2) | Sent in `session_start`; feeds system prompt | new frontend |

> **Public-internet caveat (out of scope for this plan):** there is no auth on WS or
> `/health` and CORS is `*` (REF #13). This is fine for a LAN kiosk. A public deployment
> would require an auth/origin layer — flagged as Open Question OQ-1, **not** implemented here.

---

## 4. Frontend Architecture Plan

### 4.1 Stack rationale (fit-for-contract, not preference)
- **Framework: React + TypeScript + Vite.** Chosen because the contract is
  event-stream-heavy (streamed tokens, streamed audio, connection/pipeline state
  machine — REF §3, §8): a component model with a central store maps cleanly onto it,
  and TS lets us type the message catalog (REF §4.2) so malformed payloads are caught
  at the boundary. Vite gives simple env-var config (`VITE_*`) matching REF §9.2.
- **Audio: Web Audio API + AudioWorklet.** Required, not optional: capture must
  resample to 16 kHz and convert to Int16 (REF §5.1, §3.9.2), and playback must feed a
  **24 kHz PCM16 ring buffer** rather than `decodeAudioData` (REF §5.3). Only the Web
  Audio graph gives sample-level control for both directions and instant flush for
  barge-in (REF §5.4).
- **VAD: `@ricky0123/vad-web`** (wraps Silero, matching the desktop's Silero VAD —
  REF §5.2) **with a push-to-talk fallback path.** Client-side VAD is mandatory because
  the server has no live-stream VAD and expects whole ≥0.5 s utterances (REF §3.9.1).
- **No state library beyond a small store** (Zustand or React context+reducer). The
  state machine is small and well-defined (REF §8); a heavyweight solution is unwarranted.

### 4.2 Module breakdown
- **ConnectionManager** — owns the single `WebSocket` (`binaryType="arraybuffer"`),
  backoff reconnect, session_start/ack handshake, frame-type dispatch (text→JSON parse,
  binary→audio player) (REF §3.0, §3.8, §4.2).
- **MessageCodec** — typed encode/decode of the REF §4.2 catalog; discriminates by frame
  type then `type` field; tolerates/strips leaked language boilerplate defensively (REF #15).
- **AudioCapture** — getUserMedia → AudioWorklet → resample to 16 kHz → Float32→Int16 →
  buffer accumulation (REF §5.1).
- **VadSegmenter** — wraps vad-web (or PTT); emits `speech_start`/`speech_end` with a
  pre-roll buffer; enforces ≥0.5 s minimum before emitting an utterance (REF §5.2, §3.3.4).
- **AudioPlayer** — inbound binary → strip `RIFF` header if present else treat as raw
  PCM16 @ 24 kHz → Int16→Float32 → AudioWorklet ring buffer → gapless playback; supports
  instant `flush()` for barge-in (REF §5.3, §5.4).
- **ConversationStore** — chat bubbles + `_response_started` bubble gating; local echo of
  typed user text; status/pipeline state (REF §3.9.4–5, §8).
- **InterruptController** — on new voice/text/explicit interrupt: flush AudioPlayer +
  (for explicit) send `{type:"interrupt"}` (REF §3.6, §5.4).
- **HealthPanel** — periodic `/health` fetch + render (REF §4.1).
- **TimeoutGuard** — client-side response timeout to recover stuck "thinking" (REF §3.7, #5).

### 4.3 State management (mapped to backend state machine, REF §8)
The store mirrors server-authoritative state; **the client never invents pipeline state**:
- **ConnectionState:** `disconnected → connecting → connected(unacked) → ready` (ready =
  after `session_ack`). Reconnect returns to `connecting` and re-sends `session_start`
  (REF §3.8).
- **PipelineStatus:** `idle | listening | thinking | speaking`, driven by events —
  `transcript`/`text_input` → thinking; first audio/token → speaking; `final:true` /
  `status{state}` → listening (REF §8, §3.4). Advisory only; UI display.
- **RecordingState:** `alwaysListen` vs `manualSpeak(push-to-talk)`, with the 15 s
  manual-speak timeout reproduced (REF §5.2, §8).
- **BubbleState:** `_response_started` gating — open assistant bubble on first **non-empty**
  `llm_text_chunk`, close on `final:true` **only if opened** (REF §3.9.5).

### 4.4 PyQt-only behaviors → browser (from REF §11 Migration Audit)
| Desktop behavior | Browser replication |
|---|---|
| `websockets` auto-reconnect, exp backoff (REF §3.8) | ConnectionManager own backoff, `binaryType="arraybuffer"` |
| sounddevice 16k/mono/PCM16 capture (REF §5.1) | AudioCapture: getUserMedia + AudioWorklet + resample + Int16 |
| Silero VAD, whole-utterance send (REF §5.2, §3.9.1) | VadSegmenter (vad-web) or PTT; one binary frame per utterance |
| per-frame WAV/raw-PCM decode @24k (REF §5.3) | AudioPlayer raw-PCM ring buffer @24k |
| local echo of typed text (REF §3.3.2) | ConversationStore renders user bubble locally, expects no `transcript` |
| `_response_started` bubble gating (REF §3.9.5) | BubbleState identical gating |
| `playback.stop()` on barge-in (REF §3.6) | AudioPlayer.flush() |
| manual-speak 15 s timeout (REF §5.2) | RecordingState timeout |
| Clear Session → `session_reset` no-op (REF #1) | reconnect to clear (FE-14) |
| (none) error recovery (REF #5) | TimeoutGuard (new capability) |

---

## 5. Integration Task List

Ordered by dependency chain, grouped into phases. Each task is one agent session.

### Phase 0 — Project + Connection groundwork

---
**Task ID:** FE-1
**Title:** Scaffold frontend project + runtime config
**Depends on:** none
**Backend endpoint(s)/contract used:** none
**Description:** Create the React+TS+Vite SPA skeleton with a typed config module reading
`VITE_SERVER_WS_URL`, `VITE_HEALTH_URL`, `VITE_KIOSK_ID`, `VITE_KIOSK_LOCATION` (REF §9.2,
§3 of this plan), with `window.location`-derived defaults for the WS/health URLs.
**Inputs:** env vars from §3 config table.
**Outputs:** buildable app shell; a `config` module exposing typed values.
**Acceptance criteria:** `npm run build` succeeds; config values resolve from env or
location-derived defaults; dev server runs and renders an empty shell.
**Edge cases:** missing env → sensible localhost defaults (`ws://localhost:8765/ws`,
`http://localhost:8000/health`); `https` page must derive `wss` (note for later deploy).
**Open questions:** none.

---
**Task ID:** FE-2
**Title:** Typed message codec for the WS catalog
**Depends on:** FE-1
**Backend endpoint(s)/contract used:** full catalog REF §4.2 / §3.3 / §3.4.
**Description:** Define TS types + encode/decode for every client→server and server→client
message. Discriminate inbound by frame type (ArrayBuffer=audio, string=JSON) then by
`type`. Decode `session_ack`, `transcript`, `llm_text_chunk`, `status`; encode
`session_start`, `text_input`, `interrupt`, (optional) `session_reset`.
**Inputs:** exact payload shapes REF §3.4 ("Exact payload shapes [Confirmed]").
**Outputs:** `MessageCodec` module + typed union of inbound/outbound messages.
**Acceptance criteria:** round-trip encode/decode unit tests pass for each type; unknown
`type` decodes to a benign "unknown" variant (server ignores unknowns — REF §4.2);
`llm_text_chunk` tokens are preserved **verbatim including leading/trailing spaces** (REF §3.4).
**Edge cases:** empty-string tokens; `final:true` with `text:""`; boilerplate leak
(`[Reply in English]`) — strip defensively (REF §3.5, #15).
**Open questions:** none.

---
**Task ID:** FE-3
**Title:** ConnectionManager + session handshake + reconnect
**Depends on:** FE-2
**Backend endpoint(s)/contract used:** `ws://host:8765/ws`; `session_start`→`session_ack`
(REF §3.2, §3.3.1); reconnect semantics (REF §3.8).
**Description:** Open the WebSocket (`binaryType="arraybuffer"`), on open send
`session_start{kiosk_id,kiosk_location}` and wait for `session_ack{status:"ready"}` before
marking ready. Implement exponential backoff reconnect (1 s → 30 s cap, matching desktop
REF §3.8); on every reopen **re-send `session_start`** (reconnect = fresh server session,
REF §3.8, §7). Route inbound frames to MessageCodec/AudioPlayer.
**Inputs:** config URLs (FE-1), codec (FE-2).
**Outputs:** `ConnectionManager` service + ConnectionState in the store.
**Acceptance criteria:** connects, receives `session_ack`, sets state `ready`; input stays
disabled until ack; killing the server triggers backoff reconnect; on reopen a new
`session_start` is sent and a fresh `session_ack` received.
**Edge cases:** WS close **1011** (unhandled server error — REF §3.7) → treat as error,
reconnect; clean close → reconnect; send-failure → reconnect (REF §3.8); do not send app
messages before `ready`.
**Open questions:** none.

### Phase 1 — Text chat (validates protocol end-to-end without audio)

---
**Task ID:** FE-4
**Title:** ConversationStore + streaming text renderer + bubble gating
**Depends on:** FE-3
**Backend endpoint(s)/contract used:** `llm_text_chunk` (REF §3.4), `status` (REF §3.4),
`transcript` (REF §3.4).
**Description:** Central store for chat bubbles and pipeline status. Append `llm_text_chunk.text`
**verbatim** to the current assistant bubble; open the bubble on the first **non-empty**
chunk, close it on `final:true` **only if opened** (`_response_started` gating — REF §3.9.5).
Render user bubbles from `transcript` events (voice path). Map events to PipelineStatus
(REF §8).
**Inputs:** decoded events (FE-2/FE-3).
**Outputs:** `ConversationStore` + chat transcript UI component.
**Acceptance criteria:** streamed tokens concatenate with no inserted spaces; a lone
`final:true` while idle produces **no** empty bubble; status transitions render.
**Edge cases:** spurious `final:true` from idle-state interrupt (REF §3.9.5); token with
only whitespace; very long streams.
**Open questions:** none.

---
**Task ID:** FE-5
**Title:** Text input send path with local echo
**Depends on:** FE-4
**Backend endpoint(s)/contract used:** `text_input{text,lang:"auto"}` (REF §3.3.2).
**Description:** Text box that sends `{type:"text_input", text, lang:"auto"}` (always
`"auto"` — server re-detects, REF §3.3.2, #8) and **renders the user's message locally
immediately** (no `transcript` echo for typed input — REF §3.3.2, #7). Sending a text_input
implicitly interrupts any in-progress response server-side, so also flush local audio
(coordinate with FE-11 later).
**Inputs:** user text; ConversationStore (FE-4).
**Outputs:** text-input component + send action.
**Acceptance criteria:** typed message appears as a user bubble immediately; assistant
response streams into a new bubble; no duplicate user bubble appears; `lang` is always `"auto"`.
**Edge cases:** rapid successive sends (each preempts prior — REF §3.3.2); empty input
(block send); input disabled until connection `ready`.
**Open questions:** none.

### Phase 2 — Audio

---
**Task ID:** FE-6
**Title:** AudioPlayer — 24 kHz PCM16 ring-buffer playback
**Depends on:** FE-3
**Backend endpoint(s)/contract used:** inbound binary WAV/PCM frames, 24 kHz mono PCM16,
≤64 KB (REF §3.5, §5.3, §4.2).
**Description:** Build the inbound audio player. For each binary frame: if it starts with
`RIFF`, strip the 44-byte WAV header; otherwise treat the entire frame as raw PCM16
(REF §5.3 recommendation, avoiding `decodeAudioData` per #2). Convert Int16→Float32 and
feed a Web Audio AudioWorklet ring buffer clocked at **24 kHz** for gapless playback.
Expose `flush()`/`stop()` that clears the queue and stops the source instantly for barge-in.
**Inputs:** ArrayBuffer frames from ConnectionManager (FE-3).
**Outputs:** `AudioPlayer` module wired to receive binary frames.
**Acceptance criteria:** a multi-sentence response plays continuously and gaplessly;
a WAV >64 KB (arriving as multiple frames, incl. headerless slices) plays without glitches
or decode errors; `flush()` silences output within ~20 ms (matching desktop, REF §5.3).
**Edge cases:** headerless non-first slices (REF §5.3, #2); odd-length byte buffer
(guard Int16 alignment); frames arriving faster than realtime (buffer); empty frame.
**Open questions:** OQ-2 — confirm all engines truly emit 24 kHz mono PCM16 with no
per-engine header variance (REF §5.3 says yes for Kokoro/KokoClone; verify KokoClone
byte layout if audio artifacts appear).

---
**Task ID:** FE-7
**Title:** AudioCapture — mic → 16 kHz mono Int16 PCM
**Depends on:** FE-1
**Backend endpoint(s)/contract used:** binary mic frame contract, PCM16 16 kHz mono
little-endian (REF §3.3.4, §5.1, §3.9.2).
**Description:** getUserMedia({audio}) → AudioContext/AudioWorklet → **resample to 16 kHz**
→ convert Float32 `[-1,1]` to Int16 (`clamp*32767`) → accumulate into a growable buffer.
Produce a method to flush the accumulated utterance as a single `ArrayBuffer` of raw
Int16 samples (no header, no length prefix — REF §3.3.4).
**Inputs:** microphone permission.
**Outputs:** `AudioCapture` module emitting Int16 PCM buffers.
**Acceptance criteria:** captured buffer is exactly 16 kHz mono little-endian Int16; a
1 s utterance yields ~16000 samples (~32000 bytes); resampling verified against a known
tone (no pitch shift). No WAV/RIFF header is added.
**Edge cases:** browser capture at 44.1/48 kHz (must resample — REF §3.9.2); permission
denied (surface a clear error); clamp out-of-range samples (REF §5.1).
**Open questions:** OQ-3 — AudioWorklet vs ScriptProcessor for resampling quality/latency
(REF §5.1 lists both as acceptable; pick AudioWorklet, fall back if unsupported).

---
**Task ID:** FE-8
**Title:** VadSegmenter — utterance detection + PTT fallback
**Depends on:** FE-7
**Backend endpoint(s)/contract used:** whole-utterance send, ≥0.5 s / ≥16000 bytes
minimum (REF §3.3.4, §3.9.1, §5.2).
**Description:** Wrap `@ricky0123/vad-web` (Silero) to emit `speech_start`/`speech_end`
with a ~300 ms pre-roll buffer (REF §5.2). On `speech_end`, hand the full buffered
utterance to the send path. Also implement **push-to-talk** mode (record between button
down/up) as the simpler/guaranteed path, plus a 15 s manual-speak timeout (REF §5.2).
Enforce the **≥0.5 s minimum** — drop shorter utterances client-side before sending
(REF §3.3.4).
**Inputs:** AudioCapture stream (FE-7).
**Outputs:** `VadSegmenter` module + recording-mode toggle (always-listen vs PTT).
**Acceptance criteria:** in PTT mode, press→speak→release sends exactly one utterance;
in VAD mode, a pause ends the utterance and sends once; utterances <0.5 s are not sent;
pre-roll prevents onset clipping.
**Edge cases:** utterance shorter than minimum (drop, REF §3.3.4); manual-speak 15 s
timeout flush mid-speech (REF §5.2); VAD unsupported → fall back to PTT.
**Open questions:** OQ-4 — VAD threshold/min-silence tuning (desktop uses 0.3 / 800 ms —
REF §5.2; start there, tune by testing).

---
**Task ID:** FE-9
**Title:** Voice send path — one binary frame per utterance
**Depends on:** FE-8, FE-3
**Backend endpoint(s)/contract used:** binary mic frame (REF §3.3.4); voice→`transcript`
event (REF §3.4).
**Description:** Wire VadSegmenter output to ConnectionManager: send each complete
utterance as **exactly one binary WebSocket message** (never per-frame — the implicit-
interrupt logic fires per binary frame during "speaking", REF §3.3.4 caveat / #6). Render
the returned `transcript` event as the user bubble (voice path echoes transcript — REF §3.4, #7).
**Inputs:** utterance buffers (FE-8), connection (FE-3).
**Outputs:** voice send action + transcript-driven user bubble.
**Acceptance criteria:** one utterance → one binary frame → one `transcript` event →
streamed assistant response; no self-interrupt loop occurs; user bubble text comes from
the `transcript` event (not local echo).
**Edge cases:** utterance during "speaking" correctly triggers server barge-in exactly
once (REF §5.4); never split an utterance across frames (#6); ensure ≥16000 bytes (FE-8 gate).
**Open questions:** none.

### Phase 3 — Interrupts / barge-in

---
**Task ID:** FE-10
**Title:** InterruptController + local playback flush
**Depends on:** FE-6, FE-9, FE-5
**Backend endpoint(s)/contract used:** implicit interrupt (voice/text), explicit
`{type:"interrupt"}`, `llm_text_chunk{final:true}`, `status` (REF §3.6, §3.3.3, §5.4).
**Description:** On any new input while the assistant is speaking — new voice utterance,
new `text_input`, or an explicit Interrupt button — **flush the AudioPlayer immediately**
(drop queued frames + stop source, REF §5.4). For the explicit button, also send
`{type:"interrupt"}`. Close the current bubble cleanly on the resulting `final:true`; apply
`status` events (REF §3.6).
**Inputs:** AudioPlayer.flush (FE-6), send paths (FE-5/FE-9).
**Outputs:** `InterruptController` + Interrupt button.
**Acceptance criteria:** speaking over TTS (voice or text) stops local audio instantly and
begins the new turn; explicit interrupt returns UI to `listening` via the `status` event;
no stale audio resumes after interrupt (REF §5.4); bubble closes without leaving a dangling
open bubble.
**Edge cases:** interrupt while idle → spurious `final:true` must not open/close a phantom
bubble (REF §3.9.5); already-queued frames must be dropped (REF §5.4); ~100 ms server
interrupt-detection latency (REF #9) — don't assume instant server-side stop.
**Open questions:** none.

---
**Task ID:** FE-11
**Title:** Wire audio flush into all preemption paths
**Depends on:** FE-10
**Backend endpoint(s)/contract used:** REF §3.6 (all three barge-in triggers).
**Description:** Ensure every path that preempts a response — typed send (FE-5), voice
send (FE-9), explicit interrupt (FE-10) — calls `AudioPlayer.flush()` locally, matching
the desktop's `playback.stop()` on manual-speak/typed/interrupt (REF §3.6, §3.3.2).
**Inputs:** all send actions.
**Outputs:** consistent flush wiring (no new module).
**Acceptance criteria:** typing while assistant speaks stops audio; sending voice while
speaking stops audio; explicit interrupt stops audio — all within ~20 ms.
**Edge cases:** double-flush (idempotent); flush with empty queue (no-op).
**Open questions:** none.

### Phase 4 — Error states / polish

---
**Task ID:** FE-12
**Title:** Playback-done inference + speaking-status clearing
**Depends on:** FE-6, FE-4
**Backend endpoint(s)/contract used:** no end-of-audio signal (REF §3.5, #4); text
`final:true` (REF §3.5).
**Description:** Infer end of a turn's audio: consider playback complete when the audio
queue has drained AND `llm_text_chunk{final:true}` was received AND no new binary frame
arrived within a short idle window. Clear "speaking" status accordingly (REF §8).
**Inputs:** AudioPlayer queue state, final-chunk flag.
**Outputs:** completion heuristic + status update.
**Acceptance criteria:** "speaking" clears shortly after the last audio finishes, not while
audio is still queued; a text-only turn (no audio) still completes on `final:true`.
**Edge cases:** audio lagging text (REF #4) — don't clear "speaking" while frames still
queued; turn with zero audio frames.
**Open questions:** OQ-5 — idle-window duration (heuristic; start ~500 ms). Eliminated if BE-3 is implemented.

---
**Task ID:** FE-13
**Title:** TimeoutGuard for stuck "thinking"
**Depends on:** FE-4, FE-5
**Backend endpoint(s)/contract used:** total-LLM-failure produces no `final` chunk
(REF §3.7, §10, #5).
**Description:** After sending a request, arm a client-side timeout; if no
`llm_text_chunk` (and no `transcript` for voice) arrives within N seconds, surface a soft
error, close any open bubble, and re-enable input (recovers the hang the desktop client
lacks — REF §3.7, #5).
**Inputs:** send timestamps; inbound event stream.
**Outputs:** `TimeoutGuard` + soft-error UI.
**Acceptance criteria:** simulating a silent turn (no events) surfaces a soft error and
re-enables input within N seconds; a normal streamed turn cancels the timeout on first token.
**Edge cases:** slow-but-alive LLM (choose N generously — account for cold start, REF §9.4,
§10); first token vs first audio timing; cancel timeout on ANY relevant inbound event.
**Open questions:** OQ-6 — timeout value N (must exceed worst-case cold-start first-token;
REF §9.4/§10 give no hard number — start ~20 s, make configurable).

---
**Task ID:** FE-14
**Title:** Clear-conversation via reconnect (+ optional session_reset)
**Depends on:** FE-3
**Backend endpoint(s)/contract used:** `session_reset` is a no-op (REF #1, §3.3.5);
reconnect = fresh server session (REF §3.8, §7).
**Description:** Implement "Clear conversation" by **dropping and reopening the socket**
(server `cleanup()` clears history on disconnect — REF §3.8, §7), then re-running the
session_start handshake and clearing local bubbles. If BE-1 lands, optionally send
`session_reset` instead (no reconnect needed).
**Inputs:** ConnectionManager (FE-3).
**Outputs:** Clear button + reset flow.
**Acceptance criteria:** after Clear, server-side context is gone (a follow-up referencing
prior turns is not understood) and local transcript is empty; connection returns to `ready`.
**Edge cases:** clear mid-response (flush audio + close bubbles first); rapid clear presses
(debounce). **Do NOT** rely on bare `session_reset` unless BE-1 is confirmed deployed (#1).
**Open questions:** none (default path needs no backend change).

---
**Task ID:** FE-15
**Title:** HealthPanel + connection status indicator
**Depends on:** FE-1, FE-3
**Backend endpoint(s)/contract used:** `GET /health` (REF §4.1).
**Description:** Periodically fetch `/health` (always 200; inspect body — REF §4.1) and
render service/TTS status; show WebSocket connection state (connecting/ready/reconnecting).
**Inputs:** health URL (FE-1), ConnectionState (FE-3).
**Outputs:** status panel component.
**Acceptance criteria:** panel shows `status`, TTS engine states, and live WS state;
degraded TTS (e.g. `kokoclone_ja: unavailable`) renders without treating 200 as failure.
**Edge cases:** partial health body (fields depend on init — REF §4.1); health fetch fails
(network) → show "unreachable" without crashing; CORS is `*` so fetch is allowed (REF §3.1).
**Open questions:** none.

---

## 6. Cross-Cutting Concerns

- **Reconnect/retry:** ConnectionManager owns exponential backoff 1 s→30 s cap, mirroring
  the desktop (REF §3.8). Every reopen re-sends `session_start` because reconnect yields a
  **fresh server pipeline with empty history** (REF §3.8, §7). Input is disabled until
  `session_ack` (REF §3.2).
- **Error handling:** There are **no application-level error events** (REF §3.7); failed
  turns simply produce no output. The client compensates with TimeoutGuard (FE-13) and
  treats WS close **1011** as a recoverable error → reconnect (REF §3.7). `/health` is
  always 200 — inspect the body, never the status code (REF §4.1).
- **Loading/latency states:** Surface distinct UI for `thinking` (post-send, pre-first-token)
  and `speaking` (audio playing). Account for cold-start on the first request (Kokoro/e5
  lazy-load, first synthesis/RAG pays a one-time cost — REF §9.4) — don't let the timeout
  (FE-13) trip on the first request.
- **Barge-in consistency:** Every preemption path flushes local audio (FE-11) to match
  the desktop's `playback.stop()` (REF §3.6); the server also cancels in-flight synthesis
  (REF §5.4), but ~100 ms interrupt latency (REF #9) means the client must stop locally
  first, not wait for the server.
- **Language:** Always send `lang:"auto"`; the server is authoritative and may override
  `en`/`ja` (REF §3.3.2, #8). Never hardcode language. Strip any leaked `[Reply in ...]`
  boilerplate defensively (REF #15).
- **Audio format discipline:** Capture is **16 kHz**, playback is **24 kHz** — two different
  rates on one socket; handle each independently and never assume one rate for both (REF #12,
  §3.9.2–3).

---

## 7. Risks & Open Questions

| ID | Item | Blocks | Resolution needed |
|---|---|---|---|
| OQ-1 | No auth/origin control on WS or `/health`; CORS `*` (REF #13). Fine for LAN kiosk, unsafe for public internet. | Public deployment only (not Phases 0–4) | Stakeholder decision on deployment surface; if public, an auth layer is a separate project (see §8). |
| OQ-2 | Confirm every TTS engine emits identical 24 kHz mono PCM16 byte layout (REF §5.3 says yes for Kokoro/KokoClone) | FE-6 robustness | Verify KokoClone frame bytes if artifacts appear; inspect backend source only if artifacts occur. |
| OQ-3 | AudioWorklet vs ScriptProcessor for capture resampling | FE-7 (impl detail) | Default AudioWorklet; fallback if unsupported. Not a blocker. |
| OQ-4 | VAD threshold / min-silence tuning (desktop 0.3 / 800 ms — REF §5.2) | FE-8 quality | Start from desktop values; tune empirically. |
| OQ-5 | Playback-done idle-window duration (no `audio_end` signal — REF #4) | FE-12 accuracy | Heuristic ~500 ms; eliminated by BE-3. |
| OQ-6 | Response-timeout value N (must exceed worst-case cold-start first-token — REF §9.4/§10 give no hard number) | FE-13 correctness | Start ~20 s, make configurable; measure cold-start empirically. |
| R-1 | Mic resampling correctness (48 k→16 k) — wrong rate silently breaks STT (REF §3.9.2) | FE-7 | Tone-test in acceptance criteria. |
| R-2 | Audio reassembly of >64 KB WAVs / headerless slices (REF §5.3, #2) | FE-6 | Raw-PCM ring buffer approach chosen specifically to avoid this. |
| R-3 | Streaming small binary frames mid-utterance self-interrupts (REF #6) | FE-9 | Enforce one-binary-frame-per-utterance in FE-9 acceptance criteria. |

---

## 8. Out of Scope

- **Any change to STT, VAD-gating semantics, language detection, intent routing, RAG,
  search, prompt building, or TTS engine selection** — all server-authoritative (REF Golden
  rule, §6). The client only captures audio, sends control JSON, renders text, plays audio.
- **Authentication / authorization / origin control / rate limiting** for public-internet
  deployment (REF #13, OQ-1) — separate project; this plan targets a LAN/kiosk browser client.
- **Conversation persistence across reconnects** — server keeps history per-connection only
  and clears it on disconnect (REF #14, §7). No client-side persistence is added.
- **Backend changes BE-1..BE-4** beyond documenting them — Phases 0–4 ship with zero
  backend changes; BE-* are an optional follow-up gated on a backend owner (§2).
- **Desktop PyQt client** — left in place; this plan does not modify or remove it, and
  explicitly avoids backend framing changes (BE-2) that would break it (REF §5.3).
- **Opus audio** — the wire format is WAV/PCM16, not Opus, despite legacy docstrings
  (REF #3); no Opus handling is built.
- **VoiceVox / cosyvoice** — legacy compose drift, unused by current code (REF #10, §9.3);
  ignored.
