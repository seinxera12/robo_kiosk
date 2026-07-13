# Frontend Integration Brief — Voice Kiosk Backend

Everything the UI needs to talk to the deployed backend. The backend is a single
service; you do **not** talk to the LLM/STT services directly — the voice-server
fronts all of them.

## 1. Endpoints

The server is exposed **only** through a Tailscale Funnel (public HTTPS/TLS).
There is no plain-HTTP or raw-IP access.

| Purpose | URL |
|---|---|
| WebSocket (everything) | `wss://<machine>.<tailnet>.ts.net:<port>/ws` |
| Health / readiness | `https://<machine>.<tailnet>.ts.net:<port>/health` |

Config (`frontend/.env`):
```
VITE_SERVER_WS_URL=wss://<machine>.<tailnet>.ts.net:<port>/ws
VITE_HEALTH_URL=https://<machine>.<tailnet>.ts.net:<port>/health
```
Must be `wss://` (not `ws://`) — the funnel is TLS-only. CORS is open by default.

`GET /health` → `200` with `{"status":"healthy", "components":{"stt":"ready","llm_chain":"ready","rag":"ready"}, "tts":{...}}`.
Use it for a pre-flight/"backend up?" check. It can return `healthy` while a
component is still loading, so check `components` before enabling the mic.

## 2. The WebSocket is the whole API

One connection carries control JSON, audio in, and audio out. There are no REST
endpoints for chat.

### Connect → handshake
On open, send:
```json
{"type":"session_start","kiosk_id":"kiosk-01","kiosk_location":"Floor 1 Lobby"}
```
Wait for:
```json
{"type":"session_ack","status":"ready"}
```
Don't send anything else until you get the ack.

### Client → Server

| Message | Payload |
|---|---|
| **Audio (binary)** | Raw **PCM16, 16 kHz, mono** frames. Send as binary WS frames while the user speaks. No JSON wrapper. |
| `text_input` | `{"type":"text_input","text":"...","lang":"auto"}` — skips speech; drives LLM+TTS directly. Great for a text box / testing. |
| `interrupt` | `{"type":"interrupt"}` — barge-in; cancels in-flight LLM+TTS. |

> The server **re-detects language itself** from the text. `lang` is a hint only —
> send `"auto"`. Don't rely on the client's guess.

### Server → Client

| Message | Payload | Use |
|---|---|---|
| `session_ack` | `{"status":"ready"}` | Handshake complete |
| `transcript` | `{"text":"...","lang":"en"\|"ja","final":true}` | Show what the user said |
| `llm_text_chunk` | `{"text":"<token>","final":false}` | **Streaming** reply — append tokens as they arrive |
| `llm_text_chunk` | `{"text":"","final":true}` | End of reply (empty text + `final:true`) |
| `status` | `{"state":"listening"}` | Mic/UI state |
| **Audio (binary)** | **WAV bytes, 24 kHz mono PCM16**, chunked into ≤64 KB frames | Assistant's spoken reply — buffer & play |

## 3. Two things that will bite you

1. **Audio in ≠ audio out.** You send **raw PCM16 @ 16 kHz**; you receive **WAV @ 24 kHz**. Don't reuse one pipeline for both.
2. **Reassemble the audio.** TTS output is split into ≤64 KB binary frames. Concatenate consecutive binary frames into one buffer before playing — a single frame is not a playable file.

## 4. Minimal flow

```js
const ws = new WebSocket(import.meta.env.VITE_SERVER_WS_URL);
ws.binaryType = "arraybuffer";

ws.onopen = () => ws.send(JSON.stringify({
  type: "session_start", kiosk_id: "kiosk-01", kiosk_location: "Floor 1 Lobby"
}));

let audio = [];
ws.onmessage = (e) => {
  if (e.data instanceof ArrayBuffer) { audio.push(e.data); return; }  // TTS chunk
  const m = JSON.parse(e.data);
  switch (m.type) {
    case "session_ack":     enableMic(); break;
    case "transcript":      showUser(m.text); break;
    case "llm_text_chunk":
      if (m.final) { play(new Blob(audio, {type:"audio/wav"})); audio = []; }
      else appendAssistant(m.text);
      break;
    case "status":          setState(m.state); break;
  }
};

// mic: send raw PCM16 @16kHz binary frames
ws.send(pcm16Buffer);
// barge-in
ws.send(JSON.stringify({ type: "interrupt" }));
```

## 5. Notes

- **Mic requires a secure context** — `https://` (the funnel gives you this) or `localhost`. `getUserMedia` will not work over plain HTTP.
- **Backend does the routing:** STT, LLM (via an internal LiteLLM proxy), and TTS all live behind the voice-server. The frontend never sees or configures them.
- **First connection after a deploy may be slow** — the server pre-loads models at startup. Poll `/health` until `components` are `ready`.
- Text and audio for the same reply arrive concurrently and incrementally — text tokens stream in while TTS audio for earlier text is still being generated. Render text as it arrives; don't wait for audio.