# TECHNICAL AUDIT

# Voice Kiosk Chatbot — Full Technical Audit

**Document version:** 1.0  
**Audit date:** May 10, 2026  
**Auditor:** Kiro (automated analysis)  
**Project root:** `/home/seinxera12/robotic_robo`  
**Purpose:** Complete technical documentation of the existing system to support future lightweight demo planning. No changes were made to the codebase during this audit.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Model Inventory](#2-model-inventory)
3. [Dependency Audit](#3-dependency-audit)
4. [Repository Structure](#4-repository-structure)
5. [Runtime & Startup Flow](#5-runtime--startup-flow)
6. [Storage Analysis](#6-storage-analysis)
7. [Resource Requirements](#7-resource-requirements)
8. [Pain Point Analysis](#8-pain-point-analysis)
9. [Demo Feasibility Notes](#9-demo-feasibility-notes)

---

## 1. High-Level Architecture

### 1.1 System Overview

The project is a **fully self-hosted, bilingual (English + Japanese) real-time streaming voice chatbot** designed for kiosk and robot deployment. It targets sub-600 ms Time-to-First-Audio (TTFA) through aggressive pipeline parallelisation, sentence-boundary TTS streaming, and a three-tier LLM fallback chain.

The system is split into two physically separate processes that communicate over a single persistent WebSocket connection:

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLIENT PROCESS  (CPU — kiosk hardware / WSL2 desktop)              │
│                                                                     │
│  Microphone ──► AudioCapture ──► SileroVAD ──► WebSocket ──►       │
│                                                                     │
│  ◄── WebSocket ──► AudioPlayback ──► Speaker                        │
│  ◄── WebSocket ──► PyQt6 UI (text display)                          │
└─────────────────────────────────────────────────────────────────────┘
                          │  ws://host:8765/ws
                          │  Binary PCM16 audio (up)
                          │  Binary WAV audio (down)
                          │  JSON control messages (both)
┌─────────────────────────────────────────────────────────────────────┐
│  SERVER PROCESS  (GPU — Ubuntu 24.04 / WSL2)                        │
│                                                                     │
│  WebSocket ──► audio_input_worker ──► WhisperSTT                    │
│                       │                                             │
│                       ▼                                             │
│               llm_worker ──► IntentClassifier                       │
│                   │              │                                  │
│                   │         ┌────┴────────────┐                     │
│                   │         ▼                 ▼                     │
│                   │    BuildingKB (RAG)   SearXNG (search)          │
│                   │         │                 │                     │
│                   │         └────┬────────────┘                     │
│                   │              ▼                                  │
│                   │    LLMFallbackChain                              │
│                   │    (vLLM → Ollama → Grok API)                   │
│                   │                                                 │
│                   ▼                                                 │
│               tts_worker ──► TTSRouter                              │
│                                  │                                  │
│                         ┌────────┴────────┐                         │
│                         ▼                 ▼                         │
│                   KokoroTTS (EN)    KokoCloneTTS (JA)               │
│                                  KokoroJapaneseTTS (JA fallback)    │
│                         │                 │                         │
│                         └────────┬────────┘                         │
│                                  ▼                                  │
│               audio_output_worker ──► WebSocket ──► Client          │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Main Services / Components

| Component | Location | Role | Mandatory |
|-----------|----------|------|-----------|
| **voice-server** | `server/` | FastAPI WebSocket server, pipeline orchestrator | Yes |
| **WhisperSTT** | `server/stt/` | Speech-to-text via faster-whisper | Yes |
| **LLMFallbackChain** | `server/llm/` | vLLM → Ollama → Grok API fallback | Yes (≥1 backend) |
| **BuildingKB / RAG** | `server/rag/` | ChromaDB + multilingual-e5-large embeddings | Optional (USE_RAG=false) |
| **TTSRouter** | `server/tts/` | Routes EN/JA to correct TTS engine | Yes |
| **KokoroTTS** | `server/tts/kokoro_tts.py` | In-process English TTS (Kokoro-82M) | Yes (EN) |
| **KokoCloneTTS** | `server/tts/kokoclone_tts.py` | HTTP client to KokoClone microservice (JA primary) | Optional |
| **KokoroJapaneseTTS** | `server/tts/kokoro_tts.py` | In-process Japanese TTS (Kokoro-82M) | Yes (JA fallback) |
| **KokoClone microservice** | `kokoclone/` | Zero-shot voice cloning server (Python 3.12 venv) | Optional |
| **CosyVoice2 service** | `cosyvoice_service/` | Legacy English TTS (Docker, currently unused) | No (replaced by Kokoro) |
| **Ollama** | Docker container | Secondary LLM backend | Yes (primary in practice) |
| **vLLM** | Docker container (commented out) | Primary LLM backend (disabled) | No |
| **VOICEVOX** | Docker container | Legacy Japanese TTS (currently unused) | No |
| **SearXNG** | Docker container | Self-hosted web search | Optional |
| **ChromaDB** | `chroma_db/`, `chroma_data/` | Vector store for RAG | Optional |
| **Client** | `client/` | PyQt6 kiosk UI + audio I/O | Yes (client side) |

### 1.3 Voice Flow Through the System

```
User speaks
    │
    ▼
[CLIENT] sounddevice InputStream (16kHz PCM16, 32ms frames)
    │
    ▼
[CLIENT] SileroVAD — accumulates frames, detects speech_end after 800ms silence
    │  speech_buffer (variable length PCM16 bytes)
    ▼
[CLIENT] WebSocket.send_bytes(pcm16_audio)
    │
    ▼  ── network ──
    │
    ▼
[SERVER] websocket_receiver → audio_input queue
    │
    ▼
[SERVER] audio_input_worker
    │  faster-whisper (GPU, beam_size=1, no VAD filter)
    │  → TranscriptionResult(text, language, confidence)
    ▼
[SERVER] transcript queue
    │
    ▼
[SERVER] llm_worker
    │  IntentClassifier (keyword → embedding similarity)
    │  → Intent: BUILDING | SEARCH | GENERAL
    │
    ├─ BUILDING → BuildingKB.retrieve() (ChromaDB, top-3 chunks)
    ├─ SEARCH   → SearXNG HTTP search → format_search_context()
    └─ GENERAL  → empty context
    │
    │  build_messages() → OpenAI chat format
    │  LLMFallbackChain.stream_with_fallback()
    │  → token stream (Ollama / vLLM / Grok)
    ▼
[SERVER] token queue  (also sent to client as llm_text_chunk JSON)
    │
    ▼
[SERVER] tts_worker
    │  Accumulates tokens until sentence boundary (.?!。？！…)
    │  TTSRouter.synthesize_stream(sentence, lang)
    │    EN → KokoroTTS (in-process, Kokoro-82M, 24kHz WAV)
    │    JA → KokoCloneTTS (HTTP POST to :5003) → KokoroJapaneseTTS fallback
    ▼
[SERVER] audio_output queue
    │
    ▼
[SERVER] audio_output_worker → WebSocket.send_bytes(wav_chunk)
    │
    ▼  ── network ──
    │
    ▼
[CLIENT] AudioPlayback.queue_audio(wav_bytes)
    │  wave.open() decode → PCM16 numpy array
    ▼
[CLIENT] sounddevice OutputStream → Speaker
```

### 1.4 Pipeline Concurrency Model

The server runs **five concurrent asyncio coroutines** per WebSocket connection, launched via `asyncio.gather()`:

```
websocket_receiver()    — receives audio/JSON from client
audio_input_worker()    — STT (Whisper runs in ThreadPoolExecutor)
llm_worker()            — intent + RAG/search + LLM streaming
tts_worker()            — sentence-boundary TTS synthesis
audio_output_worker()   — sends WAV chunks to client
```

All inter-stage communication uses `asyncio.Queue`. CPU-heavy inference (Whisper, embeddings, Kokoro) runs in `ThreadPoolExecutor` via `run_in_executor` to avoid blocking the event loop. External services (Ollama, SearXNG, KokoClone) are called via `httpx.AsyncClient` (non-blocking).

### 1.5 Optional vs Mandatory Components

**Mandatory (system cannot function without these):**
- FastAPI server + uvicorn
- WhisperSTT (faster-whisper)
- At least one LLM backend (Ollama is the practical default)
- KokoroTTS (English)
- KokoroJapaneseTTS (Japanese fallback)
- Client audio stack (sounddevice, SileroVAD)
- WebSocket transport (websockets)

**Optional (graceful degradation if absent):**
- RAG / ChromaDB (disabled via `USE_RAG=false`)
- SearXNG (search falls back to GENERAL intent)
- KokoCloneTTS / KokoClone microservice (falls back to KokoroJapaneseTTS)
- CosyVoice2 service (replaced by Kokoro, Docker compose file kept for reference)
- VOICEVOX (replaced by Kokoro JP, Docker compose kept for reference)
- vLLM (commented out in docker-compose.yml, disabled via `VLLM_MODEL_NAME=disabled`)
- Grok API (cloud fallback, requires API key)
- PyQt6 UI (headless `--no-ui` and `--text` modes available)

---

## 2. Model Inventory

### 2.1 Active Models (currently in use)

| # | Model Name | Purpose | Local/API | Est. Disk | Est. VRAM/RAM | Quantization | Load Method | Notes |
|---|-----------|---------|-----------|-----------|---------------|-------------|-------------|-------|
| 1 | **Whisper Large V3 Turbo** (`large-v3`) | Speech-to-Text | Local | ~1.6 GB | ~2–3 GB VRAM | int8 (ctranslate2) | faster-whisper auto-download from HF | Config: `STT_MODEL=large-v3`, `STT_COMPUTE_TYPE=int8` |
| 2 | **Kokoro-82M** (`hexgrad/Kokoro-82M`) | English TTS + Japanese TTS | Local | ~330 MB | ~500 MB RAM (CPU) | float32 | `kokoro.KPipeline`, lazy-loaded on first synthesis | Shared model for EN (`lang_code='a'`) and JA (`lang_code='j'`) pipelines |
| 3 | **multilingual-e5-large** (`intfloat/multilingual-e5-large`) | RAG embeddings + intent classification | Local | ~560 MB | ~1 GB RAM (CPU) | float32 | `sentence_transformers.SentenceTransformer`, loaded at server startup | 1024-dim embeddings; shared between BuildingKB and IntentClassifier |
| 4 | **Qwen2.5-7B-Instruct** (via Ollama) | Primary LLM inference | Local | ~4.7 GB (Q4_K_M) | ~5–6 GB VRAM | GGUF Q4_K_M | Ollama pulls on first use | Model name: `qwen2.5:7b-instruct`; served via Ollama OpenAI-compat API |
| 5 | **Silero VAD** (`snakers4/silero-vad`) | Voice Activity Detection | Local | ~2 MB | ~50 MB RAM (CPU) | float32 | `torch.hub.load`, auto-download | Runs on client CPU; 32ms frames at 16kHz |
| 6 | **Kanade voice conversion model** (KokoClone) | Zero-shot Japanese voice cloning | Local | ~1–2 GB (est.) | ~2–4 GB VRAM | float32 | `core.cloner.KokoClone()` at KokoClone service startup | Requires reference WAV; runs in separate Python 3.12 venv |
| 7 | **Kokoro-ONNX** (inside KokoClone) | TTS stage within KokoClone pipeline | Local | ~150 MB | ~300 MB RAM | ONNX int8 | `kokoro_onnx.Kokoro`, cached in `cloner.kokoro_cache` | Used as TTS front-end before Kanade VC |

### 2.2 Inactive / Legacy Models (present in config, not actively used)

| # | Model Name | Purpose | Status | Notes |
|---|-----------|---------|--------|-------|
| 8 | **CosyVoice2-0.5B** (`iic/CosyVoice2-0.5B`) | English TTS (legacy) | Inactive — replaced by Kokoro | Docker service defined in `docker-compose.cosyvoice.yml`; `cosyvoice_service/` still present |
| 9 | **Qwen2.5-7B-Instruct-AWQ** (`Qwen/Qwen2.5-7B-Instruct-AWQ`) | Primary LLM via vLLM | Inactive — vLLM commented out | AWQ 4-bit quantized; ~4 GB disk; requires vLLM container |
| 10 | **VOICEVOX engine** | Japanese TTS (legacy) | Inactive — replaced by Kokoro JP | Docker image `voicevox/voicevox_engine:latest`; CPU-only |

### 2.3 Model Dependency Relationships

```
Server startup
├── WhisperSTT ──────────────────── faster-whisper → ctranslate2 → CUDA
├── LLMFallbackChain
│   ├── OllamaBackend ────────────── HTTP → Ollama container → Qwen2.5-7B GGUF
│   ├── VLLMBackend (disabled) ───── HTTP → vLLM container (commented out)
│   └── GrokBackend (optional) ───── HTTPS → xAI API
├── BuildingKB
│   └── Embedder ─────────────────── sentence-transformers → multilingual-e5-large (CPU)
└── TTSRouter
    ├── KokoroTTS ────────────────── kokoro.KPipeline → Kokoro-82M (CPU/CUDA, lazy)
    ├── KokoCloneTTS ─────────────── HTTP → KokoClone service (:5003)
    │                                    └── Kanade VC + Kokoro-ONNX (Python 3.12 venv)
    └── KokoroJapaneseTTS ────────── kokoro.KPipeline → Kokoro-82M JP (CPU, lazy)

IntentClassifier
└── reuses BuildingKB.embedder ───── no extra model load
```

### 2.4 Audio Format Summary

| Stage | Format | Sample Rate | Bit Depth | Channels |
|-------|--------|-------------|-----------|----------|
| Microphone capture | PCM16 | 16 kHz | 16-bit int | Mono |
| VAD input | float32 tensor | 16 kHz | 32-bit float | Mono |
| WebSocket upload | PCM16 bytes | 16 kHz | 16-bit int | Mono |
| Whisper input | float32 numpy | 16 kHz | 32-bit float | Mono |
| Kokoro output | WAV (PCM16) | 24 kHz | 16-bit int | Mono |
| KokoClone output | WAV (PCM16) | 24 kHz | 16-bit int | Mono |
| WebSocket download | WAV bytes | 24 kHz | 16-bit int | Mono |
| Playback | PCM16 numpy | 24 kHz | 16-bit int | Mono |

---

## 3. Dependency Audit

### 3.1 Runtime Environment

| Property | Value |
|----------|-------|
| **OS** | Ubuntu 24.04.4 LTS (Noble) |
| **Kernel** | 6.6.87.2-microsoft-standard-WSL2 |
| **Platform** | WSL2 on Windows (x86_64) |
| **Host machine** | Lenovo LOQ laptop |
| **Python (server venv)** | 3.11 (active venv at `/home/seinxera12/robotic_robo/venv`) |
| **Python (KokoClone venv)** | 3.12 (separate venv at `kokoclone/.venv`, managed by `uv`) |
| **Package manager (server)** | pip (venv) |
| **Package manager (KokoClone)** | uv |
| **CUDA (runtime)** | 12.1 (via `LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64`) |
| **CUDA (system toolkit)** | 13.2 (apt: `cuda-toolkit-13-2`) |
| **nvcc** | NOT in PATH (nvcc not found; toolkit installed but not on PATH) |
| **cuDNN** | cu12: 8.9.2.26 (pip), cu13: 9.19.0.56 (pip) |
| **NCCL** | cu12: 2.18.1 (pip), cu13: 2.28.9 (pip) |
| **GPU** | NVIDIA GeForce RTX 4050 Laptop GPU |
| **GPU VRAM** | 6 GB (6141 MiB total) |
| **Driver version** | 581.86 (Windows host) |
| **NVIDIA-SMI** | 580.110 (WSL2 side) |
| **Docker** | Present (docker-compose.yml used for Ollama, SearXNG, VOICEVOX) |

### 3.2 Python Version Split

The project uses **two separate Python environments** to avoid version conflicts:

```
/home/seinxera12/robotic_robo/
├── venv/                    ← Python 3.11, pip-managed
│   └── Used by: server/, client/, cosyvoice_service/ (if run locally)
└── kokoclone/.venv/         ← Python 3.12, uv-managed
    └── Used by: kokoclone/ (KokoClone microservice only)
```

This split exists because KokoClone's dependencies (`torch>=2.10.0`, `kokoro-onnx[gpu]>=0.5.0`) require Python 3.12 and conflict with the server's pinned `torch==2.1.2+cu121`.

### 3.3 Core Python Dependencies (server venv — frozen versions)

#### Framework & Server
| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | 0.136.0 | WebSocket + HTTP server |
| uvicorn | 0.44.0 | ASGI server |
| starlette | 0.52.1 | ASGI framework (fastapi dep) |
| websockets | 15.0.1 | WebSocket protocol |
| pydantic | 2.12.3 | Data validation |
| python-dotenv | 1.0.0 | .env loading |

#### AI / ML Core
| Package | Version | Purpose | CUDA |
|---------|---------|---------|------|
| torch | 2.1.2+cu121 | Deep learning runtime | Yes (CUDA 12.1) |
| torchaudio | 2.1.2+cu121 | Audio processing | Yes |
| torchvision | 0.16.2+cu121 | Vision (dep) | Yes |
| triton | 2.1.0 | GPU kernel compiler (torch dep) | Yes |
| faster-whisper | 0.10.0 | Whisper STT wrapper | Via ctranslate2 |
| ctranslate2 | 4.7.1 | Optimised inference engine | Yes |
| sentence-transformers | 2.6.1 | Multilingual embeddings | CPU |
| transformers | 4.41.2 | HuggingFace model hub | — |
| kokoro | 0.9.4 | Kokoro-82M TTS | CPU/CUDA |
| misaki | 0.9.4 | G2P phonemiser for Kokoro | — |
| openai | 1.3.0 | OpenAI-compat client (Ollama/vLLM) | — |

#### Vector Database
| Package | Version | Purpose |
|---------|---------|---------|
| chromadb | 0.4.18 | Vector store |
| chroma-hnswlib | 0.7.3 | HNSW index (chromadb dep) |
| onnxruntime | 1.24.4 | ONNX inference (chromadb dep) |

#### Audio Processing
| Package | Version | Purpose |
|---------|---------|---------|
| sounddevice | 0.4.6 | Microphone / speaker I/O |
| soundfile | 0.13.1 | WAV read/write |
| numpy | 1.26.4 | Array operations |
| librosa | 0.11.0 | Audio analysis (CosyVoice dep) |

#### HTTP & Networking
| Package | Version | Purpose |
|---------|---------|---------|
| httpx | 0.25.1 | Async HTTP client |
| aiohttp | 3.13.5 | Async HTTP (various deps) |
| requests | 2.33.1 | Sync HTTP (various deps) |

#### Japanese NLP
| Package | Version | Purpose |
|---------|---------|---------|
| fugashi | 1.5.2 | Japanese morphological analyser |
| pyopenjtalk | 0.4.1 | Japanese TTS G2P |
| jaconv | 0.5.0 | Japanese character conversion |
| mojimoji | 0.0.13 | Full/half-width conversion |
| unidic | 1.1.0 | Japanese dictionary |

#### UI (client only)
| Package | Version | Purpose |
|---------|---------|---------|
| PyQt6 | 6.6.0 | Kiosk UI framework |
| PyQt6-Qt6 | 6.11.0 | Qt6 binaries |

#### Heavy / Unusual Dependencies
| Package | Version | Purpose | Risk |
|---------|---------|---------|------|
| deepspeed | 0.15.1 | Distributed training (CosyVoice dep) | High — complex C++ build |
| modelscope | 1.20.0 | ModelScope hub (CosyVoice dep) | Medium — large transitive deps |
| spacy | 3.8.14 | NLP pipeline | Medium — large |
| en_core_web_sm | 3.8.0 | spaCy English model | — |
| gradio | 5.50.0 | Web UI (CosyVoice/KokoClone dep) | Medium — large |
| vllm-omni | 0.18.0 | vLLM with audio support | High — GPU-specific build |
| tensorrt_cu12 | 10.13.3.9 | TensorRT inference | High — CUDA version-locked |
| onnxruntime-gpu | 1.18.0 | GPU ONNX inference | Medium |
| pulsar-client | 3.11.0 | Apache Pulsar (chromadb dep) | Low — unused at runtime |

### 3.4 KokoClone Dependencies (Python 3.12 / uv)

| Package | Version | Purpose |
|---------|---------|---------|
| torch | ≥2.10.0 | Deep learning |
| torchaudio | ≥2.10.0 | Audio processing |
| kokoro-onnx[gpu] | ≥0.5.0 | ONNX TTS engine |
| misaki[en,ja,zh] | ≥0.9.4 | G2P for EN/JA/ZH |
| kanade-tokenizer | git HEAD | Voice conversion tokenizer (git dep) |
| soundfile | ≥0.13.1 | WAV I/O |
| huggingface-hub | ≥1.5.0 | Model downloads |
| gradio | ≥6.8.0 | Web UI |
| ninja | ≥1.13.0 | C++ build tool |

### 3.5 System-Level (APT) Dependencies

Key system packages installed (from `env_snapshots/apt_packages.txt`):

| Category | Packages |
|----------|---------|
| **CUDA toolkit** | cuda-toolkit-13-2, cuda-toolkit-12-1-config-common, cuda-nvcc-13-2, cuda-libraries-12-1, cuda-libraries-13-2 |
| **cuDNN / cuBLAS** | libcublas-12-1, libcublas-13-2, libcufft-12-1, libcufft-13-2, libcurand-12-1, libcusolver-12-1, libcusparse-12-1 |
| **Audio** | ffmpeg, libportaudio2, libportaudiocpp0, libasound2-dev, libpulse-dev, libsndfile1, libjack-jackd2-0 |
| **Build tools** | build-essential, gcc-13, g++-13, cmake, ninja-build, libssl-dev, libffi-dev |
| **Python** | libpython3.11, libpython3.11-dev, libpython3.12-dev |
| **Qt6** | libqt6core6t64, libqt6gui6t64, libqt6widgets6t64, libqt6opengl6t64 |
| **Java** | default-jre (required by some modelscope deps) |
| **Fonts** | fonts-noto-cjk (Japanese/Chinese/Korean rendering) |
| **NVIDIA container** | libnvidia-container-tools, libnvidia-container1 |

### 3.6 Environment Variables (Runtime)

Key variables from `env_snapshots/env_vars.txt`:

| Variable | Value | Purpose |
|----------|-------|---------|
| `VIRTUAL_ENV` | `/home/seinxera12/robotic_robo/venv` | Active Python venv |
| `LD_LIBRARY_PATH` | `/usr/local/cuda-12.1/lib64:` | CUDA 12.1 runtime libs |
| `DISPLAY` | `:0` | X11 display (WSLg) |
| `WAYLAND_DISPLAY` | `wayland-0` | Wayland display (WSLg) |
| `PULSE_SERVER` | `unix:/mnt/wslg/PulseServer` | PulseAudio via WSLg |
| `WSL_DISTRO_NAME` | `Ubuntu` | WSL2 distro |
| `WSL2_GUI_APPS_ENABLED` | `1` | WSLg GUI support |
| `PATH` | includes `/usr/local/cuda-12.1/bin` | CUDA binaries |

### 3.7 Version Conflicts & Fragile Dependencies

| Issue | Description | Severity |
|-------|-------------|---------|
| **Dual CUDA versions** | Both CUDA 12.1 (runtime, used by torch) and CUDA 13.2 (system toolkit) are installed. `LD_LIBRARY_PATH` pins to 12.1. Any package that auto-detects CUDA version may pick 13.2 and fail. | High |
| **nvcc not on PATH** | `nvcc` is installed (`cuda-nvcc-13-2`) but not in the active PATH. Any package that tries to compile CUDA kernels at runtime (deepspeed, triton) will fail unless PATH is set correctly. | High |
| **torch 2.1.2 vs KokoClone torch ≥2.10** | Server venv pins `torch==2.1.2+cu121`. KokoClone requires `torch>=2.10.0`. These cannot coexist in one venv — hence the Python 3.12 split. | High |
| **tokenizers version** | `faster-whisper==0.10.0` requires `tokenizers>=0.13,<0.16` but `transformers==4.41.2` requires `tokenizers>=0.19`. The freeze shows `tokenizers==0.19.1` installed, which technically violates faster-whisper's constraint. | Medium |
| **huggingface-hub version** | `faster-whisper` requires `huggingface-hub>=0.13` but `transformers==4.41.2` requires `huggingface-hub>=0.23.0,<1.0`. Freeze shows `0.24.6` — within transformers range but at the edge of faster-whisper's range. | Low |
| **grpcio-tools vs protobuf** | `grpcio-tools==1.57.0` requires `protobuf>=4.21.6,<5.0dev` but `protobuf==6.33.6` is installed. This is a known breakage point. | Medium |
| **fsspec version** | `lightning==2.2.4` requires `fsspec<2025.0` but `fsspec==2026.3.0` is installed. | Medium |
| **packaging version** | `lightning==2.2.4` requires `packaging<25.0` but `packaging==26.1` is installed. | Low |
| **WSL2 audio** | PortAudio's ALSA backend fails with `PaErrorCode -9987` (RT thread) on WSL2. Workaround: `PULSE_SERVER` + `PA_ALSA_PLUGHW=1` env vars. Fragile — breaks if WSLg is not running. | High |
| **deepspeed C++ build** | deepspeed requires CUDA toolkit + nvcc for JIT compilation of custom ops. With nvcc not on PATH, deepspeed ops will fail to compile on first use. | High |

---

## 4. Repository Structure

### 4.1 Top-Level Layout

```
robotic_robo/                          ← project root
├── server/                            ← GPU inference server (Python 3.11)
├── client/                            ← CPU kiosk client (Python 3.11)
├── kokoclone/                         ← KokoClone TTS microservice (Python 3.12, git submodule)
├── cosyvoice_service/                 ← Legacy CosyVoice2 service (Docker)
│   └── cosyvoice_repo/                ← CosyVoice git submodule
├── building_kb/                       ← Knowledge base markdown documents
│   ├── floors/
│   ├── facilities/
│   └── japanese/
├── chroma_db/                         ← ChromaDB persistent storage (primary)
├── chroma_data/                       ← ChromaDB persistent storage (Docker mount)
├── models/                            ← Model weights directory (currently empty)
├── voices_reference/                  ← Reference WAV files for voice cloning
├── searxng/                           ← SearXNG configuration
├── scripts/                           ← Setup and utility scripts
├── guides/                            ← Architecture and deployment guides
├── logs/                              ← Runtime logs
├── env_snapshots/                     ← Captured environment state
├── tests/                             ← Top-level test suite
├── venv/                              ← Python 3.11 virtual environment
├── .kiro/                             ← Kiro AI assistant specs/notes
├── docker-compose.yml                 ← Main services (Ollama, VOICEVOX, SearXNG, voice-server)
├── docker-compose.cosyvoice.yml       ← CosyVoice2 service (separate compose)
├── Makefile                           ← Docker compose shortcuts
├── .env / .env.example / .env.local   ← Environment configuration
├── .gitmodules                        ← Git submodule definitions
└── all_requirments.txt                ← Full pip freeze snapshot
```

### 4.2 Server Module Structure

```
server/
├── main.py              ← FastAPI app, lifespan (pre-loads all models), WebSocket endpoint
├── pipeline.py          ← VoicePipeline class + PipelineState dataclass (1094 lines)
├── config.py            ← Config dataclass, loads from .env
├── validation.py        ← Input validation helpers
├── stt/
│   ├── whisper_stt.py   ← WhisperSTT wrapper (faster-whisper)
│   └── text_cleaner.py  ← Post-transcription text cleanup
├── llm/
│   ├── fallback_chain.py    ← LLMFallbackChain (vLLM → Ollama → Grok)
│   ├── vllm_backend.py      ← vLLM OpenAI-compat backend
│   ├── ollama_backend.py    ← Ollama OpenAI-compat backend
│   ├── grok_backend.py      ← xAI Grok API backend
│   ├── intent_classifier.py ← Keyword + embedding intent classification
│   ├── prompt_builder.py    ← System prompt templates + message assembly
│   └── base_backend.py      ← Protocol/base class
├── tts/
│   ├── tts_router.py        ← TTSRouter (EN/JA routing + fallback)
│   ├── kokoro_tts.py        ← KokoroTTS (EN) + KokoroJapaneseTTS (JA)
│   ├── kokoclone_tts.py     ← KokoCloneTTS HTTP client
│   └── opus_encoder.py      ← Opus encoding (present but not used in current pipeline)
├── rag/
│   ├── chroma_store.py  ← BuildingKB (ChromaDB CRUD + retrieval)
│   ├── embedder.py      ← Embedder (multilingual-e5-large)
│   └── ingest.py        ← Document ingestion script
├── search/
│   ├── searxng_client.py        ← SearXNG async HTTP client
│   └── query_reformulator.py    ← Search query extraction from conversation
├── lang/
│   └── detector.py      ← Language detection (Whisper confidence + Unicode scan)
└── tools/
    └── tool_definitions.py  ← LLM tool schemas (defined but not actively used)
```

### 4.3 Client Module Structure

```
client/
├── main.py              ← Entry point; --no-ui, --text, or full Qt mode
├── config.py            ← ClientConfig (SERVER_WS_URL, KIOSK_ID, KIOSK_LOCATION)
├── audio_capture.py     ← AudioCapture (sounddevice InputStream, 16kHz PCM16)
├── vad.py               ← SileroVAD wrapper (speech start/end detection)
├── ws_client.py         ← WebSocketClient (websockets library)
├── audio_playback.py    ← AudioPlayback (WAV decode → sounddevice OutputStream)
├── keyboard_input.py    ← Keyboard input handler
├── kiosk.service        ← systemd service unit for kiosk deployment
└── ui/
    └── app.py           ← KioskMainWindow (PyQt6 fullscreen UI)
```

### 4.4 KokoClone Microservice Structure

```
kokoclone/
├── server.py            ← FastAPI service (:5003); /synthesize, /synthesize_stream, /health
├── app.py               ← Gradio demo UI
├── cli.py               ← CLI interface
├── inference.py         ← Direct inference helpers
├── core/
│   ├── cloner.py        ← KokoClone class (Kokoro-ONNX + Kanade VC pipeline)
│   ├── chunked_convert.py ← Chunked voice conversion for streaming
│   └── logging_setup.py
├── model/               ← Model weight files (downloaded on first run)
├── voice/               ← Voice preset files
├── pyproject.toml       ← uv project config (Python ≥3.12)
└── uv.lock              ← Locked dependency tree
```

### 4.5 Git Submodules

| Submodule | Path | Remote URL | Purpose |
|-----------|------|-----------|---------|
| `kokoclone` | `kokoclone/` | `https://github.com/seinxera12/kokoclone.git` | KokoClone TTS microservice |
| `cosyvoice_repo` | `cosyvoice_service/cosyvoice_repo/` | `https://github.com/seinxera12/CosyVoice.git` | CosyVoice2 model code (forked) |

The CosyVoice repo itself contains a nested submodule:
- `cosyvoice_service/cosyvoice_repo/third_party/Matcha-TTS/` — Matcha-TTS dependency

### 4.6 External Cloned Repos / Local Patches

- `cosyvoice_service/cosyvoice_repo/` is a **fork** of the official CosyVoice repo (`seinxera12/CosyVoice`), suggesting local modifications may exist.
- The `cosyvoice_service/` directory contains a custom `app.py` REST wrapper that is not part of the upstream CosyVoice project.
- `kokoclone/` is also a fork (`seinxera12/kokoclone`).

### 4.7 Inter-Service Dependencies

```
voice-server (Python 3.11, :8765)
    ├── depends on: Ollama (:11434)          — LLM inference
    ├── depends on: SearXNG (:8081)          — web search
    ├── depends on: KokoClone service (:5003) — Japanese TTS (optional)
    ├── depends on: ChromaDB (local files)   — RAG vector store
    └── optional: CosyVoice (:5002)          — legacy English TTS (not used)

KokoClone service (Python 3.12, :5003)
    └── standalone — no dependencies on voice-server

Ollama (Docker, :11434)
    └── standalone — pulls models from HuggingFace/Ollama registry

SearXNG (Docker, :8081)
    └── standalone — proxies to external search engines

VOICEVOX (Docker, :50021)
    └── standalone — legacy, not used by current pipeline
```

---

## 5. Runtime & Startup Flow

### 5.1 Full Startup Sequence

The system has **no single start command**. Services must be started in the correct order manually or via separate commands:

```
Step 1 — Start Docker services (Ollama + SearXNG)
    cd /home/seinxera12/robotic_robo
    docker compose up -d ollama searxng

Step 2 — Pull Ollama model (first time only)
    docker compose exec ollama ollama pull qwen2.5:7b-instruct

Step 3 — Start KokoClone microservice (optional, for Japanese voice cloning)
    cd kokoclone
    source .venv/bin/activate
    python server.py
    # Listens on :5003
    # Loads Kanade VC model + pre-warms reference embedding (~30–60s)

Step 4 — Start voice server
    cd /home/seinxera12/robotic_robo
    source venv/bin/activate
    python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
    # OR: python server/main.py

    Server startup sequence (lifespan):
      a. Load WhisperSTT (faster-whisper, ~10–20s, downloads model if needed)
      b. Init LLMFallbackChain (instantiates Ollama/vLLM/Grok clients — fast)
      c. Load BuildingKB (connects ChromaDB, loads multilingual-e5-large, ~15–30s)
      d. Init TTSRouter (loads KokoroTTS lazily — actual model load deferred to first synthesis)
      e. Server ready — accepts WebSocket connections

Step 5 — Start client
    cd /home/seinxera12/robotic_robo
    source venv/bin/activate
    python client/main.py              # Full PyQt6 UI
    python client/main.py --no-ui      # Headless mic mode
    python client/main.py --text       # Text-only mode
```

### 5.2 Service Startup Order Requirements

```
Ollama          ─── must be running before voice-server starts
                    (health check in LLMFallbackChain)

SearXNG         ─── can start after voice-server (search is optional,
                    failures fall back to GENERAL intent)

KokoClone       ─── can start after voice-server (TTS falls back to
                    KokoroJapaneseTTS if :5003 is unreachable)

ChromaDB        ─── embedded in voice-server process (no separate service)
                    chroma_db/ directory must exist and be writable

voice-server    ─── must be running before client connects

client          ─── last to start
```

### 5.3 Port Map

| Port | Service | Protocol | Direction |
|------|---------|---------|-----------|
| **8765** | voice-server WebSocket | WS | Client ↔ Server |
| **8000** | voice-server HTTP health | HTTP | Monitoring → Server |
| **11434** | Ollama | HTTP (OpenAI-compat) | Server → Ollama |
| **8081** | SearXNG | HTTP | Server → SearXNG |
| **5003** | KokoClone microservice | HTTP | Server → KokoClone |
| **5002** | CosyVoice2 (legacy) | HTTP | Server → CosyVoice (unused) |
| **50021** | VOICEVOX (legacy) | HTTP | Server → VOICEVOX (unused) |
| **8001** | vLLM (disabled) | HTTP (OpenAI-compat) | Server → vLLM (commented out) |

### 5.4 WebSocket Message Protocol

**Client → Server:**

| Message | Type | Format | Description |
|---------|------|--------|-------------|
| Audio frame | Binary | PCM16 bytes | Raw speech audio after VAD speech_end |
| Session start | JSON | `{"type":"session_start","kiosk_id":"...","kiosk_location":"..."}` | Connection init |
| Text input | JSON | `{"type":"text_input","text":"...","lang":"auto"}` | Keyboard bypass |
| Interrupt | JSON | `{"type":"interrupt"}` | Barge-in signal |

**Server → Client:**

| Message | Type | Format | Description |
|---------|------|--------|-------------|
| Transcript | JSON | `{"type":"transcript","text":"...","lang":"en/ja","final":true}` | STT result |
| LLM token | JSON | `{"type":"llm_text_chunk","text":"...","final":false/true}` | Streaming LLM output |
| Audio chunk | Binary | WAV bytes (PCM16, 24kHz) | TTS audio |
| Status | JSON | `{"type":"status","state":"listening/thinking/speaking"}` | Pipeline state |
| Session ack | JSON | `{"type":"session_ack"}` | Connection confirmed |

### 5.5 GPU Allocation Strategy

The system runs on a single RTX 4050 Laptop GPU (6 GB VRAM). GPU usage at runtime:

| Component | VRAM Usage | Notes |
|-----------|-----------|-------|
| Whisper Large V3 (int8) | ~2–3 GB | Loaded at server startup, stays resident |
| Ollama Qwen2.5-7B (Q4_K_M) | ~5–6 GB | Loaded by Ollama container |
| Kokoro-82M (CPU mode) | 0 GB | Runs on CPU by default (`KOKORO_DEVICE=cpu`) |
| KokoClone / Kanade VC | ~2–4 GB | Runs in separate process |
| **Total (Whisper + Ollama)** | **~7–9 GB** | **Exceeds 6 GB VRAM — causes OOM** |

**Critical finding:** Whisper + Ollama together exceed the 6 GB VRAM budget. In practice, the system works because:
1. Ollama manages its own VRAM and may offload layers to CPU
2. Whisper uses int8 quantization to reduce footprint
3. KokoClone is run separately and may not be active simultaneously

This is a known fragility — the system is operating at or beyond VRAM capacity.

### 5.6 Barge-in / Interrupt Flow

```
Client: user presses Speak while assistant is talking
    → sends {"type": "interrupt"}

Server: websocket_receiver receives interrupt
    → calls handle_interrupt()
    → sets state.interrupt_event
    → all 5 workers check interrupt_event at top of loop → pause
    → drains audio_input, transcript, token, audio_output queues
    → resets state.status = "listening"
    → clears interrupt_event → workers resume
```

### 5.7 Conversation History Management

- Max 10 turns (20 messages: 10 user + 10 assistant)
- Stored in `PipelineState.conversation_history` (per-connection, in-memory)
- Cleared on WebSocket disconnect
- Language tag stored per message (`{"role":"user","content":"...","lang":"en"}`)
- Boilerplate patterns stripped from assistant responses before saving to history
- Prompt builder trims history to fit 3000-token budget (oldest turns dropped first)

---

## 6. Storage Analysis

### 6.1 Estimated Size by Category

> Note: Exact sizes require `du` commands on the live system. The estimates below are based on known model sizes, package counts, and directory inspection.

| Category | Path(s) | Estimated Size | Notes |
|----------|---------|---------------|-------|
| **Python venv (server)** | `venv/` | ~8–12 GB | Includes torch+CUDA, deepspeed, spacy, gradio, all ML deps |
| **KokoClone venv** | `kokoclone/.venv/` | ~4–6 GB | Separate torch 2.10+, kokoro-onnx, kanade |
| **CosyVoice repo** | `cosyvoice_service/cosyvoice_repo/` | ~500 MB–1 GB | Source code + Matcha-TTS submodule |
| **HuggingFace model cache** | `~/.cache/huggingface/` | ~5–15 GB | Whisper, multilingual-e5-large, Kokoro-82M, tokenizers |
| **Ollama model storage** | `models/ollama/` or `~/.ollama/` | ~4–5 GB | Qwen2.5-7B GGUF Q4_K_M |
| **ChromaDB data** | `chroma_db/`, `chroma_data/` | ~10–50 MB | Vector embeddings for building KB |
| **Source code** | `server/`, `client/`, `kokoclone/`, `cosyvoice_service/` | ~5–10 MB | Python source files |
| **Building KB docs** | `building_kb/` | <1 MB | Markdown documents |
| **Voice reference files** | `voices_reference/` | ~5–20 MB | 4 WAV files |
| **Logs / cache** | `logs/`, `.pytest_cache/`, `__pycache__/` | ~10–50 MB | Runtime artifacts |
| **Docker images** | (Docker daemon storage) | ~5–10 GB | Ollama, SearXNG, VOICEVOX images |
| **CUDA system toolkit** | `/usr/local/cuda-13.2/`, `/usr/local/cuda-12.1/` | ~8–15 GB | System-level CUDA installations |
| **TOTAL (estimated)** | | **~35–65 GB** | Wide range due to HF cache uncertainty |

### 6.2 Largest Individual Components

| Component | Est. Size | Location | Removable? |
|-----------|----------|---------|-----------|
| Python venv (server) | ~8–12 GB | `venv/` | Replaceable (rebuild from requirements) |
| CUDA system toolkit | ~8–15 GB | `/usr/local/cuda-*` | No (system dependency) |
| HuggingFace cache | ~5–15 GB | `~/.cache/huggingface/` | Partially (re-downloadable) |
| Docker images | ~5–10 GB | Docker daemon | Replaceable (re-pullable) |
| KokoClone venv | ~4–6 GB | `kokoclone/.venv/` | Replaceable (rebuild with uv) |
| Ollama models | ~4–5 GB | `~/.ollama/` or `models/ollama/` | Re-downloadable |
| CosyVoice repo | ~500 MB–1 GB | `cosyvoice_service/cosyvoice_repo/` | Optional (legacy service) |

### 6.3 Storage Classification

**Essential (cannot be removed without breaking the system):**
- `venv/` — server Python environment
- `~/.cache/huggingface/hub/` — Whisper, multilingual-e5-large, Kokoro-82M weights
- `server/`, `client/` — source code
- `chroma_db/` — RAG vector store (if USE_RAG=true)
- `.env` — configuration

**Optional (system degrades gracefully without these):**
- `cosyvoice_service/` — legacy TTS, not used
- `chroma_data/` — duplicate ChromaDB mount (Docker path, not used in non-Docker mode)
- `models/` — currently empty directory
- `voices_reference/` — only needed if KokoClone is enabled
- `building_kb/` — only needed for RAG ingestion (already ingested into chroma_db)

**Replaceable / Re-downloadable:**
- All HuggingFace model weights (re-download from HF Hub)
- Ollama models (re-pull via `ollama pull`)
- Docker images (re-pull)
- Python venv (rebuild from requirements files)
- KokoClone venv (rebuild with `uv sync`)

**Generated / Temporary:**
- `__pycache__/` directories — auto-regenerated
- `logs/` — runtime logs
- `.pytest_cache/`, `.hypothesis/` — test artifacts
- `chroma_db/` SQLite + HNSW index — regenerated by running `scripts/ingest_kb.sh`

---

## 7. Resource Requirements

### 7.1 Server Requirements

| Resource | Minimum | Recommended | Current Hardware |
|----------|---------|-------------|-----------------|
| **GPU** | NVIDIA 8 GB VRAM | NVIDIA 16–24 GB VRAM | RTX 4050 Laptop 6 GB ⚠️ |
| **GPU CUDA** | CUDA 11.8+ | CUDA 12.1+ | CUDA 12.1 (runtime) |
| **CPU** | 4 cores | 8+ cores | Intel (Lenovo LOQ) |
| **RAM** | 16 GB | 32 GB | Unknown (not captured) |
| **Disk** | 50 GB | 100 GB | Unknown |
| **OS** | Ubuntu 22.04+ | Ubuntu 24.04 | Ubuntu 24.04 WSL2 |
| **Docker** | Required | Required | Installed |
| **NVIDIA Container Toolkit** | Required | Required | Installed |

> ⚠️ The current RTX 4050 Laptop (6 GB) is **below the recommended minimum** for running Whisper Large V3 + Ollama Qwen2.5-7B simultaneously. The system works but operates at VRAM capacity, risking OOM errors under load.

### 7.2 Client Requirements

| Resource | Minimum | Notes |
|----------|---------|-------|
| **CPU** | Any x86_64 | No GPU needed on client |
| **RAM** | 4 GB | SileroVAD + PyQt6 |
| **Audio** | Microphone + speakers | sounddevice / PortAudio |
| **Display** | 1920×1080 | For PyQt6 kiosk UI (optional with --no-ui) |
| **OS** | Ubuntu 22.04+ | systemd service deployment |
| **Network** | LAN to server | WebSocket connection to :8765 |
| **Python** | 3.11 | Same venv as server (or separate install) |

### 7.3 OS & Platform Assumptions

The project is **tightly coupled to WSL2 on Windows** in its current development state:

- `LD_LIBRARY_PATH` hardcoded to `/usr/local/cuda-12.1/lib64`
- Audio workarounds for WSL2 (`PULSE_SERVER=unix:/mnt/wslg/PulseServer`, `PA_ALSA_PLUGHW=1`)
- `AudioCapture` has explicit WSLg detection code (`/mnt/wslg/PulseServer`)
- `DISPLAY=:0` and `WAYLAND_DISPLAY=wayland-0` set by WSLg
- `kiosk.service` systemd unit assumes Ubuntu deployment

For production kiosk deployment, the README targets **Ubuntu 22.04 bare metal** (not WSL2). The WSL2 audio workarounds would not be needed on bare metal but the CUDA/Python setup would be similar.

### 7.4 Network Requirements

| Connection | Required | Notes |
|-----------|---------|-------|
| LAN (client ↔ server) | Yes | WebSocket :8765 |
| Internet (Ollama model pull) | First-time only | ~4.7 GB download |
| Internet (HF model download) | First-time only | ~2.5 GB total |
| Internet (SearXNG search) | For search intent | Proxied through SearXNG |
| Internet (Grok API) | Optional | Cloud LLM fallback |
| Internet (Docker image pull) | First-time only | ~2–3 GB |

---

## 8. Pain Point Analysis

### 8.1 Deployment Bottlenecks

| Bottleneck | Time Cost | Description |
|-----------|----------|-------------|
| **Python venv setup** | 30–90 min | `pip install` of 200+ packages including torch+CUDA, deepspeed, spacy. Frequent network timeouts and build failures. |
| **CUDA toolkit installation** | 30–60 min | Requires matching CUDA version to torch build. Two CUDA versions (12.1 + 13.2) currently coexist, creating confusion. |
| **Model downloads** | 30–120 min | Whisper (~1.6 GB), multilingual-e5-large (~560 MB), Kokoro-82M (~330 MB), Ollama Qwen2.5-7B (~4.7 GB). Total ~7+ GB on first run. |
| **KokoClone venv setup** | 15–30 min | Separate Python 3.12 + uv environment. `kanade-tokenizer` is a git dependency that must be cloned and built. |
| **Docker image pulls** | 15–30 min | Ollama, SearXNG, VOICEVOX images. |
| **CosyVoice submodule** | 10–20 min | Nested git submodule with its own Matcha-TTS submodule. `git submodule update --init --recursive` required. |
| **Total first-time setup** | **2–5 hours** | Under ideal conditions. Realistically 1–2 days with troubleshooting. |

### 8.2 Dependency Conflicts

| Conflict | Impact | Workaround in place |
|---------|--------|-------------------|
| **torch version split** | KokoClone needs torch ≥2.10, server needs torch 2.1.2 | Separate Python 3.12 venv for KokoClone |
| **Dual CUDA versions** | Packages may pick wrong CUDA version | `LD_LIBRARY_PATH` pins to 12.1 |
| **nvcc not on PATH** | deepspeed JIT compilation fails | deepspeed not actively used; workaround: add `/usr/local/cuda-13.2/bin` to PATH |
| **grpcio-tools vs protobuf** | grpcio-tools 1.57 requires protobuf <5, but 6.33 installed | Not actively used at runtime; silent breakage |
| **fsspec version** | lightning requires <2025.0, installed 2026.3.0 | lightning not used at runtime |
| **tokenizers version** | faster-whisper requires <0.16, installed 0.19.1 | Works in practice but technically unsupported |

### 8.3 Setup Fragility

| Fragile Point | Description | Failure Mode |
|--------------|-------------|-------------|
| **WSL2 audio** | PulseAudio via WSLg socket. Breaks if WSLg not running, Windows audio service stopped, or on bare Linux. | `sounddevice` raises `PaErrorCode -9987`; client cannot capture audio |
| **CUDA path** | `LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64` hardcoded in env. If CUDA 12.1 not installed at that path, torch CUDA fails. | `torch.cuda.is_available()` returns False; Whisper falls back to CPU (10× slower) |
| **HuggingFace cache** | Models downloaded to `~/.cache/huggingface/`. If cache is on a different machine or cleared, all models re-download on startup. | Server startup takes 30–120 min on first run |
| **ChromaDB path** | `CHROMADB_PATH=/chroma` in Docker env, `./chroma_db` in local env. Mismatch causes empty KB. | RAG returns no results; system falls back to GENERAL intent |
| **KokoClone ref audio** | `KOKOCLONE_REF_AUDIO` must point to an existing WAV file. If path is wrong, KokoCloneTTS silently disables itself. | Japanese TTS falls back to KokoroJapaneseTTS (different voice) |
| **Ollama model name** | `OLLAMA_MODEL_NAME=qwen2.5:7b-instruct` must exactly match the pulled model name. | LLM health check fails; falls back to Grok API (or fails entirely if no API key) |
| **Port conflicts** | Multiple services on fixed ports. If any port is in use, service fails to start. | Silent failure or crash at startup |
| **Git submodule state** | `cosyvoice_repo` and `kokoclone` are submodules. If not initialised, directories are empty. | CosyVoice service fails to import; KokoClone service fails entirely |

### 8.4 Long Installation Steps

Ranked by pain level:

1. **CUDA + cuDNN setup** — Version matching between driver, toolkit, torch, and ctranslate2 is the single most common failure point. The current system has CUDA 12.1 (runtime) and 13.2 (toolkit) coexisting, which is unusual and confusing.

2. **deepspeed installation** — Requires C++ compiler, CUDA toolkit, and ninja. Often fails with cryptic build errors. Currently installed but not actively used by the main pipeline.

3. **pyopenjtalk installation** — Requires CMake and C++ build tools. Frequently fails on fresh Ubuntu installs without `build-essential`.

4. **KokoClone kanade-tokenizer** — Git dependency that must be cloned from GitHub. Requires network access to GitHub and a working C++ build environment.

5. **CosyVoice submodule** — Nested submodule (`cosyvoice_repo` → `Matcha-TTS`) requires `git submodule update --init --recursive`. Easy to forget.

6. **Ollama model pull** — 4.7 GB download. No progress indication in docker-compose logs. Easy to think it's stuck.

### 8.5 Areas Tightly Coupled to Host Machine

| Coupling | Description | Portability Risk |
|---------|-------------|-----------------|
| **CUDA 12.1 path** | `LD_LIBRARY_PATH` hardcoded to `/usr/local/cuda-12.1/lib64` | High — breaks on machines with different CUDA install path |
| **WSLg audio socket** | `PULSE_SERVER=unix:/mnt/wslg/PulseServer` | High — WSL2-specific, breaks on bare Linux or different WSL2 setup |
| **HuggingFace cache** | `~/.cache/huggingface/` — user home directory | Medium — different user = re-download |
| **KokoClone ref audio path** | `KOKOCLONE_REF_AUDIO=/home/seinxera12/robotic_robo/voices_reference/reference_ja.wav` | High — absolute path hardcoded to specific user |
| **Python version** | Server requires Python 3.11 specifically (3.12 breaks some deps; 3.10 too old) | Medium |
| **GPU model** | RTX 4050 Laptop — system tuned for 6 GB VRAM (int8 Whisper, CPU Kokoro) | Medium — different GPU may need config changes |
| **Ollama on Windows host** | PATH includes `C:\Users\Administrator\AppData\Local\Programs\Ollama` — Ollama also installed on Windows side | Medium — dual Ollama installations can cause confusion |

### 8.6 What Would Break Easily on Another PC

1. Any machine without CUDA 12.1 at `/usr/local/cuda-12.1/` — torch CUDA fails
2. Any machine without WSLg — audio capture fails
3. Any machine with different username — KokoClone ref audio path fails
4. Any machine with <8 GB VRAM — Whisper + Ollama OOM
5. Any machine without `build-essential` + `cmake` — deepspeed, pyopenjtalk fail to install
6. Any machine with Python 3.10 or 3.13 — various dependency incompatibilities
7. Any machine without Docker + NVIDIA Container Toolkit — Ollama container fails
8. Any machine without `fonts-noto-cjk` — Japanese text rendering broken in UI

---

## 9. Demo Feasibility Notes

> **Important:** This section is analysis only. No implementation changes are recommended here. These notes are intended to inform future lightweight demo planning.

### 9.1 Components Absolutely Required for a Lightweight Demo

A minimal voice-to-voice demo requires these functional blocks regardless of implementation:

| Block | Function | Cannot be removed |
|-------|---------|------------------|
| Audio capture | Microphone input | Yes |
| VAD | Speech detection | Yes (or push-to-talk button) |
| STT | Speech → text | Yes |
| LLM | Text → response | Yes |
| TTS | Response → audio | Yes |
| Audio playback | Speaker output | Yes |
| Transport | Client ↔ server | Yes (or single-process) |

### 9.2 Components That Can Be Replaced with APIs

| Current Component | API Replacement | Trade-off |
|------------------|----------------|-----------|
| **Whisper Large V3** (local, ~2 GB VRAM) | Groq Whisper API (`whisper-large-v3-turbo`) | Latency: ~200–400ms; requires internet; data leaves device |
| **Ollama Qwen2.5-7B** (local, ~5 GB VRAM) | Groq LLaMA-3.1-8B or Gemini Flash | Latency: ~100–300ms TTFT; requires internet; free tier available |
| **KokoClone / Kanade VC** (complex, GPU) | Groq PlayAI TTS or ElevenLabs | Loses voice cloning; simpler setup |
| **SearXNG** (self-hosted Docker) | Tavily API or SerpAPI | Simpler; requires API key |
| **ChromaDB RAG** (optional) | Remove entirely or use in-memory | Loses building KB; acceptable for generic demo |

**Groq API** is the strongest candidate for a lightweight demo:
- Free tier: 14,400 requests/day for Whisper, generous LLM limits
- Latency: Whisper ~200ms, LLaMA-3.1-8B TTFT ~100ms
- Single API key, no local GPU needed
- Python SDK: `groq` package (~50 KB)

**Gemini Flash** alternative:
- Multimodal (audio input natively in Gemini 2.0 Flash)
- Could replace STT + LLM in a single API call
- Free tier available

### 9.3 Local Models That Could Be Swapped for Smaller Alternatives

| Current Model | Size | Lighter Alternative | Size | Quality Trade-off |
|--------------|------|-------------------|------|------------------|
| Whisper Large V3 | ~1.6 GB | Whisper Turbo (via Groq) or `faster-whisper` `small` | ~244 MB | Slightly lower accuracy on accented speech |
| Qwen2.5-7B (Ollama) | ~4.7 GB | Qwen2.5-3B or Phi-3.5-mini via Ollama | ~2 GB | Lower reasoning quality |
| multilingual-e5-large | ~560 MB | `paraphrase-multilingual-MiniLM-L12-v2` | ~120 MB | Lower embedding quality |
| Kokoro-82M | ~330 MB | Already lightweight — keep as-is | — | — |
| Silero VAD | ~2 MB | Already minimal — keep as-is | — | — |

### 9.4 Services That Can Be Containerised

| Service | Containerisable | Notes |
|---------|----------------|-------|
| voice-server | Yes | Already has Dockerfile in `server/` (referenced in docker-compose.yml) |
| KokoClone microservice | Yes | Needs GPU passthrough; Python 3.12 base image |
| Ollama | Already containerised | `ollama/ollama:latest` |
| SearXNG | Already containerised | `searxng/searxng:latest` |
| CosyVoice2 | Already containerised | `docker-compose.cosyvoice.yml` |
| VOICEVOX | Already containerised | `voicevox/voicevox_engine:latest` |
| Client | Partially | Audio I/O requires host device passthrough; UI requires display |

For a demo, the entire server stack (voice-server + Ollama + SearXNG) could run in a single `docker-compose up` with GPU passthrough, eliminating the Python venv setup entirely.

### 9.5 Dependencies That Should Be Isolated

These dependencies cause the most setup pain and should be isolated in a demo:

| Dependency | Pain Level | Isolation Strategy |
|-----------|-----------|-------------------|
| **deepspeed** | Very High | Remove entirely — not used by main pipeline; only pulled in as CosyVoice dep |
| **CosyVoice / cosyvoice_repo** | Very High | Remove entirely — replaced by Kokoro |
| **VOICEVOX** | Medium | Remove Docker service — replaced by Kokoro JP |
| **vLLM** | High | Keep commented out; use Ollama only |
| **spacy + en_core_web_sm** | Medium | Remove if not needed for intent classification |
| **modelscope** | Medium | Remove — CosyVoice dep, not needed |
| **pyopenjtalk** | Medium | Keep only if Japanese TTS needed; requires C++ build |
| **KokoClone / Kanade VC** | High | Replace with KokoroJapaneseTTS for demo (no voice cloning) |
| **PyQt6** | Medium | Use `--no-ui` or `--text` mode for demo; avoids Qt6 install |
| **tensorrt** | High | Remove — not used by current pipeline |

### 9.6 Recommended Lightweight Demo Architecture

```
┌─────────────────────────────────────────────────────────┐
│  DEMO STACK (estimated setup time: 15–30 minutes)        │
│                                                         │
│  Client (any OS, Python 3.11):                          │
│    sounddevice + silero-vad + websockets                │
│    (no PyQt6, no CUDA, no GPU)                          │
│                                                         │
│  Server (any machine with Python 3.11):                 │
│    FastAPI + uvicorn                                    │
│    STT:  Groq Whisper API  (no local model)             │
│    LLM:  Groq LLaMA-3.1-8B (no local model)            │
│    TTS:  Kokoro-82M (CPU, ~330 MB, pip install kokoro)  │
│    Search: Tavily API or remove                         │
│    RAG:  disabled (USE_RAG=false)                       │
│                                                         │
│  No Docker required                                     │
│  No CUDA required                                       │
│  No GPU required                                        │
│  Total pip install: ~500 MB                             │
│  API keys needed: GROQ_API_KEY                          │
└─────────────────────────────────────────────────────────┘
```

This demo stack reuses the existing pipeline architecture (same asyncio queue design, same WebSocket protocol, same sentence-boundary TTS streaming) but replaces the heavy local models with API calls. The code changes would be:
- New `GroqSTTBackend` replacing `WhisperSTT`
- New `GroqLLMBackend` replacing `OllamaBackend` as primary
- `KokoroTTS` kept as-is (already lightweight)
- `USE_RAG=false` in `.env`
- `KOKOCLONE_ENABLED=false` in `.env`

### 9.7 What Cannot Be Simplified for a Demo

| Component | Why It Must Stay |
|-----------|----------------|
| **asyncio pipeline architecture** | Core design; removing it would require a full rewrite |
| **WebSocket transport** | Required for real-time streaming audio |
| **Sentence-boundary TTS streaming** | Required for low-latency first audio |
| **VAD (Silero)** | Required for automatic speech detection; already minimal |
| **Language detection** | Required for bilingual support |
| **Conversation history** | Required for coherent multi-turn dialogue |

---

---

## Appendix A: Latency Budget

| Stage | Measured / Estimated | Notes |
|-------|---------------------|-------|
| VAD silence threshold | 800 ms | By design — waits for end of speech |
| Whisper transcription (GPU, int8) | 100–500 ms | Depends on audio length |
| Intent classification (keyword) | <1 ms | Synchronous, no model call |
| Intent classification (embedding) | ~30 ms | Only if keyword confidence <0.7 |
| RAG retrieval (embed + ChromaDB) | ~35 ms | CPU embedding + local DB query |
| SearXNG web search | 500 ms–3 s | Network-dependent |
| LLM first token (Ollama, 7B Q4) | 300–800 ms | GPU-dependent |
| TTS first sentence (Kokoro, CPU) | 200–500 ms | CPU inference |
| Audio playback start | ~50 ms | sounddevice buffer |
| **Total TTFA (best case)** | **~1.5 s** | Keyword intent + short audio + fast LLM |
| **Total TTFA (typical)** | **~2–4 s** | Embedding intent + RAG + normal LLM |
| **Total TTFA (search intent)** | **~4–8 s** | SearXNG round-trip dominates |

---

## Appendix B: Key Configuration Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `STT_MODEL` | `large-v3` | Whisper model size |
| `STT_COMPUTE_TYPE` | `float16` | `int8` for <12 GB VRAM |
| `STT_DEVICE` | `cuda` | `cpu` for no-GPU |
| `VLLM_MODEL_NAME` | `Qwen/Qwen2.5-7B-Instruct-AWQ` | Set to `disabled` to skip vLLM |
| `OLLAMA_MODEL_NAME` | `qwen2.5:7b-instruct` | Must match pulled model name exactly |
| `GROK_API_KEY` | (empty) | Enables Grok cloud fallback |
| `USE_RAG` | `true` | Set `false` to skip ChromaDB entirely |
| `KOKORO_DEVICE` | `cpu` | `cuda` for GPU TTS |
| `KOKOCLONE_ENABLED` | `true` | Set `false` to skip voice cloning |
| `KOKOCLONE_REF_AUDIO` | (empty) | Absolute path to reference WAV |
| `KOKOCLONE_URL` | `http://localhost:5003` | KokoClone service URL |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG service URL |
| `SERVER_WS_URL` | `ws://localhost:8765/ws` | Client WebSocket URL |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose pipeline logging |

---

## Appendix C: Files That Must Not Be Modified During Audit

The following files contain the live environment state and should not be changed:

- `env_snapshots/` — captured system state
- `venv/` — active Python environment
- `kokoclone/.venv/` — KokoClone Python environment
- `chroma_db/` — live vector store
- `.env` — active configuration
- `all_requirments.txt` — pip freeze snapshot

---

## Appendix D: Storage Size Commands (Run to Get Exact Numbers)

When ready to measure exact disk usage, run these commands on the live system:

```bash
# Total project directory
du -sh /home/seinxera12/robotic_robo/

# By subdirectory
du -sh /home/seinxera12/robotic_robo/venv/
du -sh /home/seinxera12/robotic_robo/kokoclone/.venv/
du -sh /home/seinxera12/robotic_robo/cosyvoice_service/
du -sh /home/seinxera12/robotic_robo/chroma_db/
du -sh /home/seinxera12/robotic_robo/models/

# HuggingFace cache
du -sh ~/.cache/huggingface/

# Ollama models
du -sh ~/.ollama/models/

# Docker images
docker system df

# CUDA toolkit
du -sh /usr/local/cuda-12.1/
du -sh /usr/local/cuda-13.2/ 2>/dev/null || echo "not found"
```

---

*End of Technical Audit — Voice Kiosk Chatbot*  
*Generated: May 10, 2026*
