# Voice Kiosk Chatbot

A fully self-hosted, bilingual (English + Japanese) real-time streaming voice chatbot system for kiosk and robot deployment. Achieves sub-600ms Time-to-First-Audio through aggressive pipeline parallelization, sentence-boundary TTS streaming, and a three-tier LLM fallback chain.

## Features

- **Bilingual Support**: English and Japanese with automatic language detection
- **Real-time Streaming**: Sub-600ms Time-to-First-Audio (TTFA)
- **Self-hosted**: Fully local deployment except optional Grok API fallback
- **LLM Fallback Chain**: vLLM → Ollama → Grok API for high availability
- **RAG Integration**: ChromaDB-backed building knowledge base
- **Voice Activity Detection**: Automatic speech start/end detection
- **Barge-in Support**: Interrupt system responses naturally
- **Kiosk-ready**: Fullscreen PyQt6 UI with touch support

## Architecture

### Server (GPU)
- **STT**: Whisper Large V3 Turbo via faster-whisper
- **LLM**: Qwen2.5-7B-Instruct via vLLM/Ollama, Grok-3-fast fallback
- **TTS**: CosyVoice2 (English), VOICEVOX (Japanese)
- **RAG**: ChromaDB with multilingual-e5-large embeddings
- **Web Search**: Self-hosted SearXNG integration

### Client (CPU)
- **Audio Capture**: 16kHz PCM16 via sounddevice
- **VAD**: Silero VAD for speech detection
- **UI**: PyQt6 fullscreen kiosk interface
- **Playback**: Opus-decoded audio via sounddevice

## System Requirements

### Server
- **GPU**: NVIDIA GPU with 12-16GB VRAM
- **OS**: Ubuntu 22.04 or compatible
- **CUDA**: 11.8 or later
- **Docker**: With NVIDIA Container Toolkit

### Client
- **OS**: Ubuntu 22.04 (for kiosk deployment)
- **Audio**: Microphone and speakers
- **Display**: 1920x1080 or higher (for kiosk UI)

## Installation

### 1. Clone Repository

```bash
git clone <repository-url>
cd voice-kiosk-chatbot
```

### 2. Download Models

```bash
chmod +x scripts/download_models.sh
./scripts/download_models.sh
```

**Note**: Model download script is a placeholder. Please download models manually:
- Whisper Large V3 Turbo
- multilingual-e5-large
- CosyVoice2-0.5B
- Qwen2.5-7B-Instruct-AWQ

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

Required environment variables:
- `VLLM_BASE_URL`: vLLM server URL
- `OLLAMA_BASE_URL`: Ollama server URL
- `GROK_API_KEY`: xAI API key (optional)
- `CHROMADB_PATH`: Path to ChromaDB storage
- `SERVER_WS_URL`: WebSocket server URL (client)
- `KIOSK_ID`: Unique kiosk identifier (client)
- `KIOSK_LOCATION`: Physical location (client)

### 4. Ingest Knowledge Base

```bash
chmod +x scripts/ingest_kb.sh
./scripts/ingest_kb.sh
```

### 5. Start Server (Docker Compose)

```bash
docker-compose up -d
```

This starts:
- voice-server (main server)
- vLLM (primary LLM)
- Ollama (secondary LLM)
- VOICEVOX (Japanese TTS)
- SearXNG (web search)

### 6. Setup Client (Kiosk)

```bash
# Install Python dependencies
pip install -r client/requirements.txt

# Configure kiosk OS (Ubuntu 22.04)
sudo ./scripts/setup_kiosk_os.sh

# Enable and start service
sudo systemctl enable kiosk.service
sudo systemctl start kiosk.service
```

## Usage

### Server

The server runs automatically via Docker Compose. Check health:

```bash
curl http://localhost:8765/health
```

### Client

The client runs as a systemd service on kiosk hardware. Check status:

```bash
systemctl status kiosk.service
```

View logs:

```bash
journalctl -u kiosk.service -f
```

### Manual Client Start

For development/testing:

```bash
python3 client/main.py
```

## Configuration

### Server Configuration

Edit `server/config.py` or set environment variables:

```python
VLLM_BASE_URL = "http://localhost:8000/v1"
VLLM_MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct-AWQ"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL_NAME = "qwen2.5:7b"
GROK_API_KEY = "xai-..."  # Optional
CHROMADB_PATH = "./chroma_db"
BUILDING_NAME = "Office Building"
```

### Client Configuration

Edit `client/config.py` or set environment variables:

```python
SERVER_WS_URL = "ws://server:8765/ws"
KIOSK_ID = "kiosk-01"
KIOSK_LOCATION = "Floor 1 Lobby"
```

## Knowledge Base

Add building knowledge documents to `building_kb/`:

```
building_kb/
├── floors/
│   ├── floor_01.md
│   ├── floor_02.md
│   └── ...
├── facilities/
│   ├── elevators.md
│   ├── restrooms.md
│   └── ...
└── japanese/
    ├── floor_01_ja.md
    └── ...
```

After adding documents, re-run ingestion:

```bash
./scripts/ingest_kb.sh
```

## Troubleshooting

### Server Issues

**vLLM not starting:**
- Check GPU availability: `nvidia-smi`
- Check VRAM usage: Ensure 12-16GB available
- Check logs: `docker-compose logs vllm`

**ChromaDB errors:**
- Ensure ChromaDB path is writable
- Re-run ingestion: `./scripts/ingest_kb.sh`

**VOICEVOX not responding:**
- Check container status: `docker-compose ps voicevox`
- Restart: `docker-compose restart voicevox`

### Client Issues

**No audio input:**
- Check microphone: `arecord -l`
- Test recording: `arecord -d 5 test.wav`
- Check permissions: User must be in `audio` group

**No audio output:**
- Check speakers: `aplay -l`
- Test playback: `aplay test.wav`

**WebSocket connection failed:**
- Check server is running: `curl http://server:8765/health`
- Check network connectivity
- Check firewall rules

**UI not displaying:**
- Check DISPLAY variable: `echo $DISPLAY`
- Check X11 permissions: `xhost +local:`

## Development

### Running Tests

```bash
# Server tests
cd server
pytest

# Client tests
cd client
pytest
```

### Code Structure

```
voice-kiosk-chatbot/
├── server/              # GPU inference server
│   ├── main.py         # FastAPI WebSocket server
│   ├── pipeline.py     # Pipeline orchestrator
│   ├── stt/            # Speech-to-text
│   ├── llm/            # LLM backends
│   ├── tts/            # Text-to-speech
│   ├── rag/            # RAG and embeddings
│   ├── search/         # Web search
│   └── tools/          # LLM tools
├── client/             # CPU kiosk client
│   ├── main.py         # Client entry point
│   ├── audio_capture.py
│   ├── vad.py
│   ├── ws_client.py
│   ├── audio_playback.py
│   ├── keyboard_input.py
│   └── ui/             # PyQt6 UI
├── building_kb/        # Knowledge base documents
├── scripts/            # Setup and utility scripts
└── docker-compose.yml  # Server deployment
```

## Performance

Target latencies (under normal conditions):
- **STT**: <150ms
- **RAG**: <30ms
- **LLM First Token**: <200ms (vLLM)
- **TTS First Sentence**: <150ms
- **Total TTFA**: <600ms

## License

[Add license information]

## Contributing

[Add contribution guidelines]

## Support

For issues and questions, please open a GitHub issue.
