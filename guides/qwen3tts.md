# Qwen3 TTS Fallback Engine — Operator Setup Guide

This guide explains how to deploy the vLLM-Omni server for Qwen3 TTS and enable
it as the final fallback engine in the voice pipeline.

---

## 1. Start the vLLM-Omni Server

Install vllm-omni and start the server:

```bash
pip install vllm-omni
```

### Default model — 0.6B (recommended for single-user real-time on lighter hardware)

```bash
vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice \
  --port 8001 \
  --async-chunk
```

### Upgrade option — 1.7B (higher quality or ~6 concurrent streams)

```bash
vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --port 8001 \
  --async-chunk
```

> **Important**: The `--async-chunk` flag is **required** for streaming output.
> Without it, `response_format="pcm"` streaming will not work.

---

## 2. Environment Variables

Set these variables in your `.env` or `.env.local` file (or as shell environment variables):

| Variable | Type | Default | Accepted values |
|---|---|---|---|
| `QWEN3_TTS_ENABLED` | bool | `false` | `true`, `1`, `yes` (case-insensitive) to enable |
| `QWEN3_TTS_WS_URL` | str | `ws://localhost:8001/v1/audio/speech/stream` | Any valid `ws://` or `wss://` URL |
| `QWEN3_TTS_VOICE` | str | `Ono_Anna` | Any voice preset supported by the model |
| `QWEN3_TTS_LANGUAGE` | str | `ja` | BCP-47 language tag (e.g. `ja`, `en`, `zh`) |

Minimal configuration to enable the fallback:

```env
QWEN3_TTS_ENABLED=true
# Other variables use their defaults unless you need to change them
```

---

## 3. Fallback Chain

Qwen3 TTS is the **final fallback** in both synthesis chains. It is only invoked
when all higher-priority engines produce zero audio chunks for a given sentence.

| Language | Priority 1 | Priority 2 | Priority 3 (Qwen3 fallback) |
|---|---|---|---|
| English | KokoroTTS | — | Qwen3TTSEngine |
| Japanese | KokoCloneTTS | KokoroJapaneseTTS | Qwen3TTSEngine |

When `QWEN3_TTS_ENABLED=false` (the default), the chains behave exactly as before
this feature was added — no change to existing behaviour.

---

## 4. Verification

Before enabling the fallback, confirm the vLLM-Omni server is reachable:

```bash
# Python one-liner connectivity check
python -c "
import asyncio, websockets

async def check():
    try:
        async with websockets.connect('ws://localhost:8001/v1/audio/speech/stream',
                                      open_timeout=3.0):
            print('OK — vLLM-Omni server is reachable')
    except Exception as e:
        print(f'FAIL — {e}')

asyncio.run(check())
"
```

Once the main server is running with `QWEN3_TTS_ENABLED=true`, check the health endpoint:

```bash
curl -s http://localhost:8765/health | python -m json.tool | grep qwen3_tts
# Expected output: "qwen3_tts": "ready"
```

---

## 5. Model Selection

| Use case | Model |
|---|---|
| Single-user real-time, lighter GPU | `Qwen3-TTS-12Hz-0.6B-CustomVoice` (default) |
| Higher quality or ~6 concurrent streams | `Qwen3-TTS-12Hz-1.7B-CustomVoice` |
| Voice cloning from reference audio | `Qwen3-TTS-12Hz-1.7B-Base` (requires `task_type: "Base"` and `reference_audio`) |

The `0.6B-CustomVoice` model is the default choice — it delivers real-time
performance on a single GPU with modest VRAM requirements. Upgrade to
`1.7B-CustomVoice` for higher audio quality or when serving multiple concurrent
users.
