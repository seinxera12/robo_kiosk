# Running Without Docker — Dev/Demo Mode

This guide gets the full voice kiosk pipeline running directly on your machine
(WSL2 Ubuntu) without any Docker containers. Everything runs as native processes.

**Target:** Fast demo/dev iteration. No container build times, no networking layers,
logs directly in your terminal, easy to restart individual components.

---

## Architecture in No-Docker Mode

```
Windows Host
├── Ollama.exe  ← runs natively on Windows, GPU-accelerated
│
WSL2 Ubuntu (all Python processes)
├── VOICEVOX binary  ← runs as a native process
├── SearXNG          ← optional, skip for demo
│
├── server/          ← FastAPI + Whisper + RAG + TTS pipeline
│   └── uvicorn server.main:app  (port 8765 / 8000)
│
└── client/          ← PyQt6 UI + microphone + speakers
    └── python client/main.py
```

---

## What Changes vs Docker Mode

| Thing | Docker value | No-Docker value |
|-------|-------------|-----------------|
| Ollama URL | `http://ollama:11434/v1` | `http://localhost:11434/v1` |
| VOICEVOX URL | `http://voicevox:50021` | `http://localhost:50021` |
| SearXNG URL | `http://searxng:8080` | `http://localhost:8081` |
| ChromaDB path | `/chroma` | `./chroma_data` (relative) |
| STT device | `cuda` (inside container) | `cuda` or `cpu` (your choice) |

All of these are env vars — no code changes needed for the URL/path differences.

---

## Prerequisites

You need these installed before starting:

- WSL2 Ubuntu (you already have this)
- Python 3.11 in WSL2
- Ollama installed on **Windows** (not WSL2)
- VOICEVOX binary for Linux
- Git

---

## PHASE 1 — Install Ollama on Windows (LLM)

Ollama runs natively on Windows and exposes an HTTP API that WSL2 can reach.

### 1.1 Download and install

Go to **https://ollama.com/download** and download the Windows installer.
Run it. It installs as a background service automatically.

### 1.2 Pull the 3B model

Open **Windows PowerShell** (not Ubuntu) and run:

```powershell
ollama pull qwen2.5:3b-instruct
```

This downloads ~2GB. Wait for it to finish.

### 1.3 Verify Ollama is reachable from WSL2

In your **Ubuntu terminal**:

```bash
curl http://localhost:11434/api/tags
```

You should see a JSON response listing the model. If you get "connection refused",
open Ollama from the Windows Start menu and wait for it to show "Running".

> **Why localhost works:** WSL2 shares the Windows network stack. Ollama on Windows
> is reachable at `localhost` from inside WSL2.

---

## PHASE 2 — Install VOICEVOX (Japanese TTS)

VOICEVOX has a standalone Linux binary that runs without Docker.

### 2.1 Download the Linux engine

In your Ubuntu terminal:

```bash
cd ~
# Download VOICEVOX Engine for Linux (CPU version)
wget https://github.com/VOICEVOX/voicevox_engine/releases/latest/download/linux-cpu.tar.gz.sha256
wget https://github.com/VOICEVOX/voicevox_engine/releases/latest/download/linux-cpu.tar.gz

# Extract
tar -xzf linux-cpu.tar.gz
mv linux-cpu voicevox_engine
```

> **Note:** Check https://github.com/VOICEVOX/voicevox_engine/releases for the
> exact latest filename. The pattern is `linux-cpu.tar.gz` or `linux-nvidia.tar.gz`.

### 2.2 Start VOICEVOX

```bash
cd ~/voicevox_engine
./run --host 0.0.0.0 --port 50021
```

Leave this terminal open. VOICEVOX is now running at `http://localhost:50021`.

### 2.3 Verify

Open a new Ubuntu terminal and test:

```bash
curl http://localhost:50021/version
```

Expected: a version string like `"0.14.x"`.

---

## PHASE 3 — Set Up Python Environment

### 3.1 Navigate to the project

```bash
cd ~/voice-kiosk-chatbot
# or wherever your project is:
# cd /mnt/c/Users/YourName/voice-kiosk-chatbot
```

### 3.2 Create a single virtual environment for everything

In no-docker mode, server and client share one venv for simplicity:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Your prompt should now show `(.venv)`.

### 3.3 Install system-level audio dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
  portaudio19-dev \
  libsndfile1 \
  ffmpeg \
  libopus0 \
  libopus-dev \
  python3.11-dev \
  build-essential
```

### 3.4 Install Python packages

```bash
# Upgrade pip first
pip install --upgrade pip

# Install server dependencies
pip install -r server/requirements.txt

# Install client dependencies
pip install -r client/requirements.txt
```

This will take several minutes. Torch alone is ~2GB.

> **If torch install fails** with a CUDA error, install the CPU-only version first
> to verify everything else works:
> ```bash
> pip install torch==2.1.0 --index-url https://download.pytorch.org/whl/cpu
> ```
> Then reinstall with CUDA later.

---

## PHASE 4 — Create the No-Docker .env

Create a new env file specifically for no-docker mode. Keep your existing `.env`
as-is (for Docker mode) and create `.env.nodocker`:

```bash
cat > .env.nodocker << 'EOF'
# No-Docker dev mode configuration
# All services run as local processes on localhost

# General
LOG_LEVEL=DEBUG

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8765

# LLM — Ollama running on Windows, reachable at localhost from WSL2
# vLLM is disabled (not running)
VLLM_BASE_URL=http://localhost:8001/v1
VLLM_MODEL_NAME=disabled
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL_NAME=qwen2.5:3b-instruct
GROK_API_KEY=

# STT — Whisper runs inside the server process
# Use 'cuda' if you have GPU, 'cpu' if not
STT_MODEL=large-v3-turbo
STT_COMPUTE_TYPE=int8

# TTS — VOICEVOX running as local binary on port 50021
TTS_EN_ENGINE=cosyvoice
TTS_JP_URL=http://localhost:50021
COSYVOICE_MODEL_PATH=iic/CosyVoice2-0.5B
COSYVOICE_DEVICE=cuda

# RAG — ChromaDB stored locally in ./chroma_data
CHROMADB_PATH=./chroma_data

BUILDING_NAME=Demo Building

# SearXNG — optional, skip for demo (server handles missing gracefully)
SEARXNG_URL=http://localhost:8081

# Client
SERVER_WS_URL=ws://localhost:8765/ws
KIOSK_ID=dev-kiosk-01
KIOSK_LOCATION=Dev Desk
EOF
```

---

## PHASE 5 — Required Code Changes

The following changes are needed to run without Docker. They are **not yet implemented**.
Ask to implement them when ready.

---

### Change 1 — `server/pipeline.py`: Make STT device configurable

**File:** `server/pipeline.py`
**Location:** `VoicePipeline.__init__`, line where `WhisperSTT` is constructed

**Current code:**
```python
self.stt = WhisperSTT(
    model_size=config.stt_model,
    device="cuda",           # ← hardcoded
    compute_type=config.stt_compute_type
)
```

**Suggested change:**
```python
import torch
stt_device = "cuda" if torch.cuda.is_available() else "cpu"

self.stt = WhisperSTT(
    model_size=config.stt_model,
    device=stt_device,       # ← auto-detect
    compute_type=config.stt_compute_type
)
```

**Why:** Without Docker, the server runs directly on your machine. If CUDA isn't
available (or you want to test on CPU), the hardcoded `"cuda"` will crash on startup.

---

### Change 2 — `server/llm/fallback_chain.py`: Skip GrokBackend when key is empty

**File:** `server/llm/fallback_chain.py`
**Location:** `LLMFallbackChain.__init__`

**Current code:**
```python
self.backends = [
    VLLMBackend(config),
    OllamaBackend(config),
    GrokBackend(config)      # ← raises ValueError if GROK_API_KEY is empty
]
```

**Suggested change:**
```python
backends = [VLLMBackend(config), OllamaBackend(config)]
if config.GROK_API_KEY:
    backends.append(GrokBackend(config))
self.backends = backends
```

**Why:** `GrokBackend.__init__` raises `ValueError` if `GROK_API_KEY` is empty.
In no-docker mode (and in the current `.env`) the key is blank, so the entire
fallback chain fails to initialize and the server crashes before accepting any connection.

---

### Change 3 — `server/tts/tts_router.py`: Fix `asyncio.run()` inside async context

**File:** `server/tts/tts_router.py`
**Location:** `TTSRouter.get_engine`, the VOICEVOX health check

**Current code:**
```python
if self.voicevox and asyncio.run(self.voicevox.health_check()):
```

**Suggested change:**
```python
# get_engine is called from inside an async context (tts_worker)
# asyncio.run() creates a new event loop and crashes inside an existing one.
# Replace with a synchronous flag set during initialization.

# In __init__, add:
#   self._voicevox_healthy = False
#   asyncio.get_event_loop().run_until_complete(self._check_voicevox())

# Or simpler: just return voicevox and let synthesize_stream handle the error.
if lang == "en":
    return self.cosyvoice
else:
    return self.voicevox   # VoicevoxTTS.synthesize_stream already handles errors
```

**Why:** `asyncio.run()` cannot be called when an event loop is already running
(which it always is inside the FastAPI/uvicorn server). This will raise
`RuntimeError: This event loop is already running` the first time a Japanese
response is generated.

---

### Change 4 — `server/config.py`: Add `STT_DEVICE` env var

**File:** `server/config.py`

**Suggested addition** to `Config` dataclass:
```python
stt_device: str = "cuda"   # new field
```

And in `from_env()`:
```python
stt_device=os.getenv("STT_DEVICE", "cuda"),
```

Then in `server/pipeline.py` use `config.stt_device` instead of auto-detecting.

**Why:** Gives explicit control via `.env.nodocker` — set `STT_DEVICE=cpu` for
CPU-only testing without changing code.

Add to `.env.nodocker`:
```
STT_DEVICE=cuda
# or:
STT_DEVICE=cpu
```

---

### Change 5 — `server/rag/chroma_store.py`: Handle empty collection gracefully

**File:** `server/rag/chroma_store.py`
**Location:** `BuildingKB.retrieve`

**Current code:**
```python
results = self.collection.query(
    query_embeddings=query_embedding.tolist(),
    n_results=n,
    where={"lang": lang}
)
```

**Suggested change:**
```python
# ChromaDB raises an error if the collection has fewer documents than n_results
# and also if the collection is empty. Wrap in try/except for dev mode.
try:
    count = self.collection.count()
    if count == 0:
        logger.warning("ChromaDB collection is empty — skipping RAG retrieval")
        return ""
    results = self.collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=min(n, count),   # don't request more than available
        where={"lang": lang}
    )
except Exception as e:
    logger.warning(f"RAG retrieval failed: {e} — continuing without context")
    return ""
```

**Why:** In dev mode you might start the server before running the ingestion script.
Without this guard, the first query crashes the `llm_worker` with a ChromaDB error
and the pipeline stops processing.

---

### Change 6 — `client/main.py`: Add `--no-ui` flag for headless testing

**File:** `client/main.py`

**Suggested change:** Add a `--no-ui` CLI argument that skips PyQt6 entirely and
runs a simple terminal loop instead:

```python
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ui", action="store_true",
                        help="Run in headless mode (terminal only, no PyQt6 window)")
    args = parser.parse_args()

    from client.config import ClientConfig
    config = ClientConfig.from_env()

    if args.no_ui:
        # Headless mode: just connect WebSocket and print responses
        asyncio.run(run_headless(config))
    else:
        # Full UI mode
        run_qt(config)
```

**Why:** PyQt6 requires a display. In WSL2 without WSLg or VcXsrv configured,
the UI will fail to open. A headless mode lets you test the full voice pipeline
(microphone → server → LLM → TTS → speaker) without needing a working display.

---

## PHASE 6 — Ingest the Knowledge Base

Before starting the server, load the building documents into ChromaDB.

Make sure your venv is active and you're in the project root:

```bash
source .venv/bin/activate
cd ~/voice-kiosk-chatbot

# Load the .env.nodocker values
export $(grep -v '^#' .env.nodocker | xargs)

# Run ingestion
python3 server/rag/ingest.py \
  --kb-path building_kb \
  --chroma-path ./chroma_data
```

Expected output:
```
INFO - Processing: building_kb/floors/floor_01.md
INFO - Processing: building_kb/floors/floor_02.md
...
INFO - Ingesting 12 total chunks into ChromaDB...
INFO - Ingestion complete!
```

---

## PHASE 7 — Start the Server

Open a dedicated terminal for the server. Keep it open — you'll watch logs here.

```bash
cd ~/voice-kiosk-chatbot
source .venv/bin/activate

# Load no-docker env
export $(grep -v '^#' .env.nodocker | xargs)

# Add project root to Python path so imports work
export PYTHONPATH=$(pwd)

# Start the server
uvicorn server.main:app \
  --host 0.0.0.0 \
  --port 8765 \
  --log-level info \
  --reload
```

The `--reload` flag auto-restarts the server when you edit any Python file.
Remove it if you don't want that.

**Expected startup output:**
```
INFO:     Loading WhisperSTT: model=large-v3-turbo, device=cuda, compute_type=int8
INFO:     WhisperSTT initialized successfully
INFO:     Initialized LLM fallback chain with 2 backends
INFO:     Initialized BuildingKB with path: ./chroma_data
INFO:     Initialized TTS router
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8765
```

**Verify the server is healthy:**

Open another terminal and run:
```bash
curl http://localhost:8765/health
```

Expected:
```json
{"status":"healthy","service":"voice-kiosk-chatbot","version":"1.0.0"}
```

---

## PHASE 8 — Test With Text (No Microphone Needed)

Before running the full client, verify the pipeline end-to-end using wscat.

```bash
# Install wscat if not already installed
sudo apt-get install -y nodejs npm
sudo npm install -g wscat

# Connect
wscat -c ws://localhost:8765/ws
```

Type these messages one at a time, pressing Enter after each:

```json
{"type": "session_start", "kiosk_id": "dev-01", "kiosk_location": "Dev Desk"}
```

```json
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "en"}
```

You should see the server streaming back:
```json
{"type":"transcript","text":"Where is the cafeteria?","lang":"en","final":true}
{"type":"llm_text_chunk","text":"The cafeteria ","final":false}
{"type":"llm_text_chunk","text":"is located on ","final":false}
...
```

Press `Ctrl+C` to disconnect.

---

## PHASE 9 — Run the Full Client

### 9.1 If you have a working display (WSLg on Windows 11, or VcXsrv)

```bash
cd ~/voice-kiosk-chatbot
source .venv/bin/activate
export $(grep -v '^#' .env.nodocker | xargs)
export PYTHONPATH=$(pwd)
export DISPLAY=:0

python3 client/main.py
```

### 9.2 If you don't have a display (headless / Windows 10 WSL2)

Once Change 6 is implemented:

```bash
python3 client/main.py --no-ui
```

This runs the full pipeline (microphone → VAD → WebSocket → server → TTS → speaker)
in the terminal without any GUI.

---

## PHASE 10 — Daily Dev Workflow

Once everything is set up, here's the fast restart sequence:

**Terminal 1 — VOICEVOX (keep running):**
```bash
cd ~/voicevox_engine && ./run --host 0.0.0.0 --port 50021
```

**Terminal 2 — Server:**
```bash
cd ~/voice-kiosk-chatbot
source .venv/bin/activate
export $(grep -v '^#' .env.nodocker | xargs)
export PYTHONPATH=$(pwd)
uvicorn server.main:app --host 0.0.0.0 --port 8765 --reload
```

**Terminal 3 — Client:**
```bash
cd ~/voice-kiosk-chatbot
source .venv/bin/activate
export $(grep -v '^#' .env.nodocker | xargs)
export PYTHONPATH=$(pwd)
python3 client/main.py
```

Ollama on Windows starts automatically on boot — no action needed.

---

## Troubleshooting

### "RuntimeError: This event loop is already running"

This is Change 3 (tts_router.py). The `asyncio.run()` call inside `get_engine()`
crashes inside the FastAPI event loop. Ask to implement Change 3.

### "ValueError: GROK_API_KEY required for Grok backend"

This is Change 2 (fallback_chain.py). Ask to implement Change 2.

### "RuntimeError: CUDA error" or "device not found"

The STT device is hardcoded to `"cuda"`. Ask to implement Change 1 or Change 4,
or temporarily set `STT_DEVICE=cpu` in `.env.nodocker`.

### "chromadb.errors.InvalidCollectionException" or similar

The collection is empty. Run the ingestion script (Phase 6) first.
Or ask to implement Change 5 which makes the server tolerant of an empty collection.

### Ollama returns "model not found"

```bash
# On Windows PowerShell:
ollama pull qwen2.5:3b-instruct
ollama list   # verify it's there
```

### VOICEVOX "connection refused"

VOICEVOX isn't running. Start it in Terminal 1 (Phase 7 above).

### Server starts but Whisper takes a long time to load

Normal on first run — Whisper downloads the model weights (~1.5GB for large-v3-turbo).
Subsequent starts are fast because the weights are cached in `~/.cache/huggingface/`.

### "No module named 'server'"

`PYTHONPATH` isn't set. Run:
```bash
export PYTHONPATH=$(pwd)
```
from the project root before starting the server.

---

## Summary of Required Code Changes

| # | File | What | Priority |
|---|------|------|----------|
| 1 | `server/pipeline.py` | Auto-detect CUDA vs CPU for STT | **Must fix** — crashes on CPU |
| 2 | `server/llm/fallback_chain.py` | Skip GrokBackend when key is empty | **Must fix** — crashes on startup |
| 3 | `server/tts/tts_router.py` | Replace `asyncio.run()` with async-safe call | **Must fix** — crashes on first JP response |
| 4 | `server/config.py` | Add `STT_DEVICE` env var | Nice to have |
| 5 | `server/rag/chroma_store.py` | Handle empty collection gracefully | Nice to have |
| 6 | `client/main.py` | Add `--no-ui` headless mode | Nice to have for WSL2 without display |

Changes 1, 2, and 3 are blockers — the server will crash without them.
Changes 4, 5, and 6 improve the dev experience but aren't strictly required
if you have CUDA, a Grok key, and a working display.
