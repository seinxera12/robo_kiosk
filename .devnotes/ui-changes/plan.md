Implementation Plan
Approach: Build the new console UI as new components in TypeScript alongside the old ones. Old components (App.tsx, Transcript, StatusBar, MicButton, TextInput, HealthPanel) stay as fallback until the new UI is verified, then get removed. All service/audio/store logic files are reused; only App.tsx entry swaps and one new store is added.

Step 1 — Design tokens + static grid shell
New src/styles/tokens.css (§6 tokens) and src/styles/console.css (grid §2, scanline bg, hairline panels, prefers-reduced-motion guards).
New src/components/ConsoleRoot.tsx — the CSS-grid container with the 5 panel areas + TopBar, and static shells for the other panels. No data wired. Verify it compiles and lays out.
Step 2 — TopBar wired to real connection state
TopBar.tsx: wordmark + blinking cursor; connection pill driven by useStore(s => s.connection) mapping the real 5 states (disconnected/connecting/connected/ready/reconnecting) → LIVE/CONNECTING/RECONNECTING/OFFLINE colors; live HH:MM:SS clock; mode segmented control (TEXT/VOICE/HYBRID) as local UI state gating which panels are emphasized.
Step 3 — Transcript panel (terminal scrollback)
Transcript.tsx (new, console-styled): reads bubbles from the existing store, renders [HH:MM:SS] USER > / ARIA > log lines with fixed-width timestamps, cyan/magenta accents, blinking ▌ on the open assistant bubble. Auto-scroll with "manually scrolled up → new-messages pill" pause behavior. Text send path already works via SessionController.sendText.
Note: bubbles currently have no timestamp field. I'll add a ts at creation in the store (additive, non-breaking) rather than fake times at render.
Step 4 — InputVisualizer (local Web Audio, no partials)
useMicLevel hook: attach an AnalyserNode to the existing AudioCapture MediaStream (local only), getByteFrequencyData → 32–48 bars. Idle "breathing" when recording==='alwaysListen'/mic open & silent; active on amplitude; greyed flatline when recording==='idle'.
Show the last final transcript as a brief flash (no partial line — flagged above). States: idle/listening/speech_detected/muted derived from recording + level.
Step 5 — SystemTrace + new systemTraceStore
New src/store/systemTraceStore.ts: capped (~200) array with append, useSyncExternalStore binding.
Hook trace emission into eventDispatch.ts (the one existing choke point where server events become state) — append a line per real event only: session_ack → "socket ready", transcript → "stt: final received", first token → "llm: streaming", final → "llm: complete", audio frame → "tts: audio" (throttled), status transitions. Color glyphs per §3.4. Also connection open/close from ConnectionManager. No invented stages.
Step 6 — Composer + TTS control
Composer.tsx: terminal-prompt text field (reuses sendText), mic toggle button with glow ring bound to VoiceController (reuses PTT + always-listen), Send disabled while not ready. TTS mute/volume toggle wired to AudioPlayer (add a setMuted/setVolume if not present — check AudioPlayer first; adapt, don't rewrite). "Speaking" highlight on the transcript line driven by PlaybackTracker/audio frames + tts done.
Step 7 — Responsive collapse (§7)
CSS media queries <1024px: stack to topbar / transcript / collapsible left & right accordions / composer.
Step 8 — Swap entry point, then remove old UI
Point App.tsx (or main.tsx) at ConsoleRoot.
Run through the preserve-functionality checklist (text send/stream, voice start/stop, TTS playback, reconnect, error toasts→SystemTrace/soft-error, keyboard/a11y).
Only after verification: delete old Transcript/StatusBar/MicButton/TextInput (keep HealthPanel logic, re-host it in TopBar/SystemTrace). Keep any I can't fully verify (e.g. voice, if no mic in test env) marked deprecated rather than deleted.
Explicitly NOT doing
No backend changes, no new WS event types, no dependency upgrades, no reformatting unrelated files.
No STT partial line, no mic-level socket event, no fabricated pipeline stages, no word-level TTS highlight (all gated on data the backend doesn't send).
Two decisions worth your call before I build:

AskUserQuestion
OUT
Your questions have been answered: "The spec assumes STT partials, a mic:level socket event, and granular pipeline events — none of which the backend actually emits. How should I handle these missing pieces?"="Adapt to real events (Recommended)", "How aggressively should I retire the old UI once the new console is verified?"="Delete after verification (Recommended)". You can now continue with these answers in mind.
Both confirmed: adapt to real events (no fabrication), and delete old UI after verification.

The plan above stands as written — it already reflects both choices. To summarize what I'll do when you give the go-ahead to implement:

Tokens + static grid — tokens.css, console.css, ConsoleRoot.tsx
TopBar — real 5-state connection pill, clock, mode toggle
Transcript — terminal scrollback from existing bubbles store (+ additive ts field), scroll-pause pill
InputVisualizer — local Web Audio AnalyserNode off the existing mic stream; no faked STT partial line
SystemTrace — new systemTraceStore + trace emission hooked into eventDispatch.ts, only real events
Composer — reuses sendText/VoiceController/AudioPlayer, TTS mute/volume, speaking highlight
Responsive collapse (<1024px)
Swap entry → verify preserve-functionality checklist → delete old UI
All backend contracts, the WebSocket layer, mic capture, VAD, and audio playback are reused untouched — this is a presentational reskin plus one new store, not a pipeline rebuild.

Two things I want to confirm I have license to do when implementing (both additive, non-breaking):

Add a ts: number field to Bubble at creation time (for aligned timestamps) — the store is the only writer, so it's safe.
Check AudioPlayer for existing mute/volume; if absent, add setMuted/setVolume methods (adapt, not rewrite).
Want me to proceed with Step 1, or would you like to review/adjust the plan first? I can also save this plan to memory as project context if you'd like it to survive across sessions.