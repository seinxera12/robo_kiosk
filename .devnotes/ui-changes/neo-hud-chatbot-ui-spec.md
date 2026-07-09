# Neo-HUD Chatbot UI — Implementation Spec

**Target stack:** React + Vite
**Voice transport:** Full-duplex streaming STT/TTS over WebSocket (assumed already implemented on backend — this spec only covers what the frontend renders in response to socket events)
**Auth:** None (no login state to design for)
**Layout paradigm:** Control-room dashboard — multiple independent panels, not a single chat bubble column

---

## 1. Concept

Not a chat app that happens to be dark-themed. A **console** the user sits in front of, made of several live panels that all react to the same underlying event stream (mic input level, STT partials, LLM token stream, TTS playback, connection health). The chat transcript is just one panel among several — it does not dominate the screen.

Visual language: terminal / HUD / hacker-console. Monospace type for system data, thin 1px hairline borders with glow, scanline/grid background, everything reads as "instrumentation," not "messaging app."

---

## 2. Grid Layout

Use CSS Grid on a single `<div id="console-root">`, min viewport `1280×800`, degrading to a stacked single-column layout under `768px` (see §7 Responsive).

```
┌─────────────────────────────────────────────────────────────────┐
│ TOP BAR — session id / connection status / clock / mode toggle  │
├───────────────┬─────────────────────────────────┬───────────────┤
│               │                                   │               │
│  LEFT PANEL   │        CENTER PANEL              │  RIGHT PANEL  │
│  Waveform /   │        Conversation Transcript    │  System Log / │
│  Mic Input    │        (streaming text)           │  Agent Trace  │
│  Visualizer   │                                   │               │
│               │                                   │               │
├───────────────┴─────────────────────────────────┴───────────────┤
│ BOTTOM BAR — text input field / mic toggle / send / TTS controls│
└─────────────────────────────────────────────────────────────────┘
```

Grid definition (desktop):

```css
#console-root {
  display: grid;
  grid-template-columns: 280px 1fr 320px;
  grid-template-rows: 48px 1fr 72px;
  grid-template-areas:
    "topbar topbar topbar"
    "left   center right"
    "bottom bottom bottom";
  height: 100vh;
  gap: 1px; /* hairline seams between panels, background color shows through as grid lines */
  background: var(--grid-line-color);
}
```

Each panel is its own component, self-scrolling, with its own header strip (small caps label + live status dot).

---

## 3. Panel Specs

### 3.1 Top Bar (`<TopBar />`)
- Left: app wordmark / glyph (monospace, letter-spaced, e.g. `ARIA://`), small blinking cursor block after it.
- Center: connection state pill — `LIVE`, `CONNECTING`, `RECONNECTING`, `OFFLINE` — colored dot (green/amber/amber-pulse/red) + label. Driven by WebSocket `readyState`.
- Right: local clock (updates every second, monospace `HH:MM:SS`), and a mode toggle: `TEXT` / `VOICE` / `HYBRID` (segmented control, terminal-button style).

### 3.2 Left Panel — Input Visualizer (`<InputVisualizer />`)
Purpose: show mic is alive and listening, and show STT partial transcript forming in real time.

- Header: `MIC INPUT` + live level meter (small numeric dB or 0–100 bar next to label).
- Body: animated waveform/bar visualizer bound to live audio amplitude from the mic stream (Web Audio `AnalyserNode` → `getByteFrequencyData`, render as vertical bars, ~32–48 bars, canvas or SVG). Bars idle at low amplitude "breathing" animation when mic is open but silent; snap to real amplitude when speech detected.
- Below waveform: **STT partial line** — the in-progress transcription, rendered in a dimmer/italic monospace style, updates on every `stt_partial` socket event, replaced by the finalized line when `stt_final` arrives (which then gets pushed to the center transcript).
- States to implement explicitly:
  - `idle` (mic off / muted) — flatline, greyed out
  - `listening` (mic on, no speech) — low breathing animation
  - `speech_detected` — active waveform + partial text visible
  - `muted` — crossed-out mic icon, waveform frozen/greyed

### 3.3 Center Panel — Conversation Transcript (`<Transcript />`)
This is the actual chat log, styled as a terminal scrollback, not chat bubbles.

- Each turn rendered as a log line block, not a bubble:
  ```
  [12:04:31] USER   > what's the weather in kathmandu
  [12:04:32] ARIA   > checking local weather data...
  [12:04:33] ARIA   > it's 21°C and partly cloudy right now.
  ```
- User lines: one accent color (e.g. cyan), prefixed `USER >`.
- Assistant lines: a second accent color (e.g. magenta/amber), prefixed `ARIA >` (or product name), streamed token-by-token as they arrive (see §4 Streaming).
- Timestamps in a muted tertiary color, monospace, fixed-width so columns align.
- Auto-scroll to bottom on new content, but pause auto-scroll if user has manually scrolled up (classic "new messages ↓" pill reappears at bottom when paused).
- While assistant is generating: a blinking block cursor `▌` at the end of the in-progress line.
- While assistant is speaking (TTS playback): the currently-playing assistant line gets a subtle animated highlight (left border glow pulsing in time, or per-word highlight if word-boundary timing is available from TTS metadata — optional stretch, fallback to line-level highlight only).

### 3.4 Right Panel — System / Agent Trace (`<SystemTrace />`)
This is the "visual of the processes going on" — makes the app feel like a superAI interface instead of a chat box.

- Header: `SYSTEM TRACE`.
- Scrolling log of pipeline events, each a compact single line with a status glyph:
  ```
  ● socket connected
  ● mic stream opened
  ○ stt: listening
  ✓ stt: final transcript received (214ms)
  ● llm: request sent
  ▸ llm: streaming tokens...
  ✓ llm: response complete (1.8s, 312 tok)
  ● tts: synthesizing
  ▸ tts: streaming audio...
  ✓ tts: playback complete
  ```
- Map every real socket/event-bus event your backend already emits to one line here. Do not invent fake steps — only render events that actually fire (see §5 Event Contract). If backend doesn't emit a given granular event, omit that line rather than fabricate it.
- Color code by status: `○` pending/grey, `▸` active/amber (can pulse), `✓` done/green, `✗` error/red.
- This panel is purely a log renderer — no business logic — so it degrades gracefully if some events never come.

### 3.5 Bottom Bar — Composer (`<Composer />`)
- Text input, full width, monospace, terminal-prompt style prefix (`>` or `$`) inside the field.
- Mic toggle button (push-to-toggle, not push-to-talk, since it's full-duplex) — visually distinct active/inactive state (glow ring when live).
- Send button (or Enter key) for text.
- Small inline TTS mute/volume toggle for assistant voice output.
- Disabled/greyed send while `OFFLINE`/`CONNECTING`.

---

## 4. Streaming Behavior (maps directly to socket events — implement as pure event handlers, no polling)

| Event (assumed backend emits) | UI effect |
|---|---|
| `ws:open` | Top bar → `LIVE`; enable composer |
| `ws:close` / `ws:error` | Top bar → `RECONNECTING`/`OFFLINE`; disable send/mic |
| `mic:level` (periodic amplitude) | Left panel waveform bars update |
| `stt:partial` (text, incremental) | Left panel partial line updates in place |
| `stt:final` (text) | Left panel partial clears; pushed as new `USER >` line in center transcript |
| `llm:token` (incremental text chunk) | Append to current in-progress `ARIA >` line in center transcript, cursor stays at end |
| `llm:done` | Remove blinking cursor, finalize line, log `✓` in right panel |
| `tts:audio_chunk` (streamed audio) | Feed to `<audio>`/AudioBufferSourceNode queue for playback; mark transcript line as "speaking" |
| `tts:done` | Clear "speaking" highlight |
| any pipeline stage event | One line appended to `<SystemTrace />`, oldest lines scroll off past ~200 lines (virtualize or cap array) |

**Do not fabricate events the backend doesn't send.** If only `stt:final` exists (no partials), the left panel simply shows the waveform without a live partial line — that's fine, don't fake incremental text.

---

## 5. Event Contract (fill in with actual backend payload shapes before coding)

> ⚠️ Frontend agent: confirm these against the real WebSocket message schema before implementing. Placeholder shape below — replace field names to match backend.

```ts
type SocketEvent =
  | { type: "mic.level"; level: number } // 0-1
  | { type: "stt.partial"; text: string }
  | { type: "stt.final"; text: string; ts: number }
  | { type: "llm.token"; token: string }
  | { type: "llm.done"; ts: number; tokenCount: number; latencyMs: number }
  | { type: "tts.chunk"; audio: ArrayBuffer }
  | { type: "tts.done" }
  | { type: "error"; stage: string; message: string };
```

---

## 6. Visual Design Tokens

```css
:root {
  --bg-void: #05070a;          /* page background, near-black */
  --bg-panel: #0b0f14;         /* panel background */
  --grid-line-color: #10161d;  /* hairline seams */
  --accent-cyan: #4df3ff;      /* user / primary accent */
  --accent-magenta: #ff5ec4;   /* assistant accent */
  --accent-amber: #ffb454;     /* active/pending status */
  --accent-green: #4dff9f;     /* success/live status */
  --accent-red: #ff5c5c;       /* error/offline */
  --text-primary: #d8f3ff;
  --text-dim: #5b7280;
  --font-mono: "JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace;
}
```

- Font: monospace everywhere, no exceptions (including body copy) — this is a big part of the "terminal" read.
- Panel borders: `1px solid var(--grid-line-color)` with a subtle `box-shadow: inset 0 0 20px rgba(77,243,255,0.03)` for the glow.
- Background: very subtle CSS scanline or dot-grid texture at ~3% opacity behind everything (pure CSS `repeating-linear-gradient`, no images needed).
- Motion: prefer `transform`/`opacity` transitions, keep under 200ms for state changes, use pulsing glow (`animation`) sparingly for "active" indicators only — avoid animating everything or it reads as noisy rather than futuristic.
- Respect `prefers-reduced-motion`: disable waveform idle-breathing animation and pulsing glows, keep functional state changes only.

---

## 7. Responsive Behavior

Below `1024px`: collapse to stacked layout —
```
topbar
center (transcript, tallest)
left (waveform, collapsed to a thin strip, expandable)
right (system trace, collapsed to a thin strip, expandable)
bottom (composer)
```
Left/right panels become collapsible accordions under the transcript on mobile rather than side columns, to keep the transcript primary on small screens.

---

## 8. Component Tree (suggested file structure)

```
src/
  components/
    ConsoleRoot.jsx
    TopBar.jsx
    InputVisualizer.jsx
    Transcript.jsx
    SystemTrace.jsx
    Composer.jsx
  hooks/
    useSocket.js          // owns the WebSocket, exposes event stream
    useMicStream.js        // getUserMedia + AnalyserNode, emits levels
    useAudioPlayback.js    // queues/plays streamed TTS audio chunks
  state/
    conversationStore.js   // transcript lines, in-progress line buffer
    systemTraceStore.js     // capped log array
  styles/
    tokens.css
    console.css
```

Keep `useSocket` as the single source of truth for connection state; all panels subscribe to it rather than each opening their own connection.

---

## 9. Explicitly Out of Scope (per current backend state)

- No auth/user accounts → no avatar, no login screen, no multi-session history sidebar.
- No fabricated pipeline steps — right panel only shows real emitted events.
- No word-level TTS highlighting unless backend actually sends word-timing metadata — ship line-level highlight first, treat word-level as a stretch goal gated on that data being available.
