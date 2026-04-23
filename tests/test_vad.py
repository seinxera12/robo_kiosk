#!/usr/bin/env python3
"""
Test VAD → audio capture → send to server, bypassing all Qt/UI code.

This replicates exactly what the client app does:
  mic → AudioCapture (32ms frames) → SileroVAD → speech_end → ws.send(raw_bytes)

Usage (from repo root):
  python tests/test_vad.py           # listen until Ctrl+C, send each utterance to server
  python tests/test_vad.py --local   # same but transcribe locally (no server needed)
  python tests/test_vad.py --save    # also save each utterance as utterance_N.raw (raw PCM16)
                                     # then test with: python tests/test_stt.py --file utterance_0.raw --raw --ws
"""

import asyncio
import logging
import sys
import os
import argparse
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run(args):
    from client.audio_capture import AudioCapture
    from client.vad import SileroVAD

    capture = AudioCapture()
    vad = SileroVAD()

    # Set up server connection if not local
    ws = None
    if not args.local:
        import websockets, json
        ws_url = os.getenv("SERVER_WS_URL", "ws://localhost:8765/ws")
        logger.info(f"Connecting to {ws_url}")
        ws = await websockets.connect(ws_url, ping_interval=20)
        await ws.send(json.dumps({
            "type": "session_start",
            "kiosk_id": "vad-test",
            "kiosk_location": "test",
        }))
        ack = json.loads(await ws.recv())
        logger.info(f"Server ack: {ack}")
    else:
        from server.stt.whisper_stt import WhisperSTT
        model   = os.getenv("STT_MODEL", "large-v3")
        device  = os.getenv("STT_DEVICE", "cuda")
        compute = os.getenv("STT_COMPUTE_TYPE", "float16")
        logger.info(f"Loading WhisperSTT locally: {model} on {device}")
        stt = WhisperSTT(model_size=model, device=device, compute_type=compute)
        logger.info("Model ready.\n")

    utterance_count = 0
    print("\n🎙  Listening — speak naturally, pause to end each utterance. Ctrl+C to quit.\n")

    async def receive_responses():
        """Print server responses in background."""
        if ws is None:
            return
        import json
        try:
            while True:
                raw = await ws.recv()
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "transcript":
                    print(f"\n  📝 Transcript : {msg.get('text', '')!r}")
                    print(f"     Language   : {msg.get('lang', '?')}\n")
                elif t == "llm_text_chunk" and msg.get("text"):
                    print(msg.get("text"), end="", flush=True)
                elif t == "llm_text_chunk" and msg.get("final"):
                    print()
        except Exception:
            pass

    # Start receive loop in background
    recv_task = asyncio.create_task(receive_responses())

    try:
        async for frame in capture.stream():
            event = vad.process_frame(frame)
            if event is None:
                continue

            if event.event_type == "speech_start":
                print("🔴  Speech detected — recording...", flush=True)

            elif event.event_type == "speech_end" and event.audio_buffer:
                buf = event.audio_buffer
                duration_s = len(buf) / 32000  # 16kHz * 2 bytes
                print(f"⏹  Speech end — {len(buf)} bytes ({duration_s:.2f}s)")

                if len(buf) < 16000:
                    print("⚠️  Too short (< 0.5s), skipping\n")
                    continue

                utterance_count += 1

                # Optionally save raw PCM16 for later replay
                if args.save:
                    fname = f"utterance_{utterance_count}.raw"
                    with open(fname, "wb") as f:
                        f.write(buf)
                    print(f"💾  Saved to {fname}")
                    print(f"    Replay with: python tests/test_stt.py --file {fname} --raw --ws")

                if args.local:
                    t0 = time.time()
                    result = await stt.transcribe(buf)
                    elapsed = time.time() - t0
                    print(f"\n  📝 Transcript : {result.text!r}")
                    print(f"     Language   : {result.language}")
                    print(f"     Confidence : {result.confidence:.3f}")
                    print(f"     Inference  : {elapsed*1000:.0f}ms\n")
                else:
                    t0 = time.time()
                    await ws.send(buf)
                    print(f"  📤 Sent to server ({time.time()-t0:.0f}ms), waiting for transcript...\n")

    except KeyboardInterrupt:
        print(f"\n\nDone. {utterance_count} utterance(s) processed.")
    finally:
        recv_task.cancel()
        if ws:
            await ws.close()


def main():
    parser = argparse.ArgumentParser(
        description="Test VAD → mic capture → STT, bypassing the Qt UI"
    )
    parser.add_argument("--local", action="store_true",
                        help="Transcribe locally instead of sending to server")
    parser.add_argument("--save", action="store_true",
                        help="Save each utterance as utterance_N.raw for later replay")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
