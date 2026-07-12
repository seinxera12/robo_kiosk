#!/usr/bin/env python3
"""
End-to-end WebSocket probe — drives the real voice-server pipeline.

Uses the `text_input` control message (see server/pipeline.py) to trigger the
full LLM -> TTS chain WITHOUT needing a microphone or audio/STT. This is the
single best "is the deployment actually working?" test: it exercises
voice-server -> LiteLLM (LLM) -> Kokoro (TTS) and returns both the streamed
text and the synthesized audio bytes.

Protocol exercised:
  send   {"type":"session_start", "kiosk_id":..., "kiosk_location":...}
  expect {"type":"session_ack","status":"ready"}
  send   {"type":"text_input","text": "<prompt>", "lang":"auto"}
  expect stream of {"type":"llm_text_chunk","text":..,"final":false}
         then      {"type":"llm_text_chunk","text":"","final":true}
  expect binary frames = TTS audio (PCM)

Run LOCALLY on the server:
  python test_ws.py --url ws://127.0.0.1:8765/ws
Run REMOTELY through the funnel:
  python test_ws.py --url wss://<machine>.<tailnet>.ts.net:8443/ws

Requires: pip install websockets
"""
import argparse
import asyncio
import json
import sys
import time

try:
    import websockets
except ImportError:
    print("Missing dep: pip install websockets"); sys.exit(2)


async def run(url: str, prompt: str, timeout: float) -> int:
    print(f"→ connecting {url}")
    try:
        async with websockets.connect(url, open_timeout=15, max_size=None) as ws:
            print("  ✓ connected")

            # 1) session_start -> session_ack
            await ws.send(json.dumps({
                "type": "session_start",
                "kiosk_id": "deploy-test",
                "kiosk_location": "ci",
            }))
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if ack.get("type") == "session_ack" and ack.get("status") == "ready":
                print("  ✓ session_ack ready")
            else:
                print(f"  ✗ unexpected first message: {ack}"); return 1

            # 2) text_input -> LLM stream + TTS audio
            print(f"  → text_input: {prompt!r}")
            await ws.send(json.dumps({"type": "text_input", "text": prompt, "lang": "auto"}))

            reply, audio_bytes, got_final = [], 0, False
            first_at = None
            t0 = time.time()
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    print("  ✗ timed out waiting for response"); break

                if isinstance(msg, (bytes, bytearray)):
                    audio_bytes += len(msg)
                    continue
                data = json.loads(msg)
                if data.get("type") == "llm_text_chunk":
                    if data.get("final"):
                        got_final = True
                        # Give TTS a moment to flush remaining audio frames.
                        drain_deadline = time.time() + 5
                        while time.time() < drain_deadline:
                            try:
                                extra = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                if isinstance(extra, (bytes, bytearray)):
                                    audio_bytes += len(extra)
                            except asyncio.TimeoutError:
                                break
                        break
                    tok = data.get("text", "")
                    if tok and first_at is None:
                        first_at = time.time() - t0
                    reply.append(tok)
                    sys.stdout.write(tok); sys.stdout.flush()

            dt = time.time() - t0
            text = "".join(reply).strip()
            print("\n  ── results ──")
            print(f"  {'✓' if text else '✗'} LLM text ({len(text)} chars): {text[:120]!r}")
            print(f"  {'✓' if got_final else '✗'} received final chunk")
            print(f"  {'✓' if audio_bytes else '✗'} TTS audio: {audio_bytes} bytes")
            if first_at is not None:
                print(f"  ttft={first_at:.2f}s  total={dt:.2f}s")

            ok = bool(text) and got_final and audio_bytes > 0
            print(f"\n  {'PASS — full LLM→TTS pipeline works' if ok else 'FAIL — see markers above'}")
            return 0 if ok else 1
    except Exception as e:
        print(f"  ✗ connection/protocol error: {e}")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    ap.add_argument("--prompt", default="In one short sentence, what is a kiosk?")
    ap.add_argument("--timeout", type=float, default=45.0,
                    help="per-message wait for the LLM stream")
    args = ap.parse_args()
    return asyncio.run(run(args.url, args.prompt, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
