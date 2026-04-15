# Docker Compose Setup - Task 2 Summary

## What Was Created

This task created a complete Docker Compose infrastructure for the Voice Kiosk Chatbot system.

### Core Files

1. **docker-compose.yml** - Main Docker Compose configuration
   - Defines 5 services: voice-server, vllm, ollama, voicevox, searxng
   - Configures GPU access via NVIDIA Container Toolkit
   - Sets up volume mounts for models, knowledge base, and ChromaDB
   - Configures service networking and health checks
   - Implements service dependencies and restart policies

2. **.dockerignore** - Docker build optimization
   - Excludes unnecessary files from Docker build context
   - Reduces build time and image size

3. **.env.example** - Environment configuration template
   - Updated with Docker Compose specific variables
   - Includes service URLs using container names
   - Documents all configuration options

### Documentation

4. **docker-compose.README.md** - Comprehensive documentation
   - Service descriptions and architecture
   - Prerequisites and installation instructions
   - Configuration guide
   - Usage examples
   - Troubleshooting guide
   - Performance tuning tips
   - Security considerations

5. **DOCKER_QUICKSTART.md** - Quick start guide
   - 5-step setup process
   - Common commands
   - Verification steps
   - Troubleshooting shortcuts

6. **DOCKER_SETUP_SUMMARY.md** - This file
   - Overview of what was created
   - Requirements mapping

### Configuration

7. **searxng/settings.yml** - SearXNG configuration
   - Minimal configuration for web search
   - Enabled fast and reliable search engines
   - 5-second timeout for requests
   - JSON output format support

### Scripts

8. **scripts/setup_docker_dirs.sh** - Directory structure setup
   - Creates all required directories
   - Sets appropriate permissions
   - Provides next steps guidance

9. **scripts/validate_docker_setup.sh** - Setup validation
   - Checks Docker and NVIDIA Container Toolkit installation
   - Validates directory structure
   - Checks configuration files
   - Verifies disk space and GPU memory
   - Provides actionable feedback

### Automation

10. **Makefile** - Common operations automation
    - Setup commands: `make setup`, `make pull`
    - Service management: `make up`, `make down`, `make restart`
    - Monitoring: `make logs`, `make ps`, `make health`
    - Maintenance: `make clean`, `make rebuild`
    - Individual service control
    - Development helpers

## Services Configuration

### 1. voice-server
- **Ports**: 8765 (WebSocket), 8000 (HTTP health)
- **GPU**: Yes (NVIDIA Container Toolkit)
- **Volumes**: models (ro), building_kb (ro), chroma_data (rw), server code (dev)
- **Health Check**: HTTP GET /health every 30s
- **Dependencies**: vllm (healthy), ollama (started), voicevox (healthy), searxng (started)

### 2. vllm
- **Image**: vllm/vllm-openai:latest
- **Port**: 8001
- **GPU**: Yes (90% memory utilization)
- **Model**: Qwen2.5-7B-Instruct-AWQ
- **Health Check**: HTTP GET /health every 30s
- **Start Period**: 120s (model loading time)

### 3. ollama
- **Image**: ollama/ollama:latest
- **Port**: 11434
- **GPU**: Yes (optional, also works on CPU)
- **Model**: qwen2.5:7b-instruct
- **Volume**: ollama_data (persistent)

### 4. voicevox
- **Image**: voicevox/voicevox_engine:cpu-ubuntu20.04-latest
- **Port**: 50021
- **CPU**: 4 threads
- **Health Check**: HTTP GET /version every 30s

### 5. searxng
- **Image**: searxng/searxng:latest
- **Port**: 8080
- **Volume**: searxng config (rw)
- **Security**: Minimal capabilities (CHOWN, SETGID, SETUID, DAC_OVERRIDE)

## Requirements Mapping

This task fulfills the following requirements from the spec:

### Requirement 20: Docker Deployment
- ✅ 20.1: Server deployable via Docker Compose
- ✅ 20.2: Services included: voice-server, vLLM, Ollama, VOICEVOX, SearXNG
- ✅ 20.3: GPU access via NVIDIA Container Toolkit for voice-server
- ✅ 20.4: vLLM runs Qwen2.5-7B-Instruct with AWQ quantization
- ✅ 20.5: VOICEVOX exposes REST API on port 50021
- ✅ 20.6: SearXNG exposes search API on port 8080
- ✅ 20.7: Model weights mounted from host filesystem (read-only)
- ✅ 20.8: Building knowledge base mounted from host filesystem (read-only)
- ✅ 20.9: ChromaDB data persists across container restarts

### Requirement 23: Health Monitoring
- ✅ 23.6: Docker Compose health checks configured for voice-server container
  - Interval: 30 seconds
  - Timeout: 10 seconds
  - Retries: 3
  - Start period: 60 seconds

## Network Architecture

All services communicate via the `voice-network` bridge network:

```
voice-server:8765 ← WebSocket ← Client (external)
voice-server:8000 ← HTTP health check ← Monitoring (external)

voice-server → vllm:8001 (LLM inference)
voice-server → ollama:11434 (LLM fallback)
voice-server → voicevox:50021 (Japanese TTS)
voice-server → searxng:8080 (Web search)
```

## Volume Mounts

### Read-Only Mounts
- `./models:/models:ro` - AI model weights (shared by voice-server and vllm)
- `./building_kb:/building_kb:ro` - Building knowledge base documents

### Read-Write Mounts
- `./chroma_data:/chroma` - ChromaDB persistent storage
- `./searxng:/etc/searxng:rw` - SearXNG configuration
- `./server:/app/server` - Server source code (development only)

### Named Volumes
- `ollama_data` - Ollama model storage (persistent)

## GPU Resource Allocation

Total VRAM required: 12-16GB

- **vllm**: ~10-12GB (90% of available GPU memory)
  - Qwen2.5-7B-Instruct-AWQ model
  - KV cache and inference buffers
  
- **voice-server**: ~2-4GB (remaining GPU memory)
  - Whisper Large V3 Turbo (~1.5GB)
  - CosyVoice2-0.5B (~500MB)
  - Inference buffers

## Environment Variables

### Required
- `VLLM_BASE_URL` - vLLM service URL (default: http://vllm:8001/v1)
- `OLLAMA_BASE_URL` - Ollama service URL (default: http://ollama:11434/v1)
- `TTS_JP_URL` - VOICEVOX service URL (default: http://voicevox:50021)
- `CHROMADB_PATH` - ChromaDB storage path (default: /chroma)
- `SEARXNG_URL` - SearXNG service URL (default: http://searxng:8080)

### Optional
- `GROK_API_KEY` - Grok API key for cloud LLM fallback
- `HUGGING_FACE_HUB_TOKEN` - HuggingFace token for model downloads
- `SEARXNG_SECRET` - SearXNG secret key (change in production)
- `BUILDING_NAME` - Building name for context
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)

## Quick Start Commands

```bash
# 1. Setup directory structure
make setup

# 2. Validate setup
./scripts/validate_docker_setup.sh

# 3. Configure environment
cp .env.example .env
nano .env

# 4. Start all services
make up

# 5. Check health
make health

# 6. View logs
make logs

# 7. Stop services
make down
```

## Next Steps

After completing this task, the following tasks should be done:

1. **Task 3**: Create server Dockerfile
   - Define Python 3.11 base image with CUDA support
   - Install system dependencies
   - Install Python dependencies
   - Set up entry point

2. **Download Models**: Run model download script
   - Whisper Large V3 Turbo
   - multilingual-e5-large
   - CosyVoice2-0.5B
   - Qwen2.5-7B-Instruct-AWQ

3. **Create Knowledge Base**: Add building documents
   - Floor plans and descriptions
   - Facility locations
   - Room directory
   - Emergency information
   - Both English and Japanese versions

4. **Ingest Knowledge Base**: Run ingestion script
   - Chunk documents
   - Generate embeddings
   - Store in ChromaDB

5. **Test Services**: Verify end-to-end functionality
   - WebSocket connection
   - STT transcription
   - LLM inference with fallback
   - TTS synthesis
   - RAG retrieval
   - Web search

## Files Created

```
.
├── docker-compose.yml                    # Main Docker Compose configuration
├── .dockerignore                         # Docker build optimization
├── .env.example                          # Updated environment template
├── docker-compose.README.md              # Comprehensive documentation
├── DOCKER_QUICKSTART.md                  # Quick start guide
├── DOCKER_SETUP_SUMMARY.md               # This file
├── Makefile                              # Common operations automation
├── searxng/
│   └── settings.yml                      # SearXNG configuration
└── scripts/
    ├── setup_docker_dirs.sh              # Directory structure setup
    └── validate_docker_setup.sh          # Setup validation
```

## Testing Checklist

- [ ] Docker and Docker Compose installed
- [ ] NVIDIA Container Toolkit installed and working
- [ ] GPU has ≥12GB VRAM
- [ ] Directory structure created (`make setup`)
- [ ] Environment variables configured (`.env`)
- [ ] docker-compose.yml syntax valid (`docker compose config`)
- [ ] Services start successfully (`make up`)
- [ ] All services show healthy status (`make health`)
- [ ] GPU memory allocated correctly (`nvidia-smi`)
- [ ] voice-server health endpoint responds (`curl http://localhost:8000/health`)
- [ ] vLLM health endpoint responds (`curl http://localhost:8001/health`)
- [ ] VOICEVOX version endpoint responds (`curl http://localhost:50021/version`)
- [ ] SearXNG accessible (`curl http://localhost:8080/`)
- [ ] Services can communicate (check logs)
- [ ] ChromaDB data persists after restart
- [ ] Services restart automatically on failure

## Known Limitations

1. **GPU Sharing**: All GPU services share a single GPU. For production with high load, consider multiple GPUs or separate servers.

2. **Model Downloads**: Models must be downloaded separately before starting services. The vLLM service will fail if the model is not available.

3. **Ollama Model**: The Ollama model must be pulled manually after starting the service:
   ```bash
   make ollama-pull
   ```

4. **Development Mode**: The voice-server source code is mounted as a volume for development. Remove this mount in production.

5. **Security**: Default configuration uses HTTP. For production, enable WSS (WebSocket Secure) and use proper secrets.

6. **Resource Limits**: No CPU or memory limits are set. Consider adding resource limits for production deployments.

## Production Considerations

For production deployment:

1. **Remove development mounts**: Remove `./server:/app/server` volume mount
2. **Use specific image tags**: Replace `latest` with specific version tags
3. **Enable TLS**: Configure WSS with TLS certificates
4. **Set resource limits**: Add CPU and memory limits to services
5. **Use Docker secrets**: Store sensitive data in Docker secrets
6. **Set up monitoring**: Integrate with Prometheus/Grafana
7. **Configure backups**: Automate ChromaDB data backups
8. **Harden security**: Review and restrict network access
9. **Use strong secrets**: Generate strong random values for all secrets
10. **Enable logging**: Configure centralized logging (ELK, Loki, etc.)

## Support

For issues:
1. Check validation: `./scripts/validate_docker_setup.sh`
2. Check service health: `make health`
3. Check logs: `make logs`
4. Check GPU: `nvidia-smi`
5. Review documentation: `docker-compose.README.md`
6. Review troubleshooting: `DOCKER_QUICKSTART.md`

## License

See main project LICENSE file.
