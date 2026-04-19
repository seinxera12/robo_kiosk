# Getting Started - Voice Kiosk Chatbot

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Running the System](#running-the-system)
7. [Testing the System](#testing-the-system)
8. [Troubleshooting](#troubleshooting)
9. [Development Mode](#development-mode)

---

## System Overview

The Voice Kiosk Chatbot is a **bilingual (English + Japanese)** real-time streaming voice assistant designed for kiosk deployment. It achieves **sub-600ms Time-to-First-Audio** through aggressive pipeline parallelization.

### Key Features
- 🎤 **Voice Input**: Automatic speech detection with Silero VAD
- 🗣️ **Speech-to-Text**: Whisper Large V3 Turbo (English + Japanese)
- 🧠 **LLM Processing**: Three-tier fallback (vLLM → Ollama → Grok API)
- 📚 **RAG**: Building knowledge base with ChromaDB
- 🔊 **Text-to-Speech**: VOICEVOX (Japanese), CosyVoice2 (English)
- ⌨️ **Text Input**: Keyboard/on-screen keyboard support
- 🔄 **Barge-in**: Interrupt system during speech
- 🌐 **Web Search**: SearXNG integration for current information

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     KIOSK CLIENT (CPU)                      │
│  ┌──────────┐  ┌─────┐  ┌──────────┐  ┌──────────┐        │
│  │  Audio   │→ │ VAD │→ │WebSocket │→ │ Playback │        │
│  │ Capture  │  └─────┘  │  Client  │  │          │        │
│  └──────────┘            └──────────┘  └──────────┘        │
│  ┌──────────────────────────────────────────────────┐      │
│  │            PyQt6 Fullscreen UI                    │      │
│  │  • Conversation Display                           │      │
│  │  • Status Indicator (🟢🟡🔵)                      │      │
│  │  • Keyboard Input                                 │      │
│  └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            ↕ WebSocket (ws://server:8765/ws)
┌─────────────────────────────────────────────────────────────┐
│                   GPU INFERENCE SERVER                       │
│  ┌──────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐     │
│  │ Whisper  │→ │Language │→ │   RAG   │→ │   LLM    │→    │
│  │   STT    │  │Detector │  │ChromaDB │  │ Fallback │     │
│  └──────────┘  └─────────┘  └─────────┘  └──────────┘     │
│                                                ↓             │
│  ┌──────────┐  ┌─────────────────────────────┘             │
│  │   TTS    │← │                                            │
│  │  Router  │  │  ┌──────────┐  ┌────────┐  ┌──────┐     │
│  └──────────┘  └→ │  vLLM    │→ │ Ollama │→ │ Grok │     │
│       ↓           │ (Primary)│  │(Backup)│  │(Cloud)│     │
│  ┌──────────┐    └──────────┘  └────────┘  └──────┘     │
│  │VOICEVOX/ │                                              │
│  │CosyVoice │                                              │
│  └──────────┘                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

**Voice Turn Pipeline:**
```
1. User speaks → Silero VAD detects speech_end
2. Audio (PCM16) → WebSocket → Server
3. Whisper STT → Transcript + Language
4. RAG retrieval (parallel) → Top-3 context chunks
5. LLM (vLLM/Ollama/Grok) → Token stream
6. TTS (sentence-by-sentence) → Audio chunks (Opus)
7. WebSocket → Client → Audio playback
```

**Barge-in Flow:**
```
1. User speaks during playback → VAD detects
2. Client sends interrupt → Server drains queues
3. Pipeline resets → Ready for new input
```

---

## Prerequisites

### Hardware Requirements

**Server (GPU):**
- NVIDIA GPU with **12-16GB VRAM** (RTX 3090, RTX 4090, A5000, etc.)
- 32GB+ RAM recommended
- 100GB+ free disk space (for models)
- Ubuntu 22.04 or similar Linux distribution

**Client (Kiosk):**
- Any modern CPU (Intel i5+ or AMD Ryzen 5+)
- 8GB+ RAM
- Microphone and speakers
- Ubuntu 22.04 (for systemd service)
- Display for PyQt6 UI

### Software Requirements

**Server:**
- Docker Engine 20.10+
- Docker Compose V2
- NVIDIA Container Toolkit
- Python 3.11+ (for local development)

**Client:**
- Python 3.11+
- PyQt6
- sounddevice (audio I/O)
- ALSA or PulseAudio

---

## Installation

### Step 1: Install NVIDIA Container Toolkit (Server)

```bash
# Add NVIDIA package repositories
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install nvidia-container-toolkit
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Restart Docker daemon
sudo systemctl restart docker

# Test GPU access
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### Step 2: Clone Repository

```bash
git clone <repository-url>
cd voice-kiosk-chatbot
```

### Step 3: Install Python Dependencies

**Server:**
```bash
cd server
pip install -r requirements.txt
cd ..
```

**Client:**
```bash
cd client
pip install -r requirements.txt
cd ..
```

### Step 4: Set Up Directory Structure

```bash
# Create required directories
chmod +x scripts/setup_docker_dirs.sh
./scripts/setup_docker_dirs.sh
```

This creates:
- `models/` - AI model weights storage
- `building_kb/` - Building knowledge base documents
- `chroma_data/` - ChromaDB persistent storage
- `searxng/` - SearXNG configuration

### Step 5: Download AI Models

**Option A: Automatic (if URLs are configured)**
```bash
chmod +x scripts/download_models.sh
./scripts/download_models.sh
```

**Option B: Manual Download**

Download these models to the `models/` directory:

1. **Whisper Large V3 Turbo** (~1.5GB)
   ```bash
   # Will be auto-downloaded by faster-whisper on first run
   ```

2. **Multilingual E5 Large** (~2GB)
   ```bash
   # Will be auto-downloaded by sentence-transformers on first run
   ```

3. **Qwen2.5-7B-Instruct-AWQ** (~4GB) for vLLM
   ```bash
   # Download from HuggingFace
   huggingface-cli download Qwen/Qwen2.5-7B-Instruct-AWQ --local-dir models/Qwen2.5-7B-Instruct-AWQ
   ```

4. **CosyVoice2-0.5B** (Optional, ~500MB)
   ```bash
   # Requires CosyVoice library installation
   # See: https://github.com/FunAudioLLM/CosyVoice
   ```

---

## Configuration

### Environment Variables

Copy the example environment file and customize:

```bash
cp .env.example .env
nano .env
```

### Required Configuration

**Server Configuration:**
```bash
# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8765

# vLLM (Primary LLM)
VLLM_BASE_URL=http://localhost:8001/v1
VLLM_MODEL_NAME=Qwen/Qwen2.5-7B-Instruct-AWQ

# Ollama (Secondary LLM)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL_NAME=qwen2.5:7b-instruct

# Grok API (Tertiary LLM - Optional)
GROK_API_KEY=your-grok-api-key-here  # Leave empty to disable

# Speech-to-Text
STT_MODEL=large-v3-turbo
STT_COMPUTE_TYPE=float16  # Use int8 for GPUs with <12GB VRAM

# Text-to-Speech
TTS_EN_ENGINE=cosyvoice2
TTS_JP_URL=http://localhost:50021

# RAG
CHROMADB_PATH=/chroma
BUILDING_NAME=Office Building

# SearXNG
SEARXNG_URL=http://localhost:8080
SEARXNG_SECRET=changeme-in-production
```

**Client Configuration:**
```bash
# WebSocket URL
SERVER_WS_URL=ws://localhost:8765/ws

# Kiosk Identification
KIOSK_ID=kiosk-01
KIOSK_LOCATION=Floor 1 Lobby
```

### Optional: HuggingFace Token

If downloading models from HuggingFace:
```bash
HUGGING_FACE_HUB_TOKEN=your-hf-token-here
```

---

## Running the System

### Quick Start (Recommended)

**1. Start All Server Services:**
```bash
# Start Docker Compose stack
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f
```

**2. Wait for Services to Initialize (2-3 minutes)**

Monitor logs until you see:
- ✅ vLLM: "Application startup complete"
- ✅ voice-server: "VoicePipeline initialized"
- ✅ VOICEVOX: Health check passing
- ✅ Ollama: Service started

**3. Ingest Knowledge Base:**
```bash
chmod +x scripts/ingest_kb.sh
./scripts/ingest_kb.sh
```

**4. Run Client Application:**
```bash
python3 client/main.py
```

### Step-by-Step Service Startup

If you prefer to start services individually:

**1. Start vLLM (Primary LLM):**
```bash
docker-compose up -d vllm

# Wait for model loading (1-2 minutes)
docker-compose logs -f vllm
```

**2. Start Ollama (Secondary LLM):**
```bash
docker-compose up -d ollama

# Pull the model
docker-compose exec ollama ollama pull qwen2.5:7b-instruct
```

**3. Start VOICEVOX (Japanese TTS):**
```bash
docker-compose up -d voicevox

# Test health
curl http://localhost:50021/version
```

**4. Start SearXNG (Web Search):**
```bash
docker-compose up -d searxng

# Test search
curl http://localhost:8080/
```

**5. Start Voice Server:**
```bash
docker-compose up -d voice-server

# Check health
curl http://localhost:8000/health
```

---

## Testing the System

### 1. Health Check

**Check All Services:**
```bash
make health
```

Or manually:
```bash
# Voice Server
curl http://localhost:8000/health

# vLLM
curl http://localhost:8001/health

# VOICEVOX
curl http://localhost:50021/version

# SearXNG
curl http://localhost:8080/
```

### 2. Test WebSocket Connection

```bash
# Install wscat
npm install -g wscat

# Connect to WebSocket
wscat -c ws://localhost:8765/ws

# Send session start
{"type": "session_start", "kiosk_id": "test-01", "kiosk_location": "Test Location"}

# Send text input
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "auto"}
```

### 3. Test Voice Input

**Run the client and speak:**
```bash
python3 client/main.py
```

**Test scenarios:**
1. **English voice input**: "Where is the cafeteria?"
2. **Japanese voice input**: "カフェテリアはどこですか？"
3. **Barge-in**: Speak while system is responding
4. **Text input**: Type a question and press Enter
5. **Web search**: Ask "What's the weather today?"

### 4. Monitor Logs

**Server logs:**
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f voice-server
docker-compose logs -f vllm
```

**Client logs:**
```bash
# Client outputs to console
python3 client/main.py
```

---

## Service Interfaces

### 1. Voice Server (FastAPI)

**WebSocket Endpoint:**
- URL: `ws://localhost:8765/ws`
- Protocol: Binary (audio) + JSON (control messages)

**Upstream Messages (Client → Server):**
```json
// Session initialization
{"type": "session_start", "kiosk_id": "kiosk-01", "kiosk_location": "Floor 1"}

// Text input
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "auto"}

// Interrupt (barge-in)
{"type": "interrupt"}

// Binary audio frames (PCM16, 16kHz, mono, 20ms frames)
<binary data>
```

**Downstream Messages (Server → Client):**
```json
// Transcript
{"type": "transcript", "text": "Where is the cafeteria?", "lang": "en", "final": true}

// LLM text chunk
{"type": "llm_text_chunk", "text": "The cafeteria is on ", "final": false}

// Status update
{"type": "status", "state": "listening"}  // listening|thinking|speaking|idle

// TTS events
{"type": "tts_start", "lang": "en"}
{"type": "tts_end"}

// Error
{"type": "error", "code": "rate_limit_exceeded", "message": "Too many requests"}

// Binary audio chunks (Opus-encoded, 48kHz, mono)
<binary data>
```

**HTTP Health Endpoint:**
- URL: `http://localhost:8000/health`
- Method: GET
- Response: `{"status": "healthy", "service": "voice-kiosk-chatbot", ...}`

### 2. vLLM (OpenAI-compatible API)

**Base URL:** `http://localhost:8001/v1`

**Endpoints:**
- `/v1/chat/completions` - Chat completions (streaming)
- `/v1/models` - List available models
- `/health` - Health check

**Example Request:**
```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct-AWQ",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### 3. Ollama (OpenAI-compatible API)

**Base URL:** `http://localhost:11434/v1`

**Endpoints:**
- `/v1/chat/completions` - Chat completions
- `/v1/models` - List models
- `/api/tags` - List local models (Ollama-specific)

**Example Request:**
```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b-instruct",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### 4. VOICEVOX (REST API)

**Base URL:** `http://localhost:50021`

**Endpoints:**
- `/audio_query` - Create audio query
- `/synthesis` - Synthesize speech
- `/version` - Get version info
- `/speakers` - List available speakers

**Example Request:**
```bash
# Step 1: Create audio query
curl -X POST "http://localhost:50021/audio_query?text=こんにちは&speaker=1"

# Step 2: Synthesize (using query from step 1)
curl -X POST "http://localhost:50021/synthesis?speaker=1" \
  -H "Content-Type: application/json" \
  -d '<audio_query_json>' \
  --output audio.wav
```

### 5. SearXNG (Web Search)

**Base URL:** `http://localhost:8080`

**Endpoints:**
- `/search?q=<query>` - Search
- `/` - Web interface

**Example Request:**
```bash
curl "http://localhost:8080/search?q=weather&format=json"
```

---

## Troubleshooting

### Common Issues

#### 1. vLLM Fails to Start

**Symptom:** Container exits immediately or OOM errors

**Solutions:**
```bash
# Check GPU memory
nvidia-smi

# Reduce GPU memory utilization in docker-compose.yml
# Change --gpu-memory-utilization from 0.90 to 0.80

# Or use smaller model
VLLM_MODEL_NAME=Qwen/Qwen2.5-3B-Instruct

# Restart vLLM
docker-compose restart vllm
```

#### 2. Voice Server Cannot Connect to vLLM

**Symptom:** "Connection refused" errors in voice-server logs

**Solutions:**
```bash
# Check vLLM health
curl http://localhost:8001/health

# Check vLLM logs
docker-compose logs vllm

# Verify network connectivity
docker-compose exec voice-server ping vllm

# Restart both services
docker-compose restart vllm voice-server
```

#### 3. No Audio Output

**Symptom:** Client receives transcript but no audio playback

**Solutions:**
```bash
# Check VOICEVOX health
curl http://localhost:50021/version

# Check TTS logs
docker-compose logs voice-server | grep TTS

# Test audio device
python3 -c "import sounddevice; print(sounddevice.query_devices())"

# Restart VOICEVOX
docker-compose restart voicevox
```

#### 4. Client Cannot Connect to Server

**Symptom:** WebSocket connection fails

**Solutions:**
```bash
# Check server is running
curl http://localhost:8000/health

# Check WebSocket endpoint
wscat -c ws://localhost:8765/ws

# Check firewall
sudo ufw status
sudo ufw allow 8765/tcp

# Check SERVER_WS_URL in client config
echo $SERVER_WS_URL
```

#### 5. Ollama Model Not Found

**Symptom:** "model not found" error when Ollama is used

**Solutions:**
```bash
# Pull the model
docker-compose exec ollama ollama pull qwen2.5:7b-instruct

# Verify model is available
docker-compose exec ollama ollama list

# Check Ollama logs
docker-compose logs ollama
```

#### 6. ChromaDB Ingestion Fails

**Symptom:** Knowledge base ingestion errors

**Solutions:**
```bash
# Check ChromaDB directory permissions
ls -la chroma_data/
sudo chown -R $USER:$USER chroma_data/

# Check building_kb documents exist
ls -la building_kb/

# Run ingestion with verbose logging
python3 server/rag/ingest.py --verbose

# Re-ingest
./scripts/ingest_kb.sh
```

### Performance Issues

#### High Latency (>1 second TTFA)

**Diagnosis:**
```bash
# Check GPU utilization
nvidia-smi

# Check vLLM performance
docker-compose logs vllm | grep "throughput"

# Check network latency
ping localhost
```

**Solutions:**
- Use float16 instead of int8 for STT (if GPU has enough VRAM)
- Increase vLLM GPU memory utilization
- Reduce max_model_len in vLLM config
- Use faster model (e.g., Qwen2.5-3B instead of 7B)

#### High Memory Usage

**Solutions:**
```bash
# Reduce vLLM memory
# Edit docker-compose.yml: --gpu-memory-utilization 0.70

# Use int8 quantization for STT
STT_COMPUTE_TYPE=int8

# Limit conversation history
# Edit server/pipeline.py: MAX_CONTEXT_TURNS = 5
```

---

## Development Mode

### Running Without Docker

**1. Start vLLM Locally:**
```bash
pip install vllm
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --port 8001 \
  --gpu-memory-utilization 0.90
```

**2. Start Ollama Locally:**
```bash
# Install Ollama from https://ollama.ai
ollama serve
ollama pull qwen2.5:7b-instruct
```

**3. Start VOICEVOX Locally:**
```bash
docker run -p 50021:50021 voicevox/voicevox_engine:cpu-ubuntu20.04-latest
```

**4. Start Voice Server:**
```bash
cd server
python -m uvicorn main:app --host 0.0.0.0 --port 8765
```

**5. Run Client:**
```bash
cd client
python main.py
```

### Hot Reload Development

**Server (with auto-reload):**
```bash
cd server
uvicorn main:app --reload --host 0.0.0.0 --port 8765
```

**Client (with auto-restart):**
```bash
cd client
while true; do python main.py; sleep 1; done
```

### Debugging

**Enable Debug Logging:**
```bash
# Server
export LOG_LEVEL=DEBUG
python -m uvicorn main:app --log-level debug

# Client
# Edit client/main.py: logging.basicConfig(level=logging.DEBUG)
```

**Use Python Debugger:**
```python
# Add breakpoint in code
import pdb; pdb.set_trace()

# Or use ipdb
import ipdb; ipdb.set_trace()
```

---

## Useful Commands

### Docker Compose

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Restart specific service
docker-compose restart voice-server

# View logs
docker-compose logs -f voice-server

# Check status
docker-compose ps

# Rebuild and restart
docker-compose up -d --build voice-server

# Remove all containers and volumes (WARNING: deletes data)
docker-compose down -v
```

### Makefile Commands

```bash
# Setup
make setup              # Create directory structure
make pull               # Pull latest Docker images

# Service Management
make up                 # Start all services
make down               # Stop all services
make restart            # Restart all services
make rebuild            # Rebuild and restart

# Monitoring
make logs               # View all logs
make logs-server        # View voice-server logs
make logs-vllm          # View vLLM logs
make ps                 # Show service status
make health             # Check service health

# Maintenance
make clean              # Remove stopped containers
make clean-all          # Remove containers and volumes

# Ollama
make ollama-pull        # Pull Qwen2.5 model
make ollama-list        # List Ollama models
```

---

## Next Steps

1. **Customize Knowledge Base:**
   - Edit files in `building_kb/` with your building information
   - Run `./scripts/ingest_kb.sh` to update ChromaDB

2. **Configure Kiosk Hardware:**
   - Run `./scripts/setup_kiosk_os.sh` on Ubuntu 22.04
   - Install systemd service: `sudo cp client/kiosk.service /etc/systemd/system/`
   - Enable auto-start: `sudo systemctl enable kiosk.service`

3. **Production Deployment:**
   - Use WSS (WebSocket Secure) for encrypted transport
   - Set up nginx reverse proxy
   - Configure firewall rules
   - Set up monitoring and alerting
   - Implement backup strategy for ChromaDB

4. **Optional Enhancements:**
   - Install CosyVoice for better English TTS
   - Install Fish Speech for Japanese TTS fallback
   - Install opuslib for audio compression
   - Add more building knowledge documents

---

## Support

For issues and questions:
1. Check logs: `docker-compose logs -f`
2. Check service health: `make health`
3. Review troubleshooting section above
4. Check GPU status: `nvidia-smi`
5. Refer to documentation in `README.md` and `DOCKER_QUICKSTART.md`

---

## License

See main project LICENSE file.
