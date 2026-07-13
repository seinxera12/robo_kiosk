#!/usr/bin/env python3
"""
STT inference probe — mimics server/stt/remote_whisper_stt.py.

Builds a 16 kHz mono WAV (from --wav if given, else a synthetic tone) and POSTs
it to the faster-whisper endpoint exactly like the voice-server does
(multipart file + response_format=verbose_json). Validates the response carries
the fields the pipeline relies on: text, language, and per-segment no_speech_prob.

Run ON THE SERVER (reaches stt-fastwhisper over the Docker network).

Usage:
  python test_stt.py
  python test_stt.py --url http://stt-fastwhisper:8000/v1/audio/transcriptions
  python test_stt.py --wav /path/to/speech.wav          # real speech = real transcript
"""
import argparse
import io
import os
import struct
import sys
import time
import wave

import httpx

from _env import load_dotenv
load_dotenv()  # populate os.environ from ./.env (safe: ignores comments/quotes)


def synth_wav(seconds: float = 1.5, rate: int = 16000, freq: int = 220) -> bytes:
    """A short sine tone. Won't produce meaningful text, but exercises the full
    request/response path and the verbose_json contract."""
    import math
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            val = int(0.2 * 32767 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", val)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def load_wav(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv(
        "STT_REMOTE_URL", "http://stt-fastwhisper:8000/v1/audio/transcriptions"))
    ap.add_argument("--wav", default=None, help="Path to a real 16kHz mono WAV (optional)")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    wav_bytes = load_wav(args.wav) if args.wav else synth_wav()
    src = args.wav or "synthetic 220Hz tone (1.5s)"
    print(f"→ POST {args.url}")
    print(f"  audio: {src}  ({len(wav_bytes)} bytes)")

    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"response_format": "verbose_json"}
    t0 = time.time()
    try:
        r = httpx.post(args.url, files=files, data=data, timeout=args.timeout)
        r.raise_for_status()
        resp = r.json()
    except Exception as e:
        print(f"  ✗ request failed: {e}")
        return 1

    dt = time.time() - t0
    text = (resp.get("text") or "").strip()
    lang = resp.get("language")
    segs = resp.get("segments") or []

    print(f"  ✓ HTTP 200 in {dt:.2f}s")
    print(f"  text={text!r}")
    print(f"  language={lang!r}  (voice-server trusts this — Option A)")
    print(f"  segments={len(segs)}")
    # Contract the adapter depends on:
    if lang is None:
        print("  ⚠ no 'language' field — adapter would fall back to Unicode scan")
    if segs and "no_speech_prob" in segs[0]:
        nsp = segs[0].get("no_speech_prob")
        print(f"  ✓ segments carry no_speech_prob (e.g. {nsp}) — hallucination guard preserved")
    else:
        print("  ⚠ segments lack no_speech_prob — warnings would be lost (not fatal)")

    # A real speech WAV should yield non-empty text; a tone may be empty.
    if args.wav and not text:
        print("  ✗ real WAV produced empty transcript"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
