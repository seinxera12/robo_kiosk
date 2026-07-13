# Frontend Deployment — building and shipping `kiosk.exe`

Companion to `FRONTEND_INTEGRATION.md` (which describes the wire protocol). This
covers producing the distributable executable and what it assumes.

## What the exe is

`kiosk.exe` is the whole frontend in one file: a Node Single Executable
Application (SEA) with the built `dist/` embedded as assets. Running it:

1. binds a static file server on `127.0.0.1:5180` (walks upward if taken),
2. opens the default browser at it,
3. serves the UI, which connects out to the remote voice-server over `wss://`.

It is **not** a server deployment. It is a client. The voice-server stays remote.

## Build

```bash
cd frontend
npm install
npm run package        # -> frontend/release/kiosk.exe  (~82 MB)
```

Requirements:

- **Build on the target platform.** SEA makes the exe from the running `node`
  binary, so a Windows exe must be built on Windows. There is no cross-compile.
- **Node 22+** on the build machine (SEA + `node:sea` asset API).
- `release/` is gitignored. Distribute the exe as a release asset, not in git.

The size is the embedded Node runtime, not the app (the UI bundle is ~180 KB).

## The server URL is baked in

`vite build` inlines `frontend/.env.production` into the bundle, so the exe is
bound to one backend:

```
VITE_SERVER_WS_URL=wss://ubuntu.tailcd8da4.ts.net:8443/ws
VITE_HEALTH_URL=https://ubuntu.tailcd8da4.ts.net:8443/health
```

**Changing the funnel hostname or port means rebuilding and redistributing the
exe.** That is the accepted trade for a zero-config binary; if it starts to hurt,
the alternative is a runtime config file read at launch, which requires moving
config off `import.meta.env` onto a runtime-injected global.

`launcher/build.mjs` fails the build if the bundle's WebSocket URL resolves to
loopback — the signature of a missing/ignored `.env.production`, which would
otherwise produce an exe that silently never connects.

## Logs

`kiosk.log`, written next to the exe (path printed on startup). JSON Lines, one
record per line, appended across restarts, rotated at 5 MB (one `kiosk.log.1`).

The browser cannot write files, so the UI batches records and POSTs them to the
launcher at `POST /__log`; the launcher appends them. Channels:

| Channel | What lands there |
|---|---|
| `launcher` | Process start/stop/crash — written by the exe itself |
| `app` | Boot (including the **resolved server URL**), uncaught errors, session end |
| `ws` | **Every frame in and out**: sends, receives, close codes, reconnect backoff |
| `health` | Readiness phase changes (`warming` → `ready`, unreachable) |
| `audio` | Mic capture and VAD failures |
| `ui` | User actions — text sent, spoke, barge-in, and *rejected* actions |

Useful when triaging:

```bash
jq -c 'select(.channel=="ws")'    kiosk.log   # the wire
jq -c 'select(.level=="error")'   kiosk.log   # what broke
jq -c 'select(.msg|test("recv"))' kiosk.log   # what the server sent
```

Deliberate limits:

- **Audio is recorded as a byte count, never as bytes.** One TTS reply is ~70 KB;
  logging the payload would produce megabytes per turn and be unreadable.
- **Logging can never break the kiosk.** Every failure path in the logger and the
  ingest handler is swallowed. Losing a log line beats taking down an unattended
  kiosk.
- **Errors flush immediately**, rather than waiting for the 1 s batch — they are
  the thing most likely to be followed by a crash that would lose the buffer.
- **Dev builds have no launcher**, so posts fail and logging goes quiet after the
  first attempt. In dev, DevTools is the log; `kiosk.log` is a packaged-exe
  feature.

A hard kill (`Stop-Process -Force`, power loss) writes no shutdown line — nothing
can intercept that. Everything logged before it is already on disk, because the
stream appends rather than buffering to the end.

## Design constraints (do not "simplify" these away)

**Serve over `http://127.0.0.1`, never `file://`.** Loopback is a *secure
context*; `file://` is not. From `file://` the kiosk would be broken three ways:
`getUserMedia` (the microphone) is refused outside a secure context, ES-module
imports are blocked by CORS on opaque origins, and `AudioWorklet.addModule()`
refuses to load — taking out capture and playback both. The local HTTP server is
what makes the app work at all.

**The launcher entry point must be CommonJS** (`launcher/launcher.cjs`). SEA
embeds the entry's *source text* and runs it through the CJS embedder; there is
no file on disk to infer ESM from. An `import` statement there fails at startup
with `Cannot use import statement outside a module`.

**Bind loopback only.** The launcher's server must never be reachable off-box.

## Readiness

The server answers `/health` with `status: "healthy"` while its models are still
loading, so the UI gates the microphone on `components.{stt,llm_chain,rag}` all
reporting `ready`, not on `status`. Until then the connection pill reads
`WARMING` and the mic is disabled. First launch after a deploy can sit in that
state for a while — this is expected, not a fault.

`tts` is excluded from the gate on purpose: the live server reports
`kokoclone_ja: not_initialized`, and treating a degraded TTS engine as failure
would leave the kiosk permanently disabled.

## Verified against the live funnel (2026-07-13)

- `GET /health` → 200, `Access-Control-Allow-Origin: *`, all three gated
  components `ready`.
- `wss://` upgrade through the funnel succeeds; `session_start` → `session_ack`.
- `text_input` streams `llm_text_chunk` tokens, then TTS audio arrives as binary
  frames **after** text `final:true` (70,844 B over 2 frames; first frame exactly
  65,536 B, matching the ≤64 KB chunking). Audio lags the token stream — a client
  that stops reading at text-final gets no audio.
- Packaged exe serves `index.html`, the JS bundle (correct `text/javascript`
  MIME), CSS, and the SPA fallback; the served bundle contains the funnel URLs.

Not verifiable from a shell, needs a human at the machine: microphone permission
prompt, audible TTS playback, and a live spoken turn end to end.
