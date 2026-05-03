#!/usr/bin/env python3
"""
Quick STT transcription tester.

Usage (from repo root, with server venv active):

  # Record from mic for N seconds then transcribe:
  python tests/test_stt.py --record 5

  # Transcribe an existing WAV/MP3/OGG file:
  python tests/test_stt.py --file path/to/audio.wav

  # Send audio to the running server over WebSocket (full pipeline test):
  python tests/test_stt.py --file path/to/audio.wav --ws

Options:
  --record N        Record N seconds from microphone (default: 5)
  --file PATH       Path to audio file to transcribe
  --ws              Send to running server via WebSocket instead of local STT
  --model SIZE      Whisper model size (default: reads STT_MODEL env var, fallback large-v3)
  --device DEVICE   cuda or cpu (default: reads STT_DEVICE env var, fallback cuda)
  --compute TYPE    float16 / int8 (default: reads STT_COMPUTE_TYPE env var, fallback float16)
  --debug           Enable DEBUG logging (shows per-segment detail)
  --lang LANG       Force language (en/ja) — skips auto-detection
"""

import argparse
import asyncio
import logging
import os
import sys
import time
import wave
import io

import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if debug:
        logging.getLogger("server.stt.whisper_stt").setLevel(logging.DEBUG)
        logging.getLogger("server.lang.detector").setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def record_from_mic(seconds: int) -> bytes:
    """Record PCM16 mono 16kHz audio from the default microphone."""
    try:
        import sounddevice as sd
    except ImportError:
        sys.exit("sounddevice not installed — run: pip install sounddevice")

    sample_rate = 16000
    print(f"\n🎙  Recording for {seconds} seconds — speak now...")
    audio = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype=np.float32,
    )
    sd.wait()
    print("✅  Recording complete.\n")

    # Convert float32 → PCM16 bytes
    pcm16 = (audio.flatten() * 32767).astype(np.int16)
    return pcm16.tobytes()


def load_audio_file(path: str) -> bytes:
    """
    Load an audio file and return PCM16 mono 16kHz bytes.
    Supports WAV natively; MP3/OGG/etc. require pydub + ffmpeg.
    """
    if not os.path.exists(path):
        sys.exit(f"File not found: {path}")

    ext = os.path.splitext(path)[1].lower()

    if ext == ".wav":
        return _load_wav(path)
    else:
        return _load_via_pydub(path)


def _load_wav(path: str) -> bytes:
    """Load a WAV file, resampling to 16kHz mono PCM16 if needed."""
    with wave.open(path, "rb") as wf:
        src_rate = wf.getframerate()
        src_channels = wf.getnchannels()
        src_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Decode to float32
    if src_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif src_width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        sys.exit(f"Unsupported WAV sample width: {src_width} bytes")

    # Mix down to mono
    if src_channels > 1:
        audio = audio.reshape(-1, src_channels).mean(axis=1)

    # Resample to 16kHz if needed
    if src_rate != 16000:
        audio = _resample(audio, src_rate, 16000)

    pcm16 = (audio * 32767).astype(np.int16)
    print(f"  Loaded WAV: {src_rate}Hz → 16kHz, {src_channels}ch → mono, {len(pcm16)/16000:.2f}s")
    return pcm16.tobytes()


def _load_via_pydub(path: str) -> bytes:
    try:
        from pydub import AudioSegment
    except ImportError:
        sys.exit(
            f"pydub not installed (needed for {os.path.splitext(path)[1]} files).\n"
            "Run: pip install pydub\n"
            "Also ensure ffmpeg is installed: sudo apt install ffmpeg"
        )
    audio = AudioSegment.from_file(path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    pcm16 = np.frombuffer(audio.raw_data, dtype=np.int16)
    print(f"  Loaded {os.path.splitext(path)[1]}: resampled to 16kHz mono, {len(pcm16)/16000:.2f}s")
    return pcm16.tobytes()


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear resampling (good enough for 44.1kHz→16kHz)."""
    try:
        import scipy.signal
        return scipy.signal.resample_poly(
            audio,
            dst_rate,
            src_rate,
        ).astype(np.float32)
    except ImportError:
        # Fallback: numpy linear interpolation
        duration = len(audio) / src_rate
        n_samples = int(duration * dst_rate)
        old_indices = np.linspace(0, len(audio) - 1, n_samples)
        return np.interp(old_indices, np.arange(len(audio)), audio).astype(np.float32)


# ---------------------------------------------------------------------------
# Local STT test (no server needed)
# ---------------------------------------------------------------------------

async def test_local(audio_bytes: bytes, args) -> None:
    """Run transcription directly using WhisperSTT — no server required."""
    # Add repo root to path so server.* imports work
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from server.stt.whisper_stt import WhisperSTT

    model   = args.model   or os.getenv("STT_MODEL", "large-v3")
    device  = args.device  or os.getenv("STT_DEVICE", "cuda")
    compute = args.compute or os.getenv("STT_COMPUTE_TYPE", "float16")

    print(f"Loading WhisperSTT: model={model}, device={device}, compute_type={compute}")
    print("(This takes ~10s on first run while the model loads into VRAM)\n")

    t0 = time.time()
    stt = WhisperSTT(model_size=model, device=device, compute_type=compute)
    print(f"Model loaded in {time.time()-t0:.1f}s\n")

    print(f"Audio: {len(audio_bytes)} bytes = {len(audio_bytes)/32000:.2f}s of PCM16 16kHz")
    print("Transcribing...\n")

    t0 = time.time()
    result = await stt.transcribe(audio_bytes)
    elapsed = time.time() - t0

    _print_result(result, elapsed)


# ---------------------------------------------------------------------------
# WebSocket test (uses running server)
# ---------------------------------------------------------------------------

async def test_via_websocket(audio_bytes: bytes, args) -> None:
    """Send audio to the running server and print the transcript it returns."""
    try:
        import websockets
    except ImportError:
        sys.exit("websockets not installed — run: pip install websockets")

    import json

    ws_url = os.getenv("SERVER_WS_URL", "ws://localhost:8765/ws")
    print(f"Connecting to server: {ws_url}\n")

    async with websockets.connect(ws_url, ping_interval=20) as ws:
        # Handshake
        await ws.send(json.dumps({
            "type": "session_start",
            "kiosk_id": "stt-test",
            "kiosk_location": "test",
        }))
        ack = json.loads(await ws.recv())
        print(f"Server ack: {ack}\n")

        # Send audio
        print(f"Sending {len(audio_bytes)} bytes of audio...")
        t0 = time.time()
        await ws.send(audio_bytes)

        # Wait for transcript message
        print("Waiting for transcript...\n")
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            if isinstance(raw, bytes):
                continue  # ignore any TTS audio that comes back
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "transcript":
                elapsed = time.time() - t0
                print("─" * 60)
                print(f"  Transcript : {msg.get('text', '')}")
                print(f"  Language   : {msg.get('lang', '?')}")
                print(f"  Round-trip : {elapsed*1000:.0f}ms")
                print("─" * 60)
                # Don't wait for LLM — close after transcript
                break
            elif t == "llm_text_chunk" and msg.get("final"):
                break


# ---------------------------------------------------------------------------
# Result printer
# ---------------------------------------------------------------------------

def _print_result(result, elapsed_s: float) -> None:
    print("─" * 60)
    print(f"  Transcript  : {result.text!r}")
    print(f"  Language    : {result.language}")
    print(f"  Lang conf   : {result.confidence:.3f}")
    print(f"  Duration    : {result.duration_ms}ms audio processed")
    print(f"  Inference   : {elapsed_s*1000:.0f}ms wall-clock")
    if result.text:
        rtf = result.duration_ms / (elapsed_s * 1000)
        print(f"  RTF         : {rtf:.1f}x real-time")
    print("─" * 60)

    if not result.text.strip():
        print("\n⚠️  Empty transcript — possible causes:")
        print("   • Audio too quiet or too short")
        print("   • High no_speech_prob (run with --debug to see)")
        print("   • Wrong microphone / file format")
    else:
        print(f"\n✅  Done.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test Whisper STT transcription without the full client UI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--record", metavar="SECONDS", type=int,
                     help="Record from microphone for N seconds")
    src.add_argument("--file", metavar="PATH",
                     help="Path to audio file (WAV, MP3, OGG, ...)")

    parser.add_argument("--ws", action="store_true",
                        help="Send to running server via WebSocket (tests full pipeline)")
    parser.add_argument("--model",   default=None, help="Whisper model size")
    parser.add_argument("--device",  default=None, help="cuda or cpu")
    parser.add_argument("--compute", default=None, help="float16 or int8")
    parser.add_argument("--debug",   action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    setup_logging(args.debug)

    # Get audio bytes
    if args.record:
        audio_bytes = record_from_mic(args.record)
    else:
        print(f"\nLoading: {args.file}")
        audio_bytes = load_audio_file(args.file)

    print(f"Audio ready: {len(audio_bytes)} bytes ({len(audio_bytes)/32000:.2f}s)\n")

    if args.ws:
        asyncio.run(test_via_websocket(audio_bytes, args))
    else:
        asyncio.run(test_local(audio_bytes, args))


if __name__ == "__main__":
    main()
