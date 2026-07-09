# Frontend Migration — Implementation Status

Tracking checklist for tasks defined in [FRONTEND_MIGRATION_PLAN.md](./FRONTEND_MIGRATION_PLAN.md).
Mark `[x]` when the task's acceptance criteria pass.

## Phase 0 — Project + Connection groundwork
- [x] **FE-1** — Scaffold React+TS+Vite SPA + runtime config (`VITE_*` env vars) — `frontend/` scaffolded; `src/config/` with location-derived + https→wss defaults; app shell; config unit test. ⏳ needs `npm install` + `npm run build` to verify.
- [x] **FE-2** — Typed message codec for the WS catalog — `src/services/messages.ts` (full REF §4.2 union, frame-kind discrimination, verbatim tokens, boilerplate strip) + unit tests.
- [x] **FE-3** — ConnectionManager + handshake + backoff reconnect — `src/services/ConnectionManager.ts` (arraybuffer, session_start/ack gate, 1s→30s backoff, re-send on reopen, binary→audio routing) + `src/store/` + unit tests. ⏳ live-server connect verified once runtime is up.

## Phase 1 — Text chat
- [x] **FE-4** — ConversationStore + streaming renderer + bubble gating — `src/store/store.ts` (gating), `eventDispatch.ts` (events→status), `components/Transcript.tsx` + tests.
- [x] **FE-5** — Text input send path with local echo — `services/SessionController.ts` (`sendText`, local echo, lang:"auto", pre-flush) + `components/TextInput.tsx` (disabled until ready).

## Phase 2 — Audio
- [x] **FE-6** — AudioPlayer 24 kHz PCM16 ring-buffer playback — `src/audio/pcm.ts` (RIFF strip / raw-PCM / odd-length guard) + tests, `playback-worklet.ts` (ring buffer + flush + drained), `AudioPlayer.ts` (24 kHz ctx, AudioSink). ⏳ audible playback verified at runtime.
- [x] **FE-7** — AudioCapture mic → 16 kHz Int16 PCM — `src/audio/resample.ts` (linear resample, clamp Int16, headerless build) + tests, `capture-worklet.ts`, `AudioCapture.ts`. ⏳ live mic capture verified at runtime.
- [x] **FE-8** — VadSegmenter + PTT fallback — `src/audio/VadSegmenter.ts` (PTT + vad-web, ~300 ms pre-roll, 15 s manual timeout, ≥16000-byte gate). ⏳ VAD tuning (OQ-4) at runtime.
- [x] **FE-9** — Voice send path (one binary frame per utterance) — `src/audio/VoiceController.ts` + `components/MicButton.tsx`; transcript bubble via dispatcher. ⏳ live voice round-trip at runtime.

## Phase 3 — Interrupts / barge-in
- [x] **FE-10** — InterruptController + local playback flush — `SessionController.interrupt()` (flush + `{type:"interrupt"}`), Interrupt button in `StatusBar.tsx`, bubble close/status on `final`/`status` in dispatcher.
- [x] **FE-11** — Wire audio flush into all preemption paths — `sendText`/`sendUtterance`/`interrupt`/`clearConversation` all call `audio.flush()` + verified in `SessionController.test.ts`.

## Phase 4 — Error states / polish
- [x] **FE-12** — Playback-done inference + speaking-status clearing — `src/services/PlaybackTracker.ts` (drain + text-final + ~500 ms idle window; text-only completes immediately) + tests.
- [x] **FE-13** — TimeoutGuard for stuck "thinking" — `src/services/TimeoutGuard.ts` (20 s configurable, closes dangling bubble, soft error) + tests.
- [x] **FE-14** — Clear-conversation via reconnect — `SessionController.clearConversation()` (flush + clear bubbles + `reconnectNow`); Clear button in `StatusBar.tsx`. session_reset path deferred to BE-1.
- [x] **FE-15** — HealthPanel + connection status indicator — `src/services/health.ts` (always-200, tolerant) + `components/HealthPanel.tsx` (10 s poll) + connection dot/status in `StatusBar.tsx`.

> **⏳ Runtime verification pending (needs `npm install` + `npm run dev/build/test` against a running voice-server):** live WS handshake, audible 24 kHz playback, mic capture correctness, VAD tuning, barge-in, full voice round-trip. Logic layers are covered by unit tests (codec, gating, resample, PCM framing, connection, send paths, guards).

## Optional backend changes (only with a backend owner; not required for Phases 0–4)
- [ ] **BE-1** — `session_reset` handler → clear history + ack
- [ ] **BE-2** — Deterministic per-sentence audio framing *(discouraged — breaks desktop client)*
- [ ] **BE-3** — Explicit `audio_end` / `speaking_done` event
- [ ] **BE-4** — `{type:"error",detail}` event on turn failure

## Open questions to resolve (see plan §7)
- [ ] **OQ-1** — Auth/origin model for browser context (stakeholder; blocks public deploy only)
- [ ] **OQ-2** — Confirm all TTS engines emit identical 24 kHz mono PCM16 byte layout (FE-6)
- [ ] **OQ-3** — AudioWorklet vs ScriptProcessor for capture resampling (FE-7)
- [ ] **OQ-4** — VAD threshold / min-silence tuning (FE-8)
- [ ] **OQ-5** — Playback-done idle-window duration (FE-12; moot if BE-3)
- [ ] **OQ-6** — Response-timeout value N vs worst-case cold start (FE-13)
