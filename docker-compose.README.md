# Docker Compose Infrastructure

This Docker Compose setup provides all the backend services for the Real-Time Streaming Voice Chatbot system.

## Services

### 1. voice-server (Port 8765, 8000)
- Main application server handling WebSocket connections, STT, LLM orchestration, TTS, and RAG
- Requires GPU access via NVIDIA Container Toolkit
- Health check endpoint: http://localhost:8000/health

### 2. vllm (Port 8001)
- Primary LLM inference engine using vLLM with Qwen2.5-7B-Instruct-AWQ
- GPU-accelerated for fast inference
- Configured with 90% GPU memory utilization
- Health check endpoint: http://localhost:8001/health

### 3. ollama (Port 11434)
- Secondary LLM inference engine as fallback
- Can use GPU or CPU
- Runs Qwen2.5:7b-instruct model

### 4. voicevox (Port 50021)
- Japanese TTS engine with REST API
- CPU-based inference
- Health check endpoint: http://localhost:50021/version

### 5. searxng (Port 8080)
- Self-hosted web search service
- Used by LLM for web search tool calls
- Base URL: http://localhost:8080/

## Prerequisites

### System Requirements
- Ubuntu 22.04 or similar Linux distribution
- NVIDIA GPU with 12-16GB VRAM (recommended)
- NVIDIA Container Toolkit installed
- Docker Engine 20.10+ with Docker Compose V2
- At least 50GB free disk space for models

### Install NVIDIA Container Toolkit

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

## Directory Structure

The following directories must exist before starting the services:

```
.
├── docker-compose.yml
├── models/                    # AI model weights (mounted read-only)
│   ├── whisper/
│   ├── embeddings/
│   ├── cosyvoice/
│   └── ollama/
├── building_kb/               # Building knowledge base documents (mounted read-only)
│   ├── floors/
│   ├── facilities/
│   ├── rooms/
│   └── japanese/
├── chroma_data/               # ChromaDB persistent storage
├── searxng/                   # SearXNG configuration (optional)
└── server/                    # Voice server source code
    ├── Dockerfile
    ├── requirements.txt
    └── ...
```

Create the required directories:

```bash
mkdir -p models/whisper models/embeddings models/cosyvoice models/ollama
mkdir -p building_kb/floors building_kb/facilities building_kb/rooms building_kb/japanese
mkdir -p chroma_data
mkdir -p searxng
```

## Configuration

### Environment Variables

Create a `.env` file in the same directory as `docker-compose.yml`:

```bash
# Optional: Grok API key for tertiary LLM fallback
GROK_API_KEY=your_grok_api_key_here

# Optional: Building name for context
BUILDING_NAME=Office Building

# Optional: Hugging Face token for model downloads
HUGGING_FACE_HUB_TOKEN=your_hf_token_here

# Optional: SearXNG secret key
SEARXNG_SECRET=your_random_secret_here

# Optional: Log level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO
```

### Model Downloads

Before starting the services, download the required models:

```bash
# Run the model download script
./scripts/download_models.sh
```

This will download:
- Whisper Large V3 Turbo
- multilingual-e5-large embeddings
- CosyVoice2-0.5B
- Qwen2.5-7B-Instruct-AWQ

### Knowledge Base Ingestion

After starting the services, ingest the building knowledge base:

```bash
# Run the knowledge base ingestion script
./scripts/ingest_kb.sh
```

## Usage

### Start All Services

```bash
# Start all services in detached mode
docker compose up -d

# View logs
docker compose logs -f

# View logs for specific service
docker compose logs -f voice-server
```

### Stop All Services

```bash
# Stop all services
docker compose down

# Stop and remove volumes (WARNING: deletes ChromaDB data)
docker compose down -v
```

### Restart a Single Service

```bash
# Restart voice-server
docker compose restart voice-server

# Rebuild and restart voice-server
docker compose up -d --build voice-server
```

### Check Service Health

```bash
# Check all service status
docker compose ps

# Check voice-server health
curl http://localhost:8000/health

# Check vLLM health
curl http://localhost:8001/health

# Check VOICEVOX health
curl http://localhost:50021/version
```

## Networking

All services are connected via the `voice-network` bridge network. Services can communicate using their container names as hostnames:

- `voice-server` → `vllm:8001`
- `voice-server` → `ollama:11434`
- `voice-server` → `voicevox:50021`
- `voice-server` → `searxng:8080`

## GPU Resource Allocation

The GPU is shared between:
- **vllm**: ~90% GPU memory (primary LLM inference)
- **voice-server**: ~10% GPU memory (STT, TTS, embeddings)

If you have multiple GPUs, you can assign specific GPUs to services:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ['0']  # Use GPU 0
          capabilities: [gpu]
```

## Troubleshooting

### vLLM fails to start
- Check GPU memory: `nvidia-smi`
- Reduce `--gpu-memory-utilization` in docker-compose.yml
- Ensure model weights are downloaded to `./models/`

### voice-server cannot connect to vLLM
- Check vLLM health: `curl http://localhost:8001/health`
- Check vLLM logs: `docker compose logs vllm`
- Verify network connectivity: `docker compose exec voice-server ping vllm`

### VOICEVOX fails health check
- Check VOICEVOX logs: `docker compose logs voicevox`
- Verify port is accessible: `curl http://localhost:50021/version`
- Try restarting: `docker compose restart voicevox`

### Ollama model not found
- Pull the model manually:
  ```bash
  docker compose exec ollama ollama pull qwen2.5:7b-instruct
  ```

### ChromaDB data lost after restart
- Ensure `./chroma_data` directory exists and has correct permissions
- Check volume mount in docker-compose.yml
- Verify data persists: `ls -la ./chroma_data/`

## Performance Tuning

### Reduce Latency
- Use float16 compute type for STT (requires ≥12GB VRAM)
- Increase vLLM GPU memory utilization to 0.95
- Use SSD storage for model weights

### Reduce Memory Usage
- Use int8 compute type for STT
- Reduce vLLM `--max-model-len` to 2048
- Reduce vLLM GPU memory utilization to 0.80

### Scale for Multiple Kiosks
- Run multiple voice-server replicas behind a load balancer
- Share vLLM, Ollama, VOICEVOX, SearXNG across all replicas
- Use Redis for session state if needed

## Security Considerations

- All services run on a private network by default
- Expose only necessary ports to the host
- Use WSS (WebSocket Secure) for production deployments
- Set strong `SEARXNG_SECRET` in production
- Never commit `.env` file with secrets to version control
- Consider using Docker secrets for sensitive data

## Monitoring

### Health Checks
All services have health checks configured. Check status:

```bash
docker compose ps
```

Healthy services show `healthy` status.

### Resource Usage

Monitor GPU usage:
```bash
watch -n 1 nvidia-smi
```

Monitor container resources:
```bash
docker stats
```

### Logs

Centralized logging:
```bash
# All services
docker compose logs -f

# Specific service with timestamps
docker compose logs -f --timestamps voice-server

# Last 100 lines
docker compose logs --tail=100 voice-server
```

## Maintenance

### Update Services

```bash
# Pull latest images
docker compose pull

# Rebuild and restart
docker compose up -d --build
```

### Backup ChromaDB Data

```bash
# Create backup
tar -czf chroma_backup_$(date +%Y%m%d).tar.gz chroma_data/

# Restore backup
tar -xzf chroma_backup_20240101.tar.gz
```

### Clean Up

```bash
# Remove stopped containers
docker compose rm

# Remove unused images
docker image prune -a

# Remove unused volumes (WARNING: deletes data)
docker volume prune
```

## Development Mode

For development, the voice-server source code is mounted as a volume. Changes to Python files will require a restart:

```bash
# Restart to pick up code changes
docker compose restart voice-server
```

For hot-reloading during development, modify the voice-server command in docker-compose.yml:

```yaml
command: uvicorn server.main:app --host 0.0.0.0 --port 8765 --reload
```

## Production Deployment

For production:
1. Remove source code volume mounts
2. Use specific image tags instead of `latest`
3. Enable WSS (WebSocket Secure) with TLS certificates
4. Set up proper logging and monitoring
5. Configure automatic restarts and health checks
6. Use Docker secrets for sensitive configuration
7. Set up backup automation for ChromaDB data
8. Configure firewall rules to restrict access

## License

See main project LICENSE file.
