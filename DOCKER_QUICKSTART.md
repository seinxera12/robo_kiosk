# Docker Compose Quick Start Guide

This guide will help you get the voice chatbot system up and running quickly using Docker Compose.

## Prerequisites

- Ubuntu 22.04 or similar Linux distribution
- NVIDIA GPU with 12-16GB VRAM
- NVIDIA Container Toolkit installed
- Docker Engine 20.10+ with Docker Compose V2
- At least 50GB free disk space

## Quick Start (5 Steps)

### 1. Install NVIDIA Container Toolkit

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

### 2. Set Up Directory Structure

```bash
# Make setup script executable
chmod +x scripts/setup_docker_dirs.sh

# Run setup script
./scripts/setup_docker_dirs.sh
```

This creates:
- `models/` - AI model weights storage
- `building_kb/` - Building knowledge base documents
- `chroma_data/` - ChromaDB persistent storage
- `searxng/` - SearXNG configuration

### 3. Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env file with your configuration
nano .env
```

**Minimum required changes:**
- Set `GROK_API_KEY` if you want cloud LLM fallback (optional)
- Set `BUILDING_NAME` to your building name
- Change `SEARXNG_SECRET` to a random string in production

### 4. Download AI Models

```bash
# Make download script executable
chmod +x scripts/download_models.sh

# Download all required models (this will take a while)
./scripts/download_models.sh
```

This downloads:
- Whisper Large V3 Turbo (~1.5GB)
- multilingual-e5-large embeddings (~2GB)
- CosyVoice2-0.5B (~500MB)
- Qwen2.5-7B-Instruct-AWQ (~4GB)

### 5. Start All Services

```bash
# Start all services in detached mode
docker compose up -d

# View logs to monitor startup
docker compose logs -f

# Wait for all services to become healthy (2-3 minutes)
docker compose ps
```

## Verify Installation

### Check Service Health

```bash
# Check all services
docker compose ps

# Should show all services as "healthy" or "running"
```

### Test Individual Services

```bash
# Test voice-server health endpoint
curl http://localhost:8000/health

# Test vLLM health endpoint
curl http://localhost:8001/health

# Test VOICEVOX version endpoint
curl http://localhost:50021/version

# Test SearXNG
curl http://localhost:8080/
```

### Check GPU Usage

```bash
# Monitor GPU usage in real-time
watch -n 1 nvidia-smi
```

You should see:
- vLLM using ~90% of GPU memory
- voice-server using ~10% of GPU memory

## Ingest Building Knowledge Base

After services are running, ingest your building knowledge documents:

```bash
# Make ingestion script executable
chmod +x scripts/ingest_kb.sh

# Run ingestion script
./scripts/ingest_kb.sh
```

This will:
1. Read markdown documents from `building_kb/`
2. Chunk documents into appropriate sizes
3. Generate embeddings
4. Store in ChromaDB

## Connect Client

The server is now ready to accept WebSocket connections from kiosk clients.

### Test with WebSocket Client

```bash
# Install wscat for testing
npm install -g wscat

# Connect to WebSocket endpoint
wscat -c ws://localhost:8765/ws

# Send session start message
{"type": "session_start", "kiosk_id": "test-01", "kiosk_location": "Test Location"}

# Send text input message
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "auto"}
```

### Run Kiosk Client

```bash
# Install client dependencies
cd client
pip install -r requirements.txt

# Run client application
python main.py
```

## Common Commands

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f voice-server
docker compose logs -f vllm

# Last 100 lines
docker compose logs --tail=100 voice-server
```

### Restart Services

```bash
# Restart all services
docker compose restart

# Restart specific service
docker compose restart voice-server

# Rebuild and restart
docker compose up -d --build voice-server
```

### Stop Services

```bash
# Stop all services (keeps data)
docker compose down

# Stop and remove volumes (WARNING: deletes ChromaDB data)
docker compose down -v
```

### Update Services

```bash
# Pull latest images
docker compose pull

# Rebuild and restart
docker compose up -d --build
```

## Troubleshooting

### vLLM fails to start

**Symptom:** vLLM container exits immediately or shows OOM errors

**Solution:**
```bash
# Check GPU memory
nvidia-smi

# Reduce GPU memory utilization in docker-compose.yml
# Change --gpu-memory-utilization from 0.90 to 0.80

# Restart vLLM
docker compose up -d vllm
```

### voice-server cannot connect to vLLM

**Symptom:** voice-server logs show connection errors to vLLM

**Solution:**
```bash
# Check vLLM health
curl http://localhost:8001/health

# Check vLLM logs
docker compose logs vllm

# Verify network connectivity
docker compose exec voice-server ping vllm

# Restart both services
docker compose restart vllm voice-server
```

### VOICEVOX fails health check

**Symptom:** VOICEVOX container shows unhealthy status

**Solution:**
```bash
# Check VOICEVOX logs
docker compose logs voicevox

# Test VOICEVOX endpoint
curl http://localhost:50021/version

# Restart VOICEVOX
docker compose restart voicevox
```

### Ollama model not found

**Symptom:** Ollama backend fails with "model not found" error

**Solution:**
```bash
# Pull the model manually
docker compose exec ollama ollama pull qwen2.5:7b-instruct

# Verify model is available
docker compose exec ollama ollama list
```

### ChromaDB data lost after restart

**Symptom:** Knowledge base needs to be re-ingested after restart

**Solution:**
```bash
# Check chroma_data directory exists
ls -la chroma_data/

# Check volume mount in docker-compose.yml
docker compose config | grep chroma

# Ensure proper permissions
sudo chown -R $USER:$USER chroma_data/

# Re-ingest knowledge base
./scripts/ingest_kb.sh
```

### Out of disk space

**Symptom:** Services fail to start or crash with disk space errors

**Solution:**
```bash
# Check disk usage
df -h

# Clean up Docker resources
docker system prune -a

# Remove unused volumes
docker volume prune

# Remove old images
docker image prune -a
```

## Performance Tuning

### For Lower Latency

```yaml
# In docker-compose.yml, for voice-server:
environment:
  - STT_COMPUTE_TYPE=float16  # Requires ≥12GB VRAM

# For vLLM:
command:
  - --gpu-memory-utilization
  - "0.95"  # Increase from 0.90
```

### For Lower Memory Usage

```yaml
# In docker-compose.yml, for voice-server:
environment:
  - STT_COMPUTE_TYPE=int8  # Reduces VRAM usage

# For vLLM:
command:
  - --gpu-memory-utilization
  - "0.80"  # Decrease from 0.90
  - --max-model-len
  - "2048"  # Decrease from 4096
```

### For Multiple Kiosks

Run multiple voice-server replicas behind a load balancer:

```bash
# Scale voice-server to 3 replicas
docker compose up -d --scale voice-server=3

# Use nginx or HAProxy for load balancing
```

## Next Steps

1. **Customize Building Knowledge Base**: Add your building's floor plans, facilities, and room information to `building_kb/`
2. **Configure Kiosk Clients**: Set up kiosk hardware with the client application
3. **Monitor Performance**: Set up monitoring and alerting for production
4. **Secure Deployment**: Enable WSS, configure firewalls, use Docker secrets
5. **Backup Strategy**: Set up automated backups for ChromaDB data

## Additional Resources

- Full documentation: `docker-compose.README.md`
- Server configuration: `server/config.py`
- Client configuration: `client/config.py`
- Requirements: `.kiro/specs/voice-kiosk-chatbot/requirements.md`
- Design: `.kiro/specs/voice-kiosk-chatbot/design.md`

## Support

For issues and questions:
1. Check logs: `docker compose logs -f`
2. Check service health: `docker compose ps`
3. Review troubleshooting section above
4. Check GPU status: `nvidia-smi`

## License

See main project LICENSE file.
