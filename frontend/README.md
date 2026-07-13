# Voice Kiosk — Browser Frontend

Browser client replacing the PyQt6 desktop kiosk. Speaks the single-WebSocket
protocol with **zero backend changes**, and ships as a standalone `kiosk.exe`
that serves the UI locally and opens it in the user's browser.

The deployed voice-server is reachable **only** through a Tailscale Funnel — one
TLS origin fronts the whole service, so `/ws` and `/health` share a host and
port. See `../.devnotes/deployment/FRONTEND_INTEGRATION.md` for the protocol
contract.

## Setup (development)

```bash
cd frontend
npm install
cp .env.example .env   # points at the funnel by default
npm run dev            # dev server on :5173
```

Build & test:

```bash
npm run build          # tsc -b && vite build
npm test               # vitest (unit tests)
```

## Packaging the kiosk executable

```bash
npm run package        # build + bundle into release/kiosk.exe
```

Produces `release/kiosk.exe` (~82 MB — Node's Single Executable Application
format embeds the Node runtime). Running it starts a loopback-only static server
and opens the default browser at it. No install, no Node required on the target
machine.

**Build on the platform you are shipping to** — SEA cannot cross-compile; the
exe is made from the running `node` binary.

Two constraints worth knowing before changing any of this:

- **The UI is served over `http://127.0.0.1`, never `file://`.** Loopback is a
  *secure context*, so `getUserMedia` works; `file://` is not, so the mic would
  be permanently unavailable. ES-module imports and `AudioWorklet.addModule()`
  are also blocked from `file://`. Serving locally is what makes the exe work.
- **The launcher entry point is CommonJS** (`launcher/launcher.cjs`). SEA embeds
  the source text and runs it through the CJS embedder, so an ESM entry fails at
  startup with "Cannot use import statement outside a module".

The server URL is **baked in at build time** from `.env.production`, so the exe
is tied to one backend: repointing it at a different server means rebuilding and
redistributing. `launcher/build.mjs` refuses to package a bundle whose WebSocket
URL resolves to loopback, which is the signature of a missing `.env.production`.

## Configuration

`.env.production` is the build input for the packaged exe and **is committed**.
`.env` (gitignored) overrides it for local dev.

| Var | Value | Purpose |
|---|---|---|
| `VITE_SERVER_WS_URL` | `wss://<host>:<port>/ws` | WebSocket — the entire API |
| `VITE_HEALTH_URL` | `https://<host>:<port>/health` | Readiness poll |
| `VITE_KIOSK_ID` | `kiosk-01` | `session_start` |
| `VITE_KIOSK_LOCATION` | `Floor 1 Lobby` | `session_start` |

Must be `wss://` — the funnel is TLS-only. If unset, config falls back to
`window.location`, which is correct only when the server itself serves the page;
in a packaged build that would point at the launcher, hence the build guard.

## Logs

The packaged kiosk writes **`kiosk.log` next to the exe** (the path is printed on
startup). It is JSON Lines — one record per line:

```
{"ts":1783928810820,"level":"info","channel":"ws","msg":"socket open"}
{"ts":1783928810960,"level":"debug","channel":"ws","msg":"recv session_ack"}
{"ts":1783928812280,"level":"debug","channel":"ws","msg":"recv audio","data":{"bytes":65536}}
```

The browser cannot write files, so the UI POSTs batched records to the launcher
(`POST /__log`), which appends them. Channels: `app` (boot/config/crashes), `ws`
(**every frame in and out**), `health`, `audio`, `ui`, `launcher`.

Filter with `jq`, e.g. only the wire traffic:

```bash
jq -c 'select(.channel=="ws")' kiosk.log
jq -c 'select(.level=="error")' kiosk.log
```

Two things to know:

- **Audio is logged by byte count, never by content.** A single TTS reply is
  ~70 KB; writing the bytes out would produce megabytes per turn and tell you
  nothing readable.
- **In `npm run dev` there is no launcher**, so the POSTs fail and logging goes
  quiet after the first attempt. That is deliberate — in dev, DevTools *is* the
  log. `kiosk.log` only exists for the packaged exe.

Rotates at 5 MB (keeping one `kiosk.log.1`); appends across restarts, so a crash
does not destroy the evidence from the run before it.

## Readiness gate

`/health` returns `{"status":"healthy"}` **while the models are still loading**,
so `status` alone is not a readiness signal — the per-component states under
`components` (`stt`, `llm_chain`, `rag`) are. The mic stays disabled and the
connection pill reads `WARMING` until all three report `ready`; the first launch
after a deploy can sit there for a while.

`tts` is deliberately excluded from the gate: a degraded engine (the live server
currently reports `kokoclone_ja: not_initialized`) is reduced capability, not
failure, and must not disable the kiosk.

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
