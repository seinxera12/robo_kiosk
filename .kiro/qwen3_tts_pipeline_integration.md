# Qwen3 TTS — Async Pipeline Integration Guide
> For coding agent use. Scope: drop-in TTS stage into an existing STT → LLM → TTS → UI streaming pipeline.

---

## 1. Architecture Contract

The TTS stage is a **pure async transformer**: it consumes a stream of LLM text tokens and emits a stream of PCM audio chunks. It must not block, own, or modify any adjacent pipeline stage.

```
STT (audio chunks)
  → asyncio.Queue[str]          # transcript fragments
    → LLM (streaming tokens)
      → asyncio.Queue[str]      # sentence-complete text
        → Qwen3 TTS (streaming PCM)
          → asyncio.Queue[bytes] # raw audio frames
            → UI renderer
```

Each stage boundary is an **`asyncio.Queue`**. No stage holds a reference to another — only to its input and output queues.

---

## 2. Backend: Serving Qwen3 TTS

Deploy via **vLLM-Omni** (official day-0 support):

```bash
pip install vllm-omni
vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --port 8001 \
  --async-chunk         # required for streaming output
```

For lighter hardware use `Qwen3-TTS-12Hz-0.6B-CustomVoice`.

**Streaming constraint:** `stream=true` requires `response_format="pcm"` (16-bit signed PCM, 24 kHz mono). Speed adjustment is not supported in streaming mode.

---

## 3. TTS Stage Implementation

### 3a. Sentence Boundary Buffer (LLM → TTS handoff)

The TTS server splits at sentence boundaries internally, but feeding it complete sentences reduces first-packet latency. Add a thin buffer between the LLM queue and TTS:

```python
import asyncio, re

SENTENCE_END = re.compile(r'(?<=[。！？.!?])\s*')

async def sentence_buffer(
    token_queue: asyncio.Queue[str | None],
    sentence_queue: asyncio.Queue[str | None],
):
    buf = ""
    async for token in queue_iter(token_queue):
        buf += token
        parts = SENTENCE_END.split(buf)
        for sentence in parts[:-1]:
            if sentence.strip():
                await sentence_queue.put(sentence.strip())
        buf = parts[-1]
    if buf.strip():
        await sentence_queue.put(buf.strip())
    await sentence_queue.put(None)  # sentinel
```

### 3b. TTS WebSocket Streamer

Use the `/v1/audio/speech/stream` WebSocket endpoint. The server accepts text incrementally and emits `audio.start` / binary PCM frames / `audio.done` events per sentence.

```python
import asyncio, json, websockets

QWEN_TTS_WS = "ws://localhost:8001/v1/audio/speech/stream"

async def tts_stage(
    sentence_queue: asyncio.Queue[str | None],
    audio_queue: asyncio.Queue[bytes | None],
    *,
    voice: str = "Ono_Anna",   # Japanese preset; swap for cloned voice ID
    language: str = "ja",
):
    async with websockets.connect(QWEN_TTS_WS) as ws:
        # Configure session once
        await ws.send(json.dumps({
            "type": "session.config",
            "voice": voice,
            "task_type": "CustomVoice",   # or "Base" for voice cloning
            "language": language,
            "split_granularity": "sentence",
            "stream_audio": True,
            "response_format": "pcm",
        }))

        async def sender():
            async for sentence in queue_iter(sentence_queue):
                await ws.send(json.dumps({
                    "type": "input.text",
                    "text": sentence,
                }))
            await ws.send(json.dumps({"type": "input.end"}))

        async def receiver():
            async for message in ws:
                if isinstance(message, bytes):
                    await audio_queue.put(message)    # raw PCM chunk
                else:
                    event = json.loads(message)
                    if event.get("type") == "audio.done":
                        pass  # sentence boundary, no action needed
            await audio_queue.put(None)               # sentinel

        await asyncio.gather(sender(), receiver())
```

### 3c. Voice Cloning (Base model variant)

When using `Qwen3-TTS-12Hz-1.7B-Base` for a cloned voice, change session config:

```python
await ws.send(json.dumps({
    "type": "session.config",
    "task_type": "Base",
    "reference_audio": "<base64_encoded_wav>",  # ≥3 seconds of target voice
    "reference_text": "reference transcript",
    "language": "ja",
    "stream_audio": True,
    "response_format": "pcm",
}))
```

---

## 4. Audio Queue → UI Renderer

The UI stage reads raw PCM from the audio queue and plays it. Do not buffer full audio before playing — play each chunk as it arrives.

```python
import sounddevice as sd
import numpy as np

SAMPLE_RATE = 24000
CHANNELS = 1
DTYPE = np.int16

async def audio_render_stage(audio_queue: asyncio.Queue[bytes | None]):
    loop = asyncio.get_event_loop()
    with sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    ) as stream:
        async for chunk in queue_iter(audio_queue):
            pcm = np.frombuffer(chunk, dtype=DTYPE)
            await loop.run_in_executor(None, stream.write, pcm)
```

---

## 5. Pipeline Assembly

```python
async def run_pipeline(user_audio_input):
    token_q   = asyncio.Queue(maxsize=100)
    sentence_q = asyncio.Queue(maxsize=20)
    audio_q   = asyncio.Queue(maxsize=50)

    await asyncio.gather(
        stt_stage(user_audio_input, token_q),         # your existing STT
        sentence_buffer(token_q, sentence_q),          # new: thin adapter
        tts_stage(sentence_q, audio_q),                # new: Qwen3 TTS
        llm_stage(..., token_q),                       # your existing LLM
        audio_render_stage(audio_q),                   # your existing UI
    )
```

---

## 6. Key Constraints & Gotchas

| Concern | Rule |
|---|---|
| Streaming format | Must use `response_format="pcm"`. WAV/MP3 only for non-streaming. |
| `async_chunk` flag | Server **must** start with `--async-chunk`. Streaming won't work without it. |
| Speed control | `speed` param is **ignored** in streaming mode. |
| Voice cloning model | Use `Base` variant, not `CustomVoice` or `VoiceDesign`. |
| Sentence chunking | Feed complete sentences for lowest TTFP (~97ms). Partial tokens increase latency. |
| PCM normalization | Qwen3 output is int16 at 24kHz. Resample explicitly if downstream expects 44.1kHz. |
| Stage isolation | Each stage only imports its input queue and output queue. No cross-stage calls. |
| Sentinel pattern | Use `None` as stream-end sentinel in all queues. Every stage must propagate it. |
| Concurrency | 0.6B: suitable for single-user real-time. 1.7B: use for quality; supports ~6 concurrent streams at <340ms TTFP. |

---

## 7. Utility: Queue Iterator

Used by all stages above:

```python
async def queue_iter(q: asyncio.Queue):
    while True:
        item = await q.get()
        if item is None:
            break
        yield item
```

---

## 8. Model Selection Summary

| Need | Model |
|---|---|
| Preset JP voice, lowest setup | `Qwen3-TTS-12Hz-1.7B-CustomVoice` + `voice="Ono_Anna"` |
| Clone a specific voice from sample | `Qwen3-TTS-12Hz-1.7B-Base` + `reference_audio` |
| Fastest / lighter GPU | `Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| Describe voice in natural language | `Qwen3-TTS-12Hz-1.7B-VoiceDesign` |
