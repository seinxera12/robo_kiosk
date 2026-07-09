# Voice Kiosk — Browser Frontend

Browser client replacing the PyQt6 desktop kiosk. Speaks the existing
single-WebSocket protocol (`ws://host:8765/ws`) with **zero backend changes**.
See `../.devnotes/ui-migration/FRONTEND_MIGRATION_PLAN.md` for the full plan and
`../.devnotes/ui-migration/implementation-status.md` for task status.

## Setup

```bash
cd frontend
npm install
cp .env.example .env   # optional; defaults derive from window.location
npm run dev            # dev server on :5173
```

Build & test:

```bash
npm run build          # tsc -b && vite build
npm test               # vitest (unit tests)
```

## Configuration (plan §3)

All optional; unset values derive from `window.location` (with `https`→`wss`).

| Var | Default | Purpose |
|---|---|---|
| `VITE_SERVER_WS_URL` | `ws://<host>:8765/ws` | WebSocket endpoint |
| `VITE_HEALTH_URL` | `http://<host>:8000/health` | Health poll |
| `VITE_KIOSK_ID` | `kiosk-01` | `session_start` |
| `VITE_KIOSK_LOCATION` | `Floor 1 Lobby` | `session_start` |

## Architecture (plan §4) — module → task map

| Module | Task | Notes |
|---|---|---|
| `src/config/` | FE-1 | env + location-derived config |
| `src/services/messages.ts` | FE-2 | typed WS catalog, verbatim tokens |
| `src/services/ConnectionManager.ts` | FE-3 | socket, handshake, backoff reconnect |
| `src/store/` + `eventDispatch.ts` | FE-4 | bubble gating, status mapping |
| `src/services/SessionController.ts` | FE-5/9/10/11/14 | send paths + flush wiring |
| `src/audio/pcm.ts` + `AudioPlayer.ts` + `playback-worklet.ts` | FE-6 | 24 kHz PCM16 ring-buffer playback |
| `src/audio/resample.ts` + `AudioCapture.ts` + `capture-worklet.ts` | FE-7 | 16 kHz Int16 capture |
| `src/audio/VadSegmenter.ts` | FE-8 | VAD + PTT, ≥0.5 s gate |
| `src/audio/VoiceController.ts` | FE-9 | one binary frame per utterance |
| `src/services/PlaybackTracker.ts` | FE-12 | infer end-of-audio |
| `src/services/TimeoutGuard.ts` | FE-13 | stuck-turn recovery |
| `src/services/health.ts` + `components/HealthPanel.tsx` | FE-15 | health poll + status |

## Key contract invariants (from REF)

- **Audio playback is raw 24 kHz PCM16**, not `decodeAudioData` per frame —
  the server splits WAVs >64 KB into headerless slices (REF §5.3, #2).
- **Mic must be exactly 16 kHz mono PCM16**; browser captures at 48 kHz and is
  resampled (REF §3.9.2). Wrong rate silently breaks STT.
- **One binary frame per complete utterance** — never per-frame, or the server
  self-interrupts (REF §3.3.4, #6).
- **Typed text is echoed locally**; only voice yields a `transcript` event
  (REF §3.3.2, #7).
- **Always send `lang:"auto"`**; server is authoritative (REF §3.3.2, #8).
- **Reconnect = fresh server session**; re-send `session_start` (REF §3.8).

## Verification status

Unit tests cover the pure/logic layers (codec, gating, resampling, PCM framing,
connection handshake/reconnect, send paths, guards). Runtime-only acceptance
criteria (audible playback, live mic capture, real-server handshake, barge-in)
require `npm run dev` against a running voice-server and are marked ⏳ in
`implementation-status.md`.
```
