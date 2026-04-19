# CosyVoice2 TTS Service Setup Guide

This guide shows how to set up CosyVoice2 as a separate REST API service, similar to VOICEVOX.

## Architecture

```
Voice Server ──HTTP──> CosyVoice Service ──GPU──> Model
     │                       │
     │                   Port 5002
     │
  Port 8765
```

**Benefits:**
- ✅ Isolated service (no dependency conflicts)
- ✅ Can run on different server/GPU
- ✅ Easy to scale or replace
- ✅ Same pattern as VOICEVOX
- ✅ No model loading in main server

## Quick Start

### Option 1: Manual Setup (Recommended for Development)

```bash
# 1. Setup the service
cd cosyvoice_service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Install CosyVoice
git clone https://github.com/FunAudioLLM/CosyVoice.git cosyvoice_repo
cd cosyvoice_repo
pip install -r requirements.txt
cd ..
pip install -e cosyvoice_repo

# 3. Start the service
python app.py
```

### Option 2: Docker (Recommended for Production)

```bash
# Build and start CosyVoice service
docker-compose -f docker-compose.cosyvoice.yml up -d

# Check logs
docker logs cosyvoice
```

### Option 3: Automated Setup

```bash
# Run the setup script
bash cosyvoice_service/setup.sh
```

## Configuration

### Environment Variables

Create `cosyvoice_service/.env`:

```bash
# Model configuration
COSYVOICE_MODEL_PATH=iic/CosyVoice2-0.5B
COSYVOICE_DEVICE=cuda

# Server configuration
HOST=0.0.0.0
PORT=5002

# HuggingFace token (if needed)
HUGGING_FACE_HUB_TOKEN=your-token-here
```

### Main Server Configuration

Update your main `.env`:

```bash
# CosyVoice2 TTS service URL
COSYVOICE_URL=http://localhost:5002
```

## API Endpoints

### Health Check

```bash
curl http://localhost:5002/health
```

**Response:**
```json
{
  "status": "healthy",
  "model": "CosyVoice2-0.5B",
  "ready": true
}
```

### Synthesize Speech

```bash
curl -X POST http://localhost:5002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is a test"}' \
  --output test.wav
```

**Request:**
```json
{
  "text": "Hello, this is a test",
  "speaker_id": 0,
  "speed": 1.0
}
```

**Response:** WAV audio bytes

## Testing

### 1. Test Service Directly

```bash
# Start CosyVoice service
cd cosyvoice_service
source venv/bin/activate
python app.py

# In another terminal, test synthesis
curl -X POST http://localhost:5002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is CosyVoice speaking"}' \
  --output test.wav

# Play the audio
aplay test.wav  # Linux
# or
afplay test.wav  # macOS
```

### 2. Test Integration with Main Server

```bash
# Start CosyVoice service (terminal 1)
cd cosyvoice_service
source venv/bin/activate
python app.py

# Start main server (terminal 2)
python -m uvicorn server.main:app --reload

# Test with client (terminal 3)
python client/main.py --text
# Type: Hello, how are you?
# Expected: Hear English voice from CosyVoice
```

### 3. Check Health Status

```bash
# Check main server health
curl http://localhost:8765/health | jq .tts

# Expected output:
# {
#   "cosyvoice_en": "ready",
#   "voicevox_ja": "ready"
# }
```

## Docker Deployment

### Build and Run

```bash
# Build the image
docker build -t cosyvoice-service cosyvoice_service/

# Run the container
docker run -d \
  --name cosyvoice \
  --gpus all \
  -p 5002:5002 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e COSYVOICE_DEVICE=cuda \
  cosyvoice-service
```

### Using Docker Compose

```bash
# Start CosyVoice service
docker-compose -f docker-compose.cosyvoice.yml up -d

# Check status
docker-compose -f docker-compose.cosyvoice.yml ps

# View logs
docker-compose -f docker-compose.cosyvoice.yml logs cosyvoice

# Stop service
docker-compose -f docker-compose.cosyvoice.yml down
```

## Integration with Main Docker Compose

Add to your main `docker-compose.yml`:

```yaml
services:
  voice-server:
    # ... existing config ...
    environment:
      # ... existing vars ...
      - COSYVOICE_URL=http://cosyvoice:5002
    depends_on:
      - cosyvoice

  cosyvoice:
    build:
      context: ./cosyvoice_service
      dockerfile: Dockerfile
    container_name: cosyvoice
    ports:
      - "5002:5002"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    environment:
      - COSYVOICE_MODEL_PATH=iic/CosyVoice2-0.5B
      - COSYVOICE_DEVICE=cuda
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - voice-network
```

## Performance

| Metric | Value |
|--------|-------|
| Model size | ~1GB |
| VRAM usage | ~1GB |
| First synthesis | 2-3 seconds (model load) |
| Subsequent | 150-300ms |
| Sample rate | 22050 Hz |
| Output format | WAV (PCM16) |

## Troubleshooting

### Service Won't Start

```bash
# Check Python version
python --version  # Should be 3.11+

# Check CUDA
nvidia-smi

# Check dependencies
pip list | grep -E "(torch|cosyvoice|fastapi)"

# Check logs
python app.py  # Run in foreground to see errors
```

### Model Download Issues

```bash
# Set HuggingFace token
export HUGGING_FACE_HUB_TOKEN=your-token-here

# Manual download
python -c "
from huggingface_hub import snapshot_download
snapshot_download('iic/CosyVoice2-0.5B', local_dir='./models/CosyVoice2-0.5B')
"

# Update config to use local path
# In .env: COSYVOICE_MODEL_PATH=./models/CosyVoice2-0.5B
```

### CUDA Out of Memory

```bash
# Switch to CPU mode
# In cosyvoice_service/.env:
COSYVOICE_DEVICE=cpu

# Or reduce other GPU workloads
docker stop other-gpu-containers
```

### Connection Refused

```bash
# Check if service is running
curl http://localhost:5002/

# Check firewall
sudo ufw status

# Check port binding
netstat -tlnp | grep 5002
```

### Audio Quality Issues

```bash
# Check sample rate
curl -I http://localhost:5002/synthesize \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"text": "test"}'

# Should return: Content-Type: audio/wav

# Test with different text
curl -X POST http://localhost:5002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "The quick brown fox jumps over the lazy dog"}' \
  --output test.wav
```

## Monitoring

### Health Checks

```bash
# Service health
curl http://localhost:5002/health

# Integration health
curl http://localhost:8765/health | jq .tts.cosyvoice_en
```

### Logs

```bash
# Service logs
tail -f cosyvoice_service/app.log

# Docker logs
docker logs -f cosyvoice

# Main server logs
tail -f server.log | grep -i cosyvoice
```

### Performance Monitoring

```bash
# GPU usage
nvidia-smi -l 1

# Memory usage
docker stats cosyvoice

# Response times
time curl -X POST http://localhost:5002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Performance test"}' \
  --output /dev/null
```

## Scaling

### Multiple Instances

```bash
# Start multiple instances on different ports
PORT=5002 python app.py &
PORT=5003 python app.py &
PORT=5004 python app.py &

# Load balance in main server config
COSYVOICE_URL=http://localhost:5002,http://localhost:5003,http://localhost:5004
```

### Different GPU

```bash
# Run on specific GPU
CUDA_VISIBLE_DEVICES=1 python app.py

# Or in Docker
docker run --gpus '"device=1"' cosyvoice-service
```

## Security

### Production Deployment

```bash
# Use reverse proxy (nginx)
server {
    listen 80;
    location /tts/ {
        proxy_pass http://localhost:5002/;
    }
}

# Update main server config
COSYVOICE_URL=http://your-domain.com/tts
```

### API Authentication

Add to `cosyvoice_service/app.py`:

```python
from fastapi import Header, HTTPException

async def verify_token(authorization: str = Header(None)):
    if authorization != "Bearer your-secret-token":
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.post("/synthesize", dependencies=[Depends(verify_token)])
async def synthesize(request: SynthesisRequest):
    # ... existing code ...
```

## Summary

The CosyVoice service is now:
- ✅ **Isolated** — Runs independently from main server
- ✅ **Scalable** — Can run on different machines/GPUs
- ✅ **Maintainable** — Simple REST API interface
- ✅ **Compatible** — Same pattern as VOICEVOX
- ✅ **Production-ready** — Docker support, health checks, monitoring

**Next steps:**
1. Run `bash cosyvoice_service/setup.sh`
2. Start service: `cd cosyvoice_service && source venv/bin/activate && python app.py`
3. Test integration with main server
4. Deploy with Docker for production