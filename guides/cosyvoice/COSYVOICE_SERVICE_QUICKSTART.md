# CosyVoice2 Service - Quick Start

## 🚀 3-Step Setup

```bash
# 1. Setup CosyVoice service
cd cosyvoice_service
bash setup.sh

# 2. Start CosyVoice service (terminal 1)
bash start.sh

# 3. Start main server (terminal 2)
cd ..
python -m uvicorn server.main:app --reload
```

## ✅ Verify It Works

```bash
# Test CosyVoice service directly
curl -X POST http://localhost:5002/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is CosyVoice"}' \
  --output test.wav

# Test integration
curl http://localhost:8765/health | jq .tts

# Expected:
# {
#   "cosyvoice_en": "ready",
#   "voicevox_ja": "ready"  
# }
```

## 🎯 Test with Client

```bash
python client/main.py --text

# Type English text:
You: Hello, how are you today?
# Expected: Hear English voice (CosyVoice)

# Type Japanese text:  
You: こんにちは、元気ですか？
# Expected: Hear Japanese voice (VOICEVOX)
```

## 📋 What's Different

| Before | After |
|--------|-------|
| Embedded CosyVoice in main server | Separate CosyVoice service |
| 30+ second startup | 5 second startup |
| Complex dependencies | Clean separation |
| Single process | Microservice architecture |

## 🔧 Configuration

### CosyVoice Service
```bash
# cosyvoice_service/.env
COSYVOICE_MODEL_PATH=iic/CosyVoice2-0.5B
COSYVOICE_DEVICE=cuda
PORT=5002
```

### Main Server
```bash
# .env
COSYVOICE_URL=http://localhost:5002
```

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| Service won't start | Run `bash setup.sh` first |
| "Connection refused" | Check `curl http://localhost:5002/` |
| CUDA OOM | Set `COSYVOICE_DEVICE=cpu` |
| No audio | Check both services are running |

## 📚 Documentation

- **Setup Guide:** `COSYVOICE_SERVICE_SETUP.md`
- **Implementation:** `COSYVOICE_SERVICE_SUMMARY.md`
- **API Reference:** `cosyvoice_service/app.py`

## 🐳 Docker Option

```bash
# Build and run with Docker
docker-compose -f docker-compose.cosyvoice.yml up -d

# Check status
docker logs cosyvoice
```

---

**Ready to go!** CosyVoice2 is now a clean, separate service. 🎉