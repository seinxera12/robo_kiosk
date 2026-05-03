# Real-Time Streaming Voice Chatbot — Kiosk & Robot
## Complete Implementation Specification for Coding Agents

> **Purpose**: This document is the authoritative implementation reference for a coding agent (e.g. Kiro) to derive requirements, tasks, and architecture. It is structured for task isolation, accurate dependency ordering, and production-readiness. All decisions are final unless noted as configurable.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Repository Structure](#3-repository-structure)
4. [Component Specifications](#4-component-specifications)
   - 4.1 [Python Kiosk Client](#41-python-kiosk-client)
   - 4.2 [Server Pipeline Orchestrator](#42-server-pipeline-orchestrator)
   - 4.3 [STT — Speech-to-Text](#43-stt--speech-to-text)
   - 4.4 [LLM Inference with Fallback Chain](#44-llm-inference-with-fallback-chain)
   - 4.5 [TTS — Text-to-Speech](#45-tts--text-to-speech)
   - 4.6 [RAG — Building Knowledge Base](#46-rag--building-knowledge-base)
   - 4.7 [Language Detection](#47-language-detection)
   - 4.8 [Web Search Tool (SearXNG)](#48-web-search-tool-searxng)
5. [Data Flow & Protocol](#5-data-flow--protocol)
6. [LLM Fallback Chain Specification](#6-llm-fallback-chain-specification)
7. [Latency Targets & Performance Engineering](#7-latency-targets--performance-engineering)
8. [Infrastructure & Docker Compose](#8-infrastructure--docker-compose)
9. [Configuration & Environment Variables](#9-configuration--environment-variables)
10. [Kiosk Deployment & OS Setup](#10-kiosk-deployment--os-setup)
11. [Task Breakdown for Coding Agent](#11-task-breakdown-for-coding-agent)
12. [Dependency Graph](#12-dependency-graph)
13. [Testing Strategy](#13-testing-strategy)
14. [Known Constraints & Hard Rules](#14-known-constraints--hard-rules)

---

## 1. Project Overview

### What is being built

A fully self-hosted, bilingual (English + Japanese) real-time streaming voice chatbot deployed as:

- **Client**: A Python desktop application running on Ubuntu 22.04 kiosk/ATM hardware (no GPU required)
- **Server**: A GPU inference server running all AI pipelines (STT, LLM, TTS, RAG)
- **Use case**: Building navigation assistant — answers questions about floor layouts, room locations, facilities, departments

### Key Properties

| Property | Value |
|---|---|
| Languages | English (EN) + Japanese (JP) |
| Target latency | < 600ms Time-to-First-Audio (TTFA) |
| Client OS | Ubuntu 22.04 LTS |
| Client app | Python (PyQt6 or Tkinter for GUI; asyncio for I/O) |
| Server OS | Ubuntu 22.04 + CUDA 12.x |
| GPU requirement | 12–16 GB VRAM (server only) |
| LLM | Qwen2.5-7B Instruct (primary) |
| LLM engines | vLLM → Ollama → Grok API (fallback chain) |
| STT | Whisper Large V3 Turbo (faster-whisper) |
| TTS (EN) | CosyVoice2-0.5B |
| TTS (JP) | VOICEVOX (primary), Fish Speech v1.5 (fallback) |
| RAG | ChromaDB + multilingual-e5-large |
| Embeddings | intfloat/multilingual-e5-large |
| Orchestration | Pipecat + FastAPI + asyncio |
| Networking | WebSocket over LAN (PCM16 upstream, Opus+JSON downstream) |
| Input | Voice (microphone) + Keyboard / on-screen text |
| Deployment | Docker Compose (server), systemd service (client) |
| Privacy | Fully self-hosted; no cloud calls except Grok fallback |

### Non-Goals

- No cloud STT (no Whisper API, no Google ASR)
- No cloud TTS in primary path
- No Electron or Node.js client (replaced with Python)
- No Windows support
- No GPU on client device

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│              Ubuntu Kiosk Client (CPU only)               │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Microphone  │  │  Keyboard /  │  │   Speaker +   │  │
│  │  16kHz PCM16 │  │  Touch Input │  │   Display UI  │  │
│  └──────┬───────┘  └──────┬───────┘  └───────▲───────┘  │
│         │                 │                  │           │
│  ┌──────▼───────┐         │         ┌────────┴───────┐  │
│  │  Silero VAD  │         │         │  Audio Playback│  │
│  │  (CPU only)  │         │         │  (ALSA/Pulse)  │  │
│  └──────┬───────┘         │         └────────▲───────┘  │
│         │                 │                  │           │
│  ┌──────▼─────────────────▼──────────────────┴───────┐  │
│  │          WebSocket Client (asyncio)                │  │
│  │   binary PCM16 upstream │ Opus+JSON downstream     │  │
│  └────────────────────────┬───────────────────────────┘  │
└───────────────────────────┼──────────────────────────────┘
                            │ LAN WebSocket (ws://server:8765)
┌───────────────────────────┼──────────────────────────────┐
│      GPU Inference Server  │                              │
│                           ▼                              │
│  ┌────────────────────────────────────────────────────┐  │
│  │         FastAPI + Pipecat Orchestrator             │  │
│  │              (asyncio pipeline)                    │  │
│  └──┬────────────┬─────────────┬──────────────┬──────┘  │
│     │            │             │              │          │
│  ┌──▼──┐   ┌────▼────┐  ┌────▼────┐   ┌────▼────┐     │
│  │ STT │   │   RAG   │  │   LLM   │   │   TTS   │     │
│  │Whisp│   │ChromaDB │  │Fallback │   │CosyVoice│     │
│  │Turbo│   │e5-large │  │Chain    │   │VOICEVOX │     │
│  └─────┘   └─────────┘  └────┬────┘   └─────────┘     │
│                               │                          │
│                    ┌──────────▼──────────┐              │
│                    │  LLM Fallback Chain  │              │
│                    │  1. vLLM (local GPU) │              │
│                    │  2. Ollama (local)   │              │
│                    │  3. Grok API (cloud) │              │
│                    └─────────────────────┘              │
│                                                          │
│  ┌───────────────┐  ┌───────────────┐                   │
│  │   VOICEVOX   │  │   SearXNG     │                   │
│  │  (Docker JP  │  │  (self-hosted │                   │
│  │   TTS REST)  │  │   web search) │                   │
│  └───────────────┘  └───────────────┘                   │
└──────────────────────────────────────────────────────────┘
```

### Principle: Server does all AI. Client does all I/O.

The client is intentionally thin (~500 lines of logic). It:
1. Captures audio → runs Silero VAD → streams PCM to server
2. Accepts keyboard text → sends JSON to server
3. Receives audio chunks + UI events from server → plays audio, updates display

The server does:
1. STT (Whisper) → text cleaning → language detection
2. RAG retrieval (parallel with STT finalization)
3. LLM inference (streaming, with fallback chain)
4. TTS synthesis (sentence-boundary streaming)
5. Sends audio chunks + events back to client

---

## 3. Repository Structure

```
voice-kiosk/
├── client/                          # Python kiosk client (Ubuntu)
│   ├── main.py                      # Entry point, asyncio event loop
│   ├── audio_capture.py             # sounddevice mic capture, 16kHz PCM16
│   ├── vad.py                       # Silero VAD wrapper
│   ├── ws_client.py                 # WebSocket client (websockets lib)
│   ├── audio_playback.py            # ALSA/PulseAudio playback via sounddevice
│   ├── keyboard_input.py            # Keyboard and on-screen text input handler
│   ├── ui/
│   │   ├── app.py                   # PyQt6 main window (kiosk fullscreen)
│   │   ├── conversation_widget.py   # Chat transcript display
│   │   ├── status_indicator.py      # listening/thinking/speaking visual state
│   │   ├── keyboard_widget.py       # On-screen keyboard (optional)
│   │   └── styles.qss               # Qt stylesheets
│   ├── config.py                    # Client configuration (SERVER_URL etc.)
│   ├── requirements.txt             # Client Python deps
│   └── kiosk.service               # systemd unit file
│
├── server/                          # GPU inference server
│   ├── main.py                      # FastAPI app + WebSocket endpoint
│   ├── pipeline.py                  # Pipecat pipeline orchestration
│   ├── stt/
│   │   ├── whisper_stt.py           # faster-whisper STT wrapper
│   │   └── text_cleaner.py          # Punctuation, filler word removal
│   ├── llm/
│   │   ├── fallback_chain.py        # LLM fallback: vLLM → Ollama → Grok
│   │   ├── vllm_backend.py          # vLLM OpenAI-compat client
│   │   ├── ollama_backend.py        # Ollama OpenAI-compat client
│   │   ├── grok_backend.py          # Grok (xAI) API client
│   │   └── prompt_builder.py        # System prompt + context injection
│   ├── tts/
│   │   ├── tts_router.py            # Route EN→CosyVoice2, JP→VOICEVOX
│   │   ├── cosyvoice_tts.py         # CosyVoice2-0.5B streaming wrapper
│   │   ├── voicevox_tts.py          # VOICEVOX REST API client
│   │   └── fish_speech_tts.py       # Fish Speech v1.5 fallback
│   ├── rag/
│   │   ├── chroma_store.py          # ChromaDB client + retrieval
│   │   ├── embedder.py              # multilingual-e5-large wrapper
│   │   └── ingest.py                # Building KB ingestion script
│   ├── lang/
│   │   └── detector.py              # Language detection (Whisper + Unicode fallback)
│   ├── search/
│   │   └── searxng_client.py        # SearXNG web search tool implementation
│   ├── tools/
│   │   └── tool_definitions.py      # LLM function/tool call schemas
│   ├── config.py                    # Server config, env vars, model paths
│   ├── requirements.txt             # Server Python deps
│   └── Dockerfile
│
├── building_kb/                     # Bilingual knowledge base documents
│   ├── floors/
│   │   ├── floor_01.md              # EN: Lobby, reception, main entrance
│   │   ├── floor_02.md
│   │   └── ...
│   ├── facilities/
│   │   ├── elevators.md
│   │   ├── restrooms.md
│   │   ├── exits.md
│   │   └── cafeteria.md
│   ├── rooms/
│   │   ├── meeting_rooms.md
│   │   └── directory.md
│   └── japanese/                    # JP translations
│       ├── floor_01.md
│       └── ...
│
├── models/                          # Downloaded model weights (gitignored)
│   ├── whisper-large-v3-turbo/
│   ├── multilingual-e5-large/
│   └── cosyvoice2/
│
├── docker-compose.yml               # Full production stack
├── docker-compose.dev.yml           # Dev overrides (Ollama instead of vLLM)
├── .env.example                     # Environment variable template
├── scripts/
│   ├── download_models.sh           # Pull all model weights
│   ├── ingest_kb.sh                 # Run RAG ingestion
│   └── setup_kiosk_os.sh            # Ubuntu kiosk OS hardening script
└── README.md
```

---

## 4. Component Specifications

### 4.1 Python Kiosk Client

**Language**: Python 3.11+
**UI framework**: PyQt6 (preferred) — provides fullscreen kiosk window, on-screen keyboard widget, and proper ALSA audio integration. Fallback: Tkinter (simpler, no on-screen keyboard, sufficient for voice-only).
**Why Python not Electron**: Avoids Node.js/npm dependency, simpler audio stack (sounddevice integrates directly with ALSA), easier systemd integration, consistent with server codebase.

#### Client Module Responsibilities

| Module | Responsibility |
|---|---|
| `audio_capture.py` | Open sounddevice input stream at 16kHz, 1ch, PCM16. Emit 20ms frames to VAD queue. |
| `vad.py` | Run Silero VAD on each 20ms frame. Emit `speech_start`, `speech_chunk`, `speech_end` events. On `speech_end`, flush audio buffer to WebSocket. |
| `ws_client.py` | Maintain persistent WebSocket connection. Send binary PCM frames (voice) and JSON messages (keyboard text, control). Receive binary audio + JSON events. |
| `audio_playback.py` | Buffer incoming audio chunks. Play via sounddevice output stream. Implement barge-in: on `speech_start` event from VAD while playing → immediately stop playback, send `interrupt` JSON to server. |
| `keyboard_input.py` | Capture keyboard events (physical or on-screen). On Enter/submit, send `{"type": "text_input", "text": "...", "lang": "auto"}` JSON via WebSocket. |
| `ui/app.py` | PyQt6 QMainWindow in fullscreen kiosk mode. No window chrome. Displays conversation transcript, status indicator, keyboard input widget. |
| `ui/status_indicator.py` | Three visual states: 🟢 Listening (mic open), 🟡 Thinking (server processing), 🔵 Speaking (audio playback). |

#### Client Event Protocol

**Upstream (client → server)**:
```json
// Voice audio: raw binary WebSocket frames
// Each frame: PCM16 LE, 16kHz, mono, 20ms = 640 bytes

// Keyboard text input:
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "auto"}

// Barge-in / interrupt signal:
{"type": "interrupt"}

// Session start (sent on connect):
{"type": "session_start", "kiosk_id": "kiosk-01", "kiosk_location": "Floor 1 Lobby"}
```

**Downstream (server → client)**:
```json
// Audio: binary WebSocket frames (Opus-encoded, 48kHz, mono)

// Transcript event (show user's recognized speech):
{"type": "transcript", "text": "Where is the cafeteria?", "lang": "en", "final": true}

// LLM response text (for display):
{"type": "llm_text_chunk", "text": "The cafeteria is on Floor 3,", "final": false}

// Status change:
{"type": "status", "state": "thinking"} // listening | thinking | speaking | idle

// TTS audio start (client prepares playback):
{"type": "tts_start", "lang": "en"}

// TTS audio end:
{"type": "tts_end"}

// Error:
{"type": "error", "code": "llm_unavailable", "message": "All LLM backends failed"}
```

#### Client Python Dependencies

```
# client/requirements.txt
sounddevice>=0.4.6
numpy>=1.26.0
websockets>=12.0
PyQt6>=6.6.0          # GUI framework
silero-vad>=4.0.0     # VAD
torch>=2.2.0          # Required for Silero VAD (CPU only)
opuslib>=3.0.1        # Opus audio decode
langdetect>=1.0.9     # Keyboard text language detection
asyncio-queue>=0.1.0
```

#### Client systemd Service

```ini
# /etc/systemd/system/voice-kiosk.service
[Unit]
Description=Voice Kiosk Client
After=graphical.target network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=kiosk
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1001
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/opt/voice-kiosk/client
ExecStart=/opt/voice-kiosk/venv/bin/python main.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical.target
```

---

### 4.2 Server Pipeline Orchestrator

**Framework**: Pipecat (Python) + FastAPI + asyncio
**Transport**: FastAPI WebSocket endpoint at `ws://0.0.0.0:8765/ws`

#### Pipeline Stages (all async coroutines with asyncio queues)

```
AudioInputQueue → [STT Worker] → TranscriptQueue
                                       ↓
                 RAGQueue ← [RAG Worker] (parallel)
                                       ↓
                              [LLM Worker] → TokenQueue
                                       ↓
                              [TTS Worker] → AudioQueue
                                       ↓
                             [WebSocket Sender]
```

**Critical**: RAG retrieval launches simultaneously with the final STT decode pass, not after. Both complete before LLM generates its first token.

#### FastAPI WebSocket Handler

```python
# server/main.py (structure)
from fastapi import FastAPI, WebSocket
from pipeline import VoicePipeline

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    pipeline = VoicePipeline(ws)
    await pipeline.run()
```

#### Pipeline Interrupt / Barge-in Handling

When an `interrupt` JSON message arrives from the client while TTS is playing:
1. Set a shared `asyncio.Event` → `interrupt_event`
2. All pipeline stages check this event and abort current turn
3. Drain all queues (TranscriptQueue, TokenQueue, AudioQueue)
4. Reset pipeline state to `listening`
5. Send `{"type": "status", "state": "listening"}` to client

---

### 4.3 STT — Speech-to-Text

**Model**: Whisper Large V3 Turbo
**Backend**: faster-whisper (CTranslate2)
**Languages**: English + Japanese (auto-detected per utterance)

#### STT Configuration

```python
from faster_whisper import WhisperModel

model = WhisperModel(
    "large-v3-turbo",
    device="cuda",
    compute_type="float16",   # Use "int8" if VRAM < 12GB
    num_workers=1,
)

def transcribe(audio_bytes: bytes) -> tuple[str, str]:
    segments, info = model.transcribe(
        audio_bytes,
        beam_size=1,           # Greedy decoding — fastest, minimal quality loss
        language=None,         # Auto-detect
        vad_filter=False,      # VAD handled client-side
    )
    lang = info.language       # "en" or "ja"
    text = " ".join([s.text for s in segments])
    return text, lang
```

#### Text Cleaning (post-STT)

After transcription, apply:
1. Strip leading/trailing whitespace
2. Remove filler words: "um", "uh", "えー", "あの" (configurable per language)
3. Restore sentence-ending punctuation if missing
4. Confirm language detection (use Unicode block scan as secondary check)

---

### 4.4 LLM Inference with Fallback Chain

This is a critical new requirement. The system must attempt LLM backends in order, falling back automatically on failure or timeout.

#### Fallback Chain Order

```
1. vLLM (local GPU)        → Primary. Fastest. Requires GPU + vLLM running.
2. Ollama (local CPU/GPU)  → Secondary. Slower but no separate server required.
3. Grok API (xAI cloud)    → Tertiary. Cloud fallback. Requires GROK_API_KEY.
```

#### Fallback Logic

```python
# server/llm/fallback_chain.py

import asyncio
from typing import AsyncIterator
from .vllm_backend import VLLMBackend
from .ollama_backend import OllamaBackend
from .grok_backend import GrokBackend

BACKENDS = [VLLMBackend, OllamaBackend, GrokBackend]
BACKEND_TIMEOUT_SECONDS = 5.0   # Health check timeout per backend
STREAM_TIMEOUT_SECONDS = 30.0   # Max time to wait for first token

class LLMFallbackChain:
    def __init__(self, config):
        self.backends = [B(config) for B in BACKENDS]
        self._healthy_index = 0  # Cache of last known good backend

    async def health_check(self, backend) -> bool:
        try:
            await asyncio.wait_for(backend.ping(), timeout=BACKEND_TIMEOUT_SECONDS)
            return True
        except Exception:
            return False

    async def stream(self, messages: list, tools=None) -> AsyncIterator[str]:
        for i, backend in enumerate(self.backends[self._healthy_index:], self._healthy_index):
            if not await self.health_check(backend):
                continue
            try:
                async for token in backend.stream(messages, tools=tools):
                    yield token
                self._healthy_index = i  # Update cache
                return
            except Exception as e:
                # Log the failure, try next backend
                continue
        raise RuntimeError("All LLM backends failed")
```

#### Backend Interface Contract

Each backend must implement:

```python
class BaseLLMBackend:
    async def ping(self) -> None:
        """Raise on failure."""
        ...

    async def stream(self, messages: list, tools=None) -> AsyncIterator[str]:
        """Yield text tokens. Raise on fatal error."""
        ...
```

#### vLLM Backend

```python
# server/llm/vllm_backend.py
from openai import AsyncOpenAI

class VLLMBackend(BaseLLMBackend):
    def __init__(self, config):
        self.client = AsyncOpenAI(
            base_url=config.VLLM_BASE_URL,  # e.g. http://llm:8000/v1
            api_key="local"
        )
        self.model = config.VLLM_MODEL_NAME  # e.g. "qwen25"

    async def ping(self):
        await self.client.models.list()

    async def stream(self, messages, tools=None):
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
            max_tokens=512,
            temperature=0.7,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
            elif delta.tool_calls:
                yield delta  # Upstream handles tool calls
```

#### Ollama Backend

```python
# server/llm/ollama_backend.py
from openai import AsyncOpenAI

class OllamaBackend(BaseLLMBackend):
    def __init__(self, config):
        self.client = AsyncOpenAI(
            base_url=config.OLLAMA_BASE_URL,  # e.g. http://localhost:11434/v1
            api_key="ollama"
        )
        self.model = config.OLLAMA_MODEL_NAME  # e.g. "qwen2.5:7b"

    async def ping(self):
        await self.client.models.list()

    async def stream(self, messages, tools=None):
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            max_tokens=512,
            temperature=0.7,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
```

#### Grok Backend

```python
# server/llm/grok_backend.py
from openai import AsyncOpenAI

class GrokBackend(BaseLLMBackend):
    def __init__(self, config):
        self.client = AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=config.GROK_API_KEY      # from env var
        )
        self.model = "grok-3-fast"            # or grok-3 for max quality

    async def ping(self):
        await self.client.models.list()

    async def stream(self, messages, tools=None):
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            max_tokens=512,
            temperature=0.7,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
```

#### Prompt Builder

```python
# server/llm/prompt_builder.py

SYSTEM_PROMPT_TEMPLATE = """
You are a building navigation assistant for {BUILDING_NAME}.
Answer in the same language the user uses (English or Japanese).
Be polite and provide clear, landmark-based directions.
Use landmarks (elevator A, main lobby) rather than cardinal directions.
When responding in Japanese, use polite form (です・ます体).
日本語で回答する場合は、丁寧語（です・ます体）を使用してください。

BUILDING KNOWLEDGE:
{retrieved_context}

Current date/time: {datetime}
Kiosk location: {kiosk_location}
"""

def build_messages(user_text: str, lang: str, context: str, history: list, kiosk_meta: dict) -> list:
    system = SYSTEM_PROMPT_TEMPLATE.format(
        BUILDING_NAME=kiosk_meta["building_name"],
        retrieved_context=context,
        datetime=kiosk_meta["datetime"],
        kiosk_location=kiosk_meta["kiosk_location"],
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-10:])  # Last 10 turns of conversation
    messages.append({"role": "user", "content": user_text})
    return messages
```

---

### 4.5 TTS — Text-to-Speech

TTS is routed by detected language. Audio is streamed sentence-by-sentence.

#### TTS Routing

| Language | Primary | Fallback |
|---|---|---|
| English (`en`) | CosyVoice2-0.5B | Chatterbox TTS |
| Japanese (`ja`) | VOICEVOX (Docker REST) | Fish Speech v1.5 |

#### Sentence-Boundary Streaming Pattern

```python
# server/tts/tts_router.py

SENTENCE_ENDINGS = frozenset('.?!。？！…')

async def stream_tts(token_stream, lang: str, ws_sender):
    buffer = ""
    tts = get_tts_engine(lang)  # Returns CosyVoice2 or VOICEVOX instance

    async for token in token_stream:
        buffer += token
        if buffer and buffer[-1] in SENTENCE_ENDINGS and len(buffer) > 8:
            async for audio_chunk in tts.synthesize_stream(buffer):
                await ws_sender.send_bytes(audio_chunk)
            buffer = ""

    if buffer.strip():  # Flush remainder
        async for audio_chunk in tts.synthesize_stream(buffer):
            await ws_sender.send_bytes(audio_chunk)
```

#### CosyVoice2 (English)

- Model: `CosyVoice2-0.5B`
- VRAM: ~1.0 GB
- TTFA: ~150ms for first sentence
- Streaming: Both text input and audio output stream simultaneously
- License: Apache 2.0
- Integration: Python library, loaded into server process

#### VOICEVOX (Japanese)

- Deployment: Docker container `voicevox/voicevox_engine:latest`
- Port: `50021`
- Interface: REST API (audio_query → synthesis)
- License: LGPL, free commercial use

```python
# server/tts/voicevox_tts.py
import httpx, json

class VoicevoxTTS:
    BASE_URL = "http://voicevox:50021"
    DEFAULT_SPEAKER = 1  # Configurable per kiosk deployment

    async def synthesize_stream(self, text: str):
        async with httpx.AsyncClient() as client:
            query = (await client.post(
                f"{self.BASE_URL}/audio_query",
                params={"text": text, "speaker": self.DEFAULT_SPEAKER}
            )).json()
            resp = await client.post(
                f"{self.BASE_URL}/synthesis",
                params={"speaker": self.DEFAULT_SPEAKER},
                content=json.dumps(query),
                headers={"Content-Type": "application/json"}
            )
            yield resp.content  # WAV bytes (encode to Opus before sending)
```

#### Fish Speech v1.5 (JP Fallback)

- Used when VOICEVOX Docker container is unavailable
- Python library integration, GPU-accelerated
- Auto-activated by TTS router if VOICEVOX health check fails

---

### 4.6 RAG — Building Knowledge Base

**Database**: ChromaDB (local, persistent)
**Embeddings**: `intfloat/multilingual-e5-large`
**Retrieval**: Top-3 chunks, language-filtered

#### When to Use RAG vs Inline Context

- **≤ 50 rooms / 10 floors**: Embed full directory directly in system prompt (no ChromaDB needed, eliminates retrieval latency)
- **> 50 rooms or > 30,000 tokens of knowledge**: Use ChromaDB RAG

#### Document Format (Bilingual)

Each document chunk in the KB must include metadata: `{"lang": "en"|"ja", "floor": int|null, "type": "floor"|"facility"|"room"|"emergency"}`

#### RAG Implementation

```python
# server/rag/chroma_store.py
import chromadb
from .embedder import Embedder

class BuildingKB:
    def __init__(self, path: str):
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection("building_kb")
        self.embedder = Embedder()

    def ingest(self, docs: list[dict]):
        embeddings = self.embedder.encode([d["text"] for d in docs])
        self.collection.add(
            ids=[d["id"] for d in docs],
            embeddings=embeddings.tolist(),
            documents=[d["text"] for d in docs],
            metadatas=[{"lang": d["lang"], "floor": d.get("floor", -1)} for d in docs]
        )

    async def retrieve(self, query: str, lang: str, n: int = 3) -> str:
        q_emb = self.embedder.encode([query])
        results = self.collection.query(
            query_embeddings=q_emb.tolist(),
            n_results=n,
            where={"lang": lang}
        )
        return "\n\n".join(results["documents"][0])
```

#### RAG Parallelism

RAG retrieval must start as soon as the STT partial transcript reaches sufficient confidence — before the final transcript is confirmed. Implementation: launch `asyncio.create_task(kb.retrieve(...))` when STT emits a provisional result, then `await` the task result when building LLM prompt.

---

### 4.7 Language Detection

Language detection runs at two points:

1. **From audio (via Whisper)**: `info.language` from faster-whisper is authoritative for voice input. Confidence threshold: ≥ 0.8. If below threshold, fall back to Unicode block scan of the transcript.

2. **From keyboard text**: Unicode block scan (fast, no model needed).

```python
# server/lang/detector.py

def detect_from_unicode(text: str) -> str:
    """Fast Japanese detection by Unicode block presence."""
    jp_chars = sum(1 for c in text if '\u3000' <= c <= '\u9fff' or '\uff00' <= c <= '\uffef')
    return "ja" if jp_chars / max(len(text), 1) > 0.2 else "en"

def detect_language(text: str, whisper_lang: str = None, whisper_confidence: float = 0.0) -> str:
    if whisper_lang and whisper_confidence >= 0.8:
        return whisper_lang
    return detect_from_unicode(text)
```

All downstream components (RAG, LLM prompt, TTS router) use this detected language per turn.

---

### 4.8 Web Search Tool (SearXNG)

The LLM can call a `web_search` tool for current information not in the building KB.

**Service**: SearXNG (self-hosted Docker)
**Port**: `8080`
**No API key required**

```python
# server/search/searxng_client.py
import httpx

async def searxng_search(query: str, lang: str = "en") -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://searxng:8080/search",
            params={"q": query, "format": "json", "language": lang},
            timeout=5.0
        )
        results = resp.json()["results"][:3]
        return "\n\n".join(f"{r['title']}\n{r['content']}" for r in results)

# Tool schema for LLM function calling
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information not in the building directory",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    }
}
```

---

## 5. Data Flow & Protocol

### Complete Turn Lifecycle (Voice Input)

```
T=0ms    Client: VAD detects speech_end
T=3ms    Client: WS sends binary PCM16 audio blob
T=3ms    Server: receives audio, writes to AudioInputQueue
T=5ms    Server: STT worker starts transcription
T=20ms   Server: RAG worker launches (on partial STT result)
T=135ms  Server: STT returns final transcript + language
T=135ms  Server: sends {"type":"transcript", "text":"...", "lang":"en", "final":true}
T=138ms  Server: RAG result ready (was running in parallel)
T=140ms  Server: LLM worker starts, sends first prompt tokens to vLLM
T=290ms  Server: LLM emits first sentence boundary
T=292ms  Server: TTS worker starts CosyVoice2 synthesis on first sentence
T=440ms  Server: TTS first audio chunk ready
T=442ms  Server: sends binary Opus audio chunk to client
T=445ms  Client: decodes Opus, begins audio playback
T=450ms  *** User hears first audio ***
```

### Keyboard Input Turn Lifecycle

```
T=0ms    Client: user presses Enter on keyboard input
T=1ms    Client: WS sends {"type":"text_input","text":"...","lang":"auto"}
T=2ms    Server: receives JSON, detects language from Unicode scan
T=5ms    Server: RAG retrieval starts
T=8ms    Server: sends {"type":"status","state":"thinking"}
T=20ms   Server: RAG result ready, LLM starts
T=170ms  Server: LLM first sentence boundary
T=172ms  Server: TTS starts
T=320ms  Server: first audio chunk → client
T=325ms  *** User hears first audio ***
```

---

## 6. LLM Fallback Chain Specification

### Health Check Strategy

At server startup, probe all backends and log their status. Cache results for 60 seconds. Re-probe on failure.

```
Priority 1 — vLLM:
  endpoint: $VLLM_BASE_URL/v1/models
  health_check_interval: 30s
  first_token_timeout: 5s
  model: $VLLM_MODEL_NAME (default: qwen25)

Priority 2 — Ollama:
  endpoint: $OLLAMA_BASE_URL/v1/models
  health_check_interval: 60s
  first_token_timeout: 10s
  model: $OLLAMA_MODEL_NAME (default: qwen2.5:7b)
  note: Ollama must have the model pulled before use

Priority 3 — Grok API:
  endpoint: https://api.x.ai/v1/models
  health_check_interval: 120s
  first_token_timeout: 15s
  model: grok-3-fast
  requires: GROK_API_KEY env var
  privacy_note: Queries leave the local network. Only activate as last resort.
```

### Failure Modes

| Failure | Behavior |
|---|---|
| vLLM container not running | Immediately skip to Ollama |
| Ollama not running or model not pulled | Immediately skip to Grok |
| Grok API key missing | Send error event to client |
| All backends fail | Send `{"type":"error","code":"llm_unavailable"}` |
| Backend timeout mid-stream | Abort, try next backend, restart turn |

### Model Consistency Note

All three backends use Qwen2.5-compatible instruction format. Grok uses its own model but accepts the same OpenAI-compatible message format. The system prompt is identical across all backends. The primary quality difference: vLLM/Ollama use Qwen2.5 (best JP keigo), Grok uses Grok-3 (strong EN, good JP).

---

## 7. Latency Targets & Performance Engineering

### Latency Budget (Target: ~480ms TTFA)

| Stage | Duration | Notes |
|---|---|---|
| VAD end-of-speech | ~40ms | Client-side Silero VAD |
| LAN upload | ~3ms | Ethernet preferred |
| STT (Whisper Turbo) | ~130ms | faster-whisper, beam_size=1 |
| RAG retrieval | ~15ms | Parallel with STT — not additive |
| LLM TTFT (first token) | ~150ms | vLLM with KV cache warmed |
| TTS first sentence | ~150ms | CosyVoice2, ~8-word sentence |
| LAN download | ~3ms | |
| **Total TTFA** | **~480ms** | Concurrent pipeline |

### Key Optimizations (All Required)

1. **beam_size=1 in faster-whisper**: Greedy decoding. Fastest transcription.
2. **RAG parallel to STT**: `asyncio.create_task()` RAG retrieval on partial transcript.
3. **Sentence-boundary TTS**: Fire TTS on first `.?!。？！` — never wait for full LLM response.
4. **KV cache warming**: Pre-fill LLM with system prompt at startup.
5. **CUDA streams**: STT on dedicated CUDA stream, LLM on main stream.
6. **Embeddings on CPU**: Offload `multilingual-e5-large` to CPU — saves ~0.6 GB VRAM, adds ~30ms (acceptable).
7. **Whisper compute_type float16**: Reduces VRAM from ~2.5 GB to ~2.0 GB.
8. **Inter-token latency target**: < 15ms between LLM tokens to avoid TTS pausing.

### VRAM Budget (12 GB GPU)

| Component | VRAM |
|---|---|
| Whisper Large V3 Turbo (float16) | ~2.0 GB |
| Qwen2.5-7B Q4_K_M | ~4.2 GB |
| KV cache at 4k context | ~1.5 GB |
| CosyVoice2-0.5B | ~1.0 GB |
| CUDA runtime overhead | ~1.0 GB |
| **Total** | **~9.7 GB** (fits 12 GB, ~2.3 GB headroom) |

**16 GB GPU**: Upgrade LLM to Qwen2.5-14B (Q4_K_M, ~8.5 GB) for significantly better Japanese quality.

---

## 8. Infrastructure & Docker Compose

All server-side services run in Docker Compose. The Python kiosk client runs as a systemd service on the client machine (not containerized).

### Production docker-compose.yml

```yaml
version: "3.9"
services:

  voice-server:
    build: ./server
    ports:
      - "8765:8765"       # WebSocket for kiosk clients
    volumes:
      - "./models:/models"
      - "./building_kb:/kb"
      - "./chroma_data:/chroma"
    environment:
      - LLM_PRIMARY=vllm
      - VLLM_BASE_URL=http://llm:8000/v1
      - VLLM_MODEL_NAME=qwen25
      - OLLAMA_BASE_URL=http://ollama:11434/v1
      - OLLAMA_MODEL_NAME=qwen2.5:7b
      - GROK_API_KEY=${GROK_API_KEY}
      - STT_MODEL=large-v3-turbo
      - TTS_EN_ENGINE=cosyvoice2
      - TTS_JP_URL=http://voicevox:50021
      - CHROMADB_PATH=/chroma
      - BUILDING_NAME=${BUILDING_NAME:-"Building"}
    depends_on:
      - llm
      - ollama
      - voicevox
      - searxng
      - chromadb
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

  llm:
    image: vllm/vllm-openai:latest
    command: >
      --model Qwen/Qwen2.5-7B-Instruct
      --quantization awq
      --served-model-name qwen25
      --enable-auto-tool-choice
      --max-model-len 8192
      --port 8000
    volumes:
      - "./models:/root/.cache/huggingface"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    volumes:
      - "./ollama_data:/root/.ollama"
    ports:
      - "11434:11434"      # Exposed for development access
    restart: unless-stopped

  voicevox:
    image: voicevox/voicevox_engine:latest
    ports:
      - "50021:50021"
    restart: unless-stopped

  searxng:
    image: searxng/searxng:latest
    volumes:
      - "./searxng:/etc/searxng"
    ports:
      - "8080:8080"
    restart: unless-stopped

  chromadb:
    image: chromadb/chroma:latest
    volumes:
      - "./chroma_data:/chroma/chroma"
    ports:
      - "8200:8000"
    restart: unless-stopped
```

### Development Override (docker-compose.dev.yml)

```yaml
# Use with: docker compose -f docker-compose.yml -f docker-compose.dev.yml up
services:
  llm:
    # Disable vLLM in dev — use Ollama only
    profiles: ["disabled"]

  voice-server:
    environment:
      - LLM_PRIMARY=ollama   # Skip vLLM health check, go straight to Ollama
```

### Ollama Model Pull (First-Run)

```bash
# After starting docker compose, pull the Qwen model into Ollama
docker compose exec ollama ollama pull qwen2.5:7b
```

---

## 9. Configuration & Environment Variables

### Server Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | WebSocket bind address |
| `SERVER_PORT` | `8765` | WebSocket port |
| `LLM_PRIMARY` | `vllm` | Starting backend: `vllm`, `ollama`, or `grok` |
| `VLLM_BASE_URL` | `http://llm:8000/v1` | vLLM OpenAI-compatible URL |
| `VLLM_MODEL_NAME` | `qwen25` | Served model name in vLLM |
| `OLLAMA_BASE_URL` | `http://ollama:11434/v1` | Ollama URL |
| `OLLAMA_MODEL_NAME` | `qwen2.5:7b` | Ollama model tag |
| `GROK_API_KEY` | *(required for fallback)* | xAI Grok API key |
| `STT_MODEL` | `large-v3-turbo` | Whisper model size |
| `STT_COMPUTE_TYPE` | `float16` | `float16` or `int8` |
| `TTS_EN_ENGINE` | `cosyvoice2` | `cosyvoice2` or `chatterbox` |
| `TTS_JP_URL` | `http://voicevox:50021` | VOICEVOX REST URL |
| `TTS_JP_SPEAKER` | `1` | VOICEVOX speaker ID |
| `CHROMADB_PATH` | `/chroma` | ChromaDB persistent path |
| `KB_PATH` | `/kb` | Building knowledge base docs path |
| `BUILDING_NAME` | `Building` | Building name in system prompt |
| `USE_RAG` | `true` | `false` = inline KB in system prompt |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG base URL |
| `MAX_CONTEXT_TURNS` | `10` | Conversation history turns to keep |
| `LOG_LEVEL` | `INFO` | Python logging level |

### Client Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_WS_URL` | `ws://localhost:8765/ws` | Server WebSocket URL |
| `KIOSK_ID` | `kiosk-01` | Unique ID for this kiosk unit |
| `KIOSK_LOCATION` | `Floor 1 Lobby` | Sent to server for context |
| `AUDIO_INPUT_DEVICE` | `default` | sounddevice input device index |
| `AUDIO_OUTPUT_DEVICE` | `default` | sounddevice output device index |
| `UI_FULLSCREEN` | `true` | Start in fullscreen kiosk mode |
| `ENABLE_KEYBOARD_INPUT` | `true` | Show keyboard input widget |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## 10. Kiosk Deployment & OS Setup

### Ubuntu 22.04 Kiosk Hardening

```bash
# scripts/setup_kiosk_os.sh

# 1. Create restricted kiosk user
useradd -m -s /bin/bash kiosk
passwd -l kiosk  # Lock password (login via auto-login only)

# 2. Configure auto-login (GDM)
echo "[daemon]
AutomaticLoginEnable=true
AutomaticLogin=kiosk" >> /etc/gdm3/custom.conf

# 3. Disable TTY access
systemctl mask getty@tty1 getty@tty2 getty@tty3

# 4. Disable right-click and keyboard shortcuts (via GNOME settings for kiosk user)
# ... configure via dconf

# 5. Install Python and dependencies
apt-get install -y python3.11 python3.11-venv python3-pip \
  portaudio19-dev libopus-dev alsa-utils pulseaudio \
  python3-pyqt6

# 6. Create virtualenv and install client
python3.11 -m venv /opt/voice-kiosk/venv
/opt/voice-kiosk/venv/bin/pip install -r /opt/voice-kiosk/client/requirements.txt

# 7. Install and enable systemd service
cp /opt/voice-kiosk/client/kiosk.service /etc/systemd/system/voice-kiosk.service
systemctl daemon-reload
systemctl enable voice-kiosk
systemctl start voice-kiosk
```

### Audio Setup

```bash
# Ensure ALSA/PulseAudio works for kiosk user
usermod -a -G audio kiosk
# Set default audio device in /etc/asound.conf or PulseAudio default.pa
```

### Network Requirements

- Kiosk and server must be on the same private LAN (same VLAN preferred)
- Ethernet preferred over WiFi (< 5ms round-trip)
- Port 8765 must be open from kiosk to server
- No public internet access required for primary path
- Public internet required only for Grok fallback

---

## 11. Task Breakdown for Coding Agent

Tasks are grouped by component with explicit input/output contracts. Dependencies are listed. Execute in dependency order.

---

### GROUP A: Infrastructure & Configuration

#### TASK A1 — Repository Scaffold
**Description**: Create the full directory structure, `.env.example`, base `README.md`, `.gitignore` (ignore `models/`, `chroma_data/`, `ollama_data/`, `*.env`).
**Inputs**: Repository structure spec from Section 3
**Outputs**: All directories and placeholder files created
**Dependencies**: None

#### TASK A2 — Docker Compose (Production + Dev)
**Description**: Implement `docker-compose.yml` and `docker-compose.dev.yml` per Section 8.
**Inputs**: Service specs from Section 8
**Outputs**: Working `docker compose up` that starts all services
**Dependencies**: A1

#### TASK A3 — Server Configuration Module
**Description**: Implement `server/config.py` using `pydantic-settings`. Load all env vars from Section 9. Validate on startup.
**Outputs**: `Config` class importable by all server modules
**Dependencies**: A1

#### TASK A4 — Client Configuration Module
**Description**: Implement `client/config.py` loading client env vars from Section 9.
**Dependencies**: A1

---

### GROUP B: Server — Core Pipeline

#### TASK B1 — FastAPI WebSocket Server
**Description**: Implement `server/main.py`. FastAPI app with single WebSocket endpoint `/ws`. Accept connections, create per-connection pipeline instance, handle connection lifecycle (connect/disconnect/errors).
**Inputs**: Protocol spec from Section 5
**Outputs**: Running WebSocket server on port 8765, accepts connections
**Dependencies**: A2, A3
**Test**: Connect with `websocat ws://localhost:8765/ws`, send JSON, receive ACK

#### TASK B2 — Async Pipeline Orchestrator
**Description**: Implement `server/pipeline.py`. Create 5 asyncio queues (audio_input, transcript, rag_result, token, audio_output). Spawn all worker coroutines with `asyncio.gather()`. Implement interrupt/barge-in via shared `asyncio.Event`. Handle turn lifecycle.
**Inputs**: Pipeline stage spec from Section 4.2, data flow from Section 5
**Outputs**: `VoicePipeline` class that orchestrates all stages
**Dependencies**: B1

---

### GROUP C: Server — STT

#### TASK C1 — Whisper STT Wrapper
**Description**: Implement `server/stt/whisper_stt.py`. Load Whisper Large V3 Turbo via faster-whisper. Accept PCM16 bytes, return `(transcript: str, language: str, confidence: float)`. Use `beam_size=1`, `compute_type=float16`.
**Dependencies**: A3
**Test**: Pass recorded WAV bytes, verify transcript + language

#### TASK C2 — Text Cleaner
**Description**: Implement `server/stt/text_cleaner.py`. Functions: `remove_fillers(text, lang)`, `ensure_punctuation(text)`. Filler lists for EN and JP.
**Dependencies**: C1

---

### GROUP D: Server — Language Detection

#### TASK D1 — Language Detector
**Description**: Implement `server/lang/detector.py`. Two functions: `detect_from_unicode(text)` and `detect_language(text, whisper_lang, whisper_confidence)`. Returns `"en"` or `"ja"`.
**Dependencies**: A3
**Test**: Unit test with EN and JP strings

---

### GROUP E: Server — RAG

#### TASK E1 — Embedder
**Description**: Implement `server/rag/embedder.py`. Load `intfloat/multilingual-e5-large`. Expose `encode(texts: list[str]) -> np.ndarray`. Run on CPU.
**Dependencies**: A3

#### TASK E2 — ChromaDB Store
**Description**: Implement `server/rag/chroma_store.py`. `BuildingKB` class with `ingest(docs)` and `async retrieve(query, lang, n=3)` methods.
**Dependencies**: E1

#### TASK E3 — Building KB Ingestion Script
**Description**: Implement `server/rag/ingest.py`. CLI script: reads all `.md` files from `building_kb/`, chunks them (512 tokens max, 50 token overlap), detects language from path (`japanese/` → `ja`, else `en`), assigns metadata (floor, type). Calls `BuildingKB.ingest()`.
**Dependencies**: E2
**Test**: Run ingest, verify ChromaDB has documents, test retrieval query

---

### GROUP F: Server — LLM Fallback Chain

#### TASK F1 — Base LLM Backend Interface
**Description**: Define `server/llm/base.py`. Abstract base class `BaseLLMBackend` with `ping()` and `stream(messages, tools)` abstract methods.
**Dependencies**: A3

#### TASK F2 — vLLM Backend
**Description**: Implement `server/llm/vllm_backend.py`. Uses `AsyncOpenAI` pointed at vLLM. Implements `ping()` (models list), `stream()` (streaming chat completions).
**Dependencies**: F1

#### TASK F3 — Ollama Backend
**Description**: Implement `server/llm/ollama_backend.py`. Uses `AsyncOpenAI` pointed at Ollama. Same interface as F2.
**Dependencies**: F1

#### TASK F4 — Grok Backend
**Description**: Implement `server/llm/grok_backend.py`. Uses `AsyncOpenAI` pointed at `https://api.x.ai/v1`. Model: `grok-3-fast`. Read `GROK_API_KEY` from config.
**Dependencies**: F1

#### TASK F5 — Fallback Chain Orchestrator
**Description**: Implement `server/llm/fallback_chain.py`. `LLMFallbackChain` class. Health-check each backend in order. Try streaming from first healthy backend. On failure (timeout or exception), fall through to next. Raise if all fail.
**Inputs**: Spec from Section 6
**Dependencies**: F2, F3, F4
**Test**: Kill vLLM, verify Ollama takes over. Kill both, verify Grok takes over.

#### TASK F6 — Prompt Builder
**Description**: Implement `server/llm/prompt_builder.py`. `build_messages(user_text, lang, context, history, kiosk_meta)` per Section 4.4. System prompt template with RAG context injection.
**Dependencies**: F1

---

### GROUP G: Server — TTS

#### TASK G1 — TTS Router
**Description**: Implement `server/tts/tts_router.py`. `get_tts_engine(lang)` factory. Sentence-boundary streaming pattern per Section 4.5. Writes Opus-encoded audio chunks to WebSocket.
**Dependencies**: G2, G3, A3

#### TASK G2 — CosyVoice2 TTS
**Description**: Implement `server/tts/cosyvoice_tts.py`. `CosyVoiceTTS` class with `async synthesize_stream(text) -> AsyncIterator[bytes]`. Encode output to Opus.
**Dependencies**: A3

#### TASK G3 — VOICEVOX TTS Client
**Description**: Implement `server/tts/voicevox_tts.py`. `VoicevoxTTS` class using httpx. `audio_query` → `synthesis` REST flow. Returns WAV bytes, encode to Opus.
**Dependencies**: A3
**Test**: Verify VOICEVOX Docker is running, test JP synthesis

#### TASK G4 — Fish Speech Fallback
**Description**: Implement `server/tts/fish_speech_tts.py`. Activated when VOICEVOX health check fails. Same interface as VoicevoxTTS.
**Dependencies**: G1

---

### GROUP H: Server — Web Search

#### TASK H1 — SearXNG Client + Tool Schema
**Description**: Implement `server/search/searxng_client.py`. `searxng_search(query, lang)` async function. Implement `server/tools/tool_definitions.py` with `WEB_SEARCH_TOOL` schema.
**Dependencies**: A3

---

### GROUP I: Client — Python Application

#### TASK I1 — Audio Capture Module
**Description**: Implement `client/audio_capture.py`. Open sounddevice input stream, 16kHz, mono, PCM16. Emit 20ms frames (640 bytes) to asyncio queue. Handle device errors.
**Dependencies**: A4

#### TASK I2 — Silero VAD
**Description**: Implement `client/vad.py`. Wrap Silero VAD. Process 20ms frames. Emit `speech_start`, `speech_chunk`, `speech_end` events with accumulated audio buffer.
**Dependencies**: I1

#### TASK I3 — WebSocket Client
**Description**: Implement `client/ws_client.py`. Persistent WebSocket connection using `websockets`. Reconnect on disconnect (exponential backoff, max 30s). `send_audio(bytes)`, `send_json(dict)`, async iterator for incoming messages. Handle binary (audio) vs text (JSON) frames.
**Dependencies**: A4

#### TASK I4 — Audio Playback
**Description**: Implement `client/audio_playback.py`. Buffer incoming Opus-encoded audio chunks. Decode to PCM. Play via sounddevice output stream. Expose `stop()` for barge-in. Thread-safe.
**Dependencies**: I3

#### TASK I5 — Keyboard Input Handler
**Description**: Implement `client/keyboard_input.py`. Capture keyboard events from physical keyboard. On text submit (Enter key), emit text string to asyncio queue. Also expose API for programmatic submit (from on-screen keyboard widget).
**Dependencies**: A4

#### TASK I6 — PyQt6 UI — Main Window
**Description**: Implement `client/ui/app.py`. `KioskMainWindow(QMainWindow)`. Fullscreen, no window chrome. Embeds conversation widget, status indicator, keyboard input widget. Starts asyncio event loop in background thread (QThread + asyncio bridge).
**Dependencies**: I7, I8, I9

#### TASK I7 — Conversation Widget
**Description**: Implement `client/ui/conversation_widget.py`. Scrollable transcript display. Shows user text (right-aligned) and assistant text (left-aligned). Updates as `llm_text_chunk` events arrive.
**Dependencies**: None (pure UI)

#### TASK I8 — Status Indicator Widget
**Description**: Implement `client/ui/status_indicator.py`. Three visual states: listening (green pulse), thinking (amber spinner), speaking (blue wave). Updates on `status` events from server.
**Dependencies**: None (pure UI)

#### TASK I9 — Keyboard Input Widget
**Description**: Implement `client/ui/keyboard_widget.py`. Text input field + Submit button. Optional: on-screen keyboard panel (toggleable). Emits text on submit via signal to `keyboard_input.py`.
**Dependencies**: None (pure UI)

#### TASK I10 — Client Main Entry Point
**Description**: Implement `client/main.py`. Wire all modules: start asyncio event loop, create WebSocket client, start VAD+capture, start audio playback, launch PyQt6 app. Handle graceful shutdown (Ctrl+C, SIGTERM).
**Dependencies**: I1–I9

---

### GROUP J: Building Knowledge Base

#### TASK J1 — Building KB Document Set
**Description**: Create a complete set of bilingual `.md` documents in `building_kb/` for a representative 5-floor building. Cover: all floors (EN + JP), elevators, restrooms, exits, cafeteria, meeting rooms, room directory. Follow format from Section 4.6.
**Dependencies**: A1

#### TASK J2 — Ingest Script Execution & Verification
**Description**: Run `server/rag/ingest.py` against `building_kb/`. Verify ChromaDB has correct document count, language metadata, and returns sensible results for test queries in both EN and JP.
**Dependencies**: E3, J1

---

### GROUP K: Scripts & Tooling

#### TASK K1 — Model Download Script
**Description**: Implement `scripts/download_models.sh`. Download Whisper Large V3 Turbo (via huggingface-cli), multilingual-e5-large, CosyVoice2-0.5B. Save to `./models/`.
**Dependencies**: A1

#### TASK K2 — Kiosk OS Setup Script
**Description**: Implement `scripts/setup_kiosk_os.sh`. Per Section 10: create kiosk user, configure auto-login, disable TTYs, install Python deps, install and enable systemd service.
**Dependencies**: I10 (client must be deployable)

---

## 12. Dependency Graph

```
A1 (scaffold)
├── A2 (docker compose)
├── A3 (server config)     → B1 → B2
└── A4 (client config)     → I1–I10

A3 → C1 → C2
A3 → D1
A3 → E1 → E2 → E3
A3 → F1 → F2, F3, F4 → F5 → F6
A3 → G2, G3, G4 → G1
A3 → H1

B2 uses: C1+C2, D1, E2, F5+F6, G1, H1

A4 → I1 → I2
A4 → I3 → I4
A4 → I5
I7, I8, I9 → I6 → I10
I2, I3, I4, I5, I6 → I10

J1 → J2 (requires E3)
K1 (standalone)
K2 (requires I10 deployed)
```

**Critical path for first end-to-end test**:
A1 → A2 → A3 → B1 → B2 → C1 → F2 → F5 → G3 → G1 → B2 complete

---

## 13. Testing Strategy

### Unit Tests

- `test_lang_detector.py`: Test EN and JP detection from Unicode, from Whisper output
- `test_fallback_chain.py`: Mock backends, test fallback logic on simulated failures
- `test_sentence_boundary.py`: Test `ends_sentence()` with EN and JP strings
- `test_rag_retrieve.py`: Ingest fixture documents, test retrieval in EN and JP
- `test_text_cleaner.py`: Test filler word removal in both languages

### Integration Tests

- `test_websocket_pipeline.py`: Connect test client to running server, send recorded audio, assert transcript + audio response received
- `test_keyboard_input_pipeline.py`: Send JSON `text_input` message, assert audio response
- `test_llm_fallback_integration.py`: With vLLM stopped, verify Ollama responds. With both stopped, verify Grok responds.

### End-to-End Tests

- Manual: Launch full Docker Compose, launch kiosk client, speak EN query, verify audio response < 600ms
- Manual: Speak JP query, verify VOICEVOX audio response
- Manual: Type keyboard query, verify audio response
- Manual: Speak during TTS playback, verify barge-in stops playback and new query processed

### Performance Tests

- Measure TTFA for 20 consecutive voice queries, compute mean and p95
- Target: mean TTFA < 500ms, p95 < 800ms

---

## 14. Known Constraints & Hard Rules

1. **No GPU on client**. Client runs CPU-only. Silero VAD runs on CPU (it is specifically CPU-targeted).

2. **Python client, not Electron**. Client must be Python. No Node.js. No npm. No Electron. No browser. PyQt6 is the UI framework.

3. **LLM fallback is mandatory**. The system must not hard-fail when vLLM is unavailable. Ollama must work as a degraded-but-functional fallback. Grok must work as a last resort.

4. **Grok is privacy-sensitive**. Log a WARNING every time Grok is used. The building queries may contain location/person data. Only activate Grok when vLLM and Ollama are both unavailable.

5. **All audio on the wire is Opus-encoded**. PCM16 upstream (client → server), Opus downstream (server → client). This is non-negotiable for bandwidth efficiency.

6. **Barge-in is required**. Implement interrupt handling. Users must be able to speak while the assistant is speaking.

7. **Language detection is per-turn, not per-session**. A user can switch languages mid-conversation. Each turn independently detects language.

8. **Keyboard input is a first-class input mode**. It is not a fallback or afterthought. The UI must always show a keyboard input option.

9. **No hardcoded model paths**. All paths via environment variables / config.

10. **Server is stateless per-session**. All state (conversation history) is held in memory per WebSocket connection. No database for conversation state.

11. **LAN only for primary operation**. Kiosk and server on same private VLAN. Public internet only for Grok fallback.

12. **Docker Compose manages all server services**. No bare-metal systemd services on the server for AI components.

13. **The Ollama model must be pre-pulled before it can serve as fallback**. Include model pull in setup scripts and health check logic should account for model availability, not just service availability.

14. **vLLM and Ollama share the same GPU**. They cannot run simultaneously on a 12 GB GPU. In production, only vLLM runs; Ollama is the fallback activated when vLLM is down. The Docker Compose GPU allocation must reflect this (only the primary active service gets the GPU reservation).

---

*End of Implementation Specification*

*Version: 1.0 | April 2026 | Derived from Real-Time Voice Chatbot Implementation Report v2 Final*
