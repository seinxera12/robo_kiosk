# Voice Kiosk Chatbot

A fully self-hosted, bilingual (English + Japanese) real-time streaming voice chatbot system for kiosk and robot deployment. Achieves sub-600ms Time-to-First-Audio through aggressive pipeline parallelization, sentence-boundary TTS streaming, and a three-tier LLM fallback chain.

## Features

- **Bilingual Support**: English and Japanese with automatic language detection
- **Real-time Streaming**: Sub-600ms Time-to-First-Audio (TTFA)
- **Self-hosted**: Fully local deployment
- **LLM Fallback Chain**: vLLM → Ollama for high availability
- **RAG Integration**: ChromaDB-backed building knowledge base
- **Voice Activity Detection**: Automatic speech start/end detection
- **Barge-in Support**: Interrupt system responses naturally
- **Kiosk-ready**: Fullscreen PyQt6 UI with touch support

## Architecture

### Server (GPU)
- **STT**: Whisper Large V3 Turbo via faster-whisper
- **LLM**: Qwen2.5-3b-Instruct via vLLM (primary) / Ollama (fallback)
- **TTS**: Kokoro-82M (English + Japanese secondary), KokoClone (Japanese primary)
- **RAG**: ChromaDB with multilingual-e5-large embeddings
- **Web Search**: Self-hosted SearXNG integration

### Frontend (Browser)
- **UI**: React + Vite web dashboard
- **Audio Capture**: 16kHz PCM16 via Web Audio API + AudioWorklet
- **VAD**: In-browser voice activity detection
- **Playback**: Streamed audio via Web Audio API

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
- Kokoro-82M
- Qwen2.5-7B-Instruct-AWQ

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

Required environment variables:
- `VLLM_BASE_URL`: vLLM server URL
- `OLLAMA_BASE_URL`: Ollama server URL
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
- Ollama (secondary LLM; vLLM is the intended primary — enable its service on the GPU host)
- SearXNG + Redis (web search)

### 6. Run the Frontend

```bash
cd frontend
npm install
npm run dev
```

## Usage

### Server

The server runs automatically via Docker Compose. Check health:

```bash
curl http://localhost:8765/health
```

### Frontend

The React frontend connects to the server WebSocket at `ws://<server>:8765/ws`.
For development it runs via `npm run dev`; for kiosk deployment build with
`npm run build` and serve the `frontend/dist` output.

## Configuration

### Server Configuration

Edit `server/config.py` or set environment variables:

```python
VLLM_BASE_URL = "http://localhost:8000/v1"
VLLM_MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct-AWQ"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL_NAME = "qwen2.5:7b"
CHROMADB_PATH = "./chroma_db"
BUILDING_NAME = "Office Building"
```

### Frontend Configuration

Edit `frontend/.env` (see `frontend/.env.example`) to point the UI at the server:

```
VITE_SERVER_WS_URL=ws://localhost:8765/ws
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

**KokoClone (Japanese TTS) not responding:**
- Ensure the KokoClone microservice is running (default port 5003)
- The server automatically falls back to Kokoro-82M Japanese if it is down

### Frontend Issues

**No audio input:**
- Grant microphone permission in the browser
- A secure context (https:// or localhost) is required for `getUserMedia`

**WebSocket connection failed:**
- Check server is running: `curl http://<server>:8765/health`
- Verify `VITE_SERVER_WS_URL` points at the server
- Check network connectivity and firewall rules

## Development

### Running Tests

```bash
# Server tests
pytest server tests

# Frontend tests
cd frontend
npm test
```

### Code Structure

```
voice-kiosk-chatbot/
├── server/              # GPU inference server
│   ├── main.py         # FastAPI WebSocket server
│   ├── pipeline.py     # Pipeline orchestrator
│   ├── stt/            # Speech-to-text
│   ├── llm/            # LLM backends
│   ├── tts/            # Text-to-speech (Kokoro-82M, KokoClone)
│   ├── rag/            # RAG and embeddings
│   ├── search/         # Web search
│   └── tools/          # LLM tools
├── frontend/           # React + Vite web UI
├── building_kb/        # Knowledge base documents
├── scripts/            # Setup and utility scripts
├── searxng/            # SearXNG search config
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
