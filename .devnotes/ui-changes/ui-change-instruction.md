You are implementing a UI redesign in an existing React + Vite codebase. Full target spec is in neo-hud-chatbot-ui-spec.md (attached/provided). Follow it exactly for layout, components, tokens, and event contract.

Ground rules


Audit before touching anything. First, map the current codebase: locate the existing chat UI component(s), the WebSocket/socket connection logic, mic/audio handling, and any state management (context, redux, zustand, etc). List every file you intend to touch before editing any of them. Do not proceed to implementation until this audit is done.
Do not change backend contracts. Do not rename, add, or remove WebSocket event types, payload fields, or API endpoints. If the spec's placeholder event shapes (§5) don't match what the backend actually sends, adapt the spec's field names to the real ones — do not change the backend to match the spec.
Isolate the new UI from the old. Build the new components (ConsoleRoot, TopBar, InputVisualizer, Transcript, SystemTrace, Composer, and the hooks/stores per §8) alongside the existing chat UI first, not in-place. Only swap the route/entry point to the new UI once it's functionally verified. This keeps the old UI as a fallback/reference during the transition and makes the diff easy to review.
Reuse existing logic, don't rewrite working code. If there's already a working WebSocket hook, mic capture hook, or audio playback logic, wrap/adapt it into the new useSocket / useMicStream / useAudioPlayback shape rather than rewriting the underlying logic from scratch. The goal is a visual and structural redesign, not a rebuild of the streaming pipeline. Flag it if you find working logic that's genuinely incompatible with the new structure, rather than silently discarding it.
No fabricated behavior. Per spec §4 and §9: only render UI states for events the backend actually emits. If you're unsure whether an event exists, check the backend/socket code or ask — don't guess and stub it with fake data.
Preserve existing functionality checklist. Before marking this done, confirm all of the following still work exactly as before:

Sending a text message and receiving a streamed response
Starting/stopping voice input
Hearing streamed TTS audio output
Reconnect behavior if the socket drops
Any existing error states/toasts
Any keyboard shortcuts or accessibility behavior currently present



Incremental, reviewable steps. Implement in this order, confirming each step compiles and runs before moving to the next:

Design tokens + base grid layout (static, no data wired) — ConsoleRoot, TopBar, panel shells
useSocket hook wired to real backend, connection status reflected in TopBar
Transcript wired to real message send/receive (text mode working end to end)
InputVisualizer wired to real mic stream + STT events
SystemTrace wired to real pipeline events
Composer mic toggle + TTS playback wired end to end
Responsive collapse behavior (§7)
Remove old UI only after all of the above are verified working



Don't touch unrelated code. No dependency upgrades, no linting/formatting sweeps across unrelated files, no refactors outside the components/hooks listed in the spec, unless required to complete this task.
When something in the spec conflicts with how the backend actually works, stop and flag the mismatch rather than silently inventing a workaround.


Deliverable


New UI matching the spec, behind a clean swap of the app entry point.
Old chat component(s) either removed (if step 8's checklist passes) or left clearly marked as deprecated/unused if you're not fully confident — don't delete working code you haven't verified a replacement for.
A short summary of: files added, files modified, files removed, and which items in the "preserve existing functionality" checklist you personally verified vs couldn't verify (e.g. no test env for voice).