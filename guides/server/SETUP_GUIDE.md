# Voice Kiosk Chatbot — Complete Setup Guide
### From Zero to Running on WSL2 (Windows)

---

## Before You Start — Read This

You have **WSL2 Ubuntu** on Windows. This means:
- Your Ubuntu terminal is a real Linux environment inside Windows
- Files on Windows are at `/mnt/c/Users/YourName/...` inside Ubuntu
- Docker will run inside WSL2 and be accessible from Windows too
- Your Windows microphone and speakers **can** be used by the client

This guide goes from absolute zero to a fully running system. Follow every step in order. Do not skip anything.

---

## What You Will Install

| What | Why | Where |
|------|-----|-------|
| Docker Desktop | Runs all AI services in containers | Windows |
| Python 3.11 | Runs the client app | WSL2 Ubuntu |
| pip packages | Python libraries for client | WSL2 Ubuntu |
| Ollama model (4GB) | The LLM brain (Qwen2.5-7B) | Docker container |
| Whisper model (~1.5GB) | Speech recognition | Auto-downloaded on first run |
| E5 embeddings (~2GB) | Knowledge base search | Auto-downloaded on first run |
| VOICEVOX | Japanese text-to-speech | Docker container |
| SearXNG | Web search | Docker container |

**Total disk space needed: ~15GB**

---

## PHASE 1 — Windows Setup

### Step 1.1 — Check Your WSL2 Version

Open **PowerShell** (search "PowerShell" in Start menu) and run:

```powershell
wsl --version
```

You need to see `WSL version: 2.x.x`. If you see version 1 or an error, run:

```powershell
wsl --update
wsl --set-default-version 2
```

Then close PowerShell.

---

### Step 1.2 — Install Docker Desktop

1. Go to **https://www.docker.com/products/docker-desktop/**
2. Click **"Download for Windows — AMD64"**
3. Run the downloaded `.exe` installer
4. During install, make sure **"Use WSL 2 instead of Hyper-V"** is checked ✅
5. Click Install, then **Restart your computer** when asked

After restart:
- Open **Docker Desktop** from the Start menu
- Wait until the bottom-left says **"Engine running"** (green dot)
- It may take 1-2 minutes on first launch

---

### Step 1.3 — Enable Docker in WSL2

In Docker Desktop:
1. Click the **gear icon** (Settings) in the top right
2. Go to **Resources → WSL Integration**
3. Turn on the toggle next to your Ubuntu distro ✅
4. Click **"Apply & Restart"**

---

### Step 1.4 — Verify Docker Works in Ubuntu

Open your **Ubuntu terminal** and type:

```bash
docker --version
```

Expected output: `Docker version 24.x.x, build ...`

```bash
docker compose version
```

Expected output: `Docker Compose version v2.x.x`

If both work, move on. If not, restart Docker Desktop and try again.

---

## PHASE 2 — Get the Project Into WSL2

### Step 2.1 — Find Where Your Project Is

Your project files are on Windows. In Ubuntu, Windows drives are at `/mnt/c/`.

If your project is at `C:\Users\John\voice-kiosk-chatbot`, in Ubuntu it's at:
```
/mnt/c/Users/John/voice-kiosk-chatbot
```

Open Ubuntu terminal and navigate there:

```bash
cd /mnt/c/Users/YOUR_WINDOWS_USERNAME/voice-kiosk-chatbot
```

> Replace `YOUR_WINDOWS_USERNAME` with your actual Windows username.
> Tip: Type `cd /mnt/c/Users/` then press **Tab** to see your username.

Confirm you're in the right place:

```bash
ls
```

You should see: `docker-compose.yml  server/  client/  building_kb/  README.md  ...`

If you see those files, you're in the right directory. **Every command from here on is run from this folder.**

---

### Step 2.2 — Copy the Project Into WSL2 (Recommended for Performance)

Running Docker from `/mnt/c/` is slow because it crosses the Windows/Linux boundary. Copy the project into WSL2's own filesystem for much better performance:

```bash
cp -r /mnt/c/Users/YOUR_WINDOWS_USERNAME/voice-kiosk-chatbot ~/voice-kiosk-chatbot
cd ~/voice-kiosk-chatbot
```

Now you're working from `~/voice-kiosk-chatbot` inside WSL2. All future commands run from here.

---

## PHASE 3 — Check Your GPU

### Step 3.1 — Do You Have an NVIDIA GPU?

In Ubuntu terminal:

```bash
nvidia-smi
```

**If you see a table** with your GPU name, memory, etc. → You have a GPU. Go to Step 3.2.

**If you get "command not found"** → No NVIDIA GPU detected. Go to the **"No GPU Setup"** section at the end of this guide, then come back to Phase 4.

---

### Step 3.2 — Install NVIDIA Container Toolkit (GPU users only)

This lets Docker containers use your GPU. Run these commands one at a time:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
```

```bash
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
```

```bash
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
```

```bash
sudo nvidia-ctk runtime configure --runtime=docker
```

Now restart Docker Desktop from Windows (right-click the Docker icon in the taskbar → Restart).

Wait 30 seconds, then test:

```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

You should see your GPU listed inside the container output. If yes, GPU is ready.

---

## PHASE 4 — Configure the Project

### Step 4.1 — Create the .env File

```bash
cp .env.example .env
```

Now open it:

```bash
nano .env
```

You'll see a text editor. Use arrow keys to navigate. Here is **exactly what to change**:

---

**Find this line and change the value:**
```
SEARXNG_SECRET=changeme-random-secret-key
```
Change to any random string, like:
```
SEARXNG_SECRET=myvoicekiosk2024secret
```

---

**Find this line — set your building name:**
```
BUILDING_NAME=Office Building
```
Change to whatever you want, e.g.:
```
BUILDING_NAME=Test Building
```

---

**Find this line — set your GPU VRAM:**
```
STT_COMPUTE_TYPE=float16
```

- If your GPU has **12GB or more VRAM** → leave as `float16`
- If your GPU has **less than 12GB VRAM** → change to `int8`
- If you have **no GPU** → change to `int8`

---

**Grok API (optional cloud fallback):**
```
GROK_API_KEY=your-grok-api-key-here
```
If you don't have a Grok API key, change to:
```
GROK_API_KEY=
```
(leave it blank — the system will use Ollama instead)

---

**Leave everything else as-is for now.**

Save and exit: Press `Ctrl+X`, then `Y`, then `Enter`.

---

### Step 4.2 — Create Required Directories

```bash
mkdir -p models chroma_data searxng
```

---

### Step 4.3 — Create SearXNG Config

SearXNG needs a settings file or it won't start:

```bash
cat > searxng/settings.yml << 'EOF'
use_default_settings: true
server:
  secret_key: "myvoicekiosk2024secret"
  bind_address: "0.0.0.0:8080"
  base_url: "http://localhost:8080/"
search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
ui:
  static_use_hash: true
EOF
```

---

### Step 4.4 — Adjust docker-compose.yml for Your Setup

The default `docker-compose.yml` is configured for a GPU. You need to adjust it based on your hardware.

#### If you have NO GPU:

Open the file:
```bash
nano docker-compose.yml
```

You need to **remove** the GPU sections. They look like this and appear **3 times** (for `voice-server`, `vllm`, and `ollama`):

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Delete all three of those blocks. Also find the vLLM command section and change `float16` to `float32`:

Find:
```yaml
      - --dtype
      - float16
```
Change to:
```yaml
      - --dtype
      - float32
```

Save: `Ctrl+X`, `Y`, `Enter`.

#### If you have a GPU:

No changes needed. The file is already configured for GPU.

---

## PHASE 5 — Install Python for the Client

The client (the UI with microphone and speakers) runs directly in WSL2, not in Docker.

### Step 5.1 — Install Python 3.11

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-pip python3.11-dev
```

Verify:
```bash
python3.11 --version
```
Expected: `Python 3.11.x`

---

### Step 5.2 — Install Audio System Libraries

The client needs audio libraries to use your microphone and speakers:

```bash
sudo apt-get install -y \
  portaudio19-dev \
  libsndfile1 \
  ffmpeg \
  pulseaudio \
  libpulse-dev \
  libasound2-dev \
  python3-pyqt6 \
  libxcb-xinerama0 \
  libxcb-cursor0
```

---

### Step 5.3 — Create a Python Virtual Environment for the Client

A virtual environment keeps the client's packages separate from the system:

```bash
cd ~/voice-kiosk-chatbot
python3.11 -m venv client_env
```

Activate it:
```bash
source client_env/bin/activate
```

Your terminal prompt will now show `(client_env)` at the start. This means the virtual environment is active.

---

### Step 5.4 — Install Client Python Packages

```bash
pip install --upgrade pip
pip install -r client/requirements.txt
```

This installs: PyQt6, sounddevice, torch, websockets, numpy, python-dotenv.

It will take a few minutes. You'll see packages downloading and installing.

---

### Step 5.5 — Install Server Python Packages (for running ingest script locally)

```bash
pip install -r server/requirements.txt
```

This installs: fastapi, faster-whisper, chromadb, sentence-transformers, openai, etc.

This will take several minutes — these are large AI packages.

---

## PHASE 6 — Start the Docker Services

Now we start the AI backend services. Make sure Docker Desktop is running on Windows.

### Step 6.1 — Start Ollama First

Ollama is the LLM service. Start it first because it needs time to initialize:

```bash
docker compose up -d ollama
```

Check it started:
```bash
docker compose logs ollama
```

Wait until you see: `Listening on [::]:11434`

---

### Step 6.2 — Download the LLM Model into Ollama

This downloads the Qwen2.5-7B language model (~4GB). It will take several minutes depending on your internet speed:

```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

You'll see a progress bar. Wait for it to complete:
```
pulling manifest
pulling qwen2.5:7b-instruct... ████████████ 100%
success
```

Verify the model is ready:
```bash
docker compose exec ollama ollama list
```

You should see `qwen2.5:7b-instruct` in the list.

---

### Step 6.3 — Start VOICEVOX (Japanese TTS)

```bash
docker compose up -d voicevox
```

Wait about 30 seconds, then test:
```bash
curl http://localhost:50021/version
```

Expected output: `"0.14.x"` (a version number in quotes)

If you get a connection error, wait another 30 seconds and try again.

---

### Step 6.4 — Start SearXNG (Web Search)

```bash
docker compose up -d searxng
```

Test it:
```bash
curl -s http://localhost:8080/ | head -5
```

You should see some HTML output starting with `<!DOCTYPE html>`.

---

### Step 6.5 — Build and Start the Voice Server

This step builds the Docker image for the main AI server. It will take 5-10 minutes the first time (it downloads the base image and installs Python packages):

```bash
docker compose up -d --build voice-server
```

Watch the build progress:
```bash
docker compose logs -f voice-server
```

Wait until you see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8765
```

Press `Ctrl+C` to stop watching logs (the server keeps running).

---

### Step 6.6 — Verify the Voice Server is Healthy

```bash
curl http://localhost:8000/health
```

Expected output:
```json
{"status":"healthy","service":"voice-kiosk-chatbot","version":"1.0.0","config":{"building_name":"Test Building","stt_model":"large-v3-turbo","tts_en_engine":"cosyvoice2"}}
```

If you see `"status":"healthy"` — the server is running correctly.

---

### Step 6.7 — Check All Services Are Running

```bash
docker compose ps
```

You should see something like:

```
NAME            IMAGE                    STATUS
voice-server    voice-kiosk-chatbot...   running (healthy)
ollama          ollama/ollama:latest     running
voicevox        voicevox/voicevox...     running (healthy)
searxng         searxng/searxng:latest   running
```

All services should show `running`. The `voice-server` and `voicevox` should show `(healthy)`.

> **Note:** vLLM is not started yet — it requires a lot of GPU memory. Ollama handles LLM inference for now.

---

## PHASE 7 — Load the Knowledge Base

The AI needs to know about your building. We load the sample documents into ChromaDB.

### Step 7.1 — Run the Ingestion Script

Make sure your virtual environment is active (you should see `(client_env)` in your prompt). If not:
```bash
source client_env/bin/activate
```

Run the ingestion:
```bash
python3 server/rag/ingest.py --kb-path building_kb --chroma-path ./chroma_data
```

Expected output:
```
INFO - Starting ingestion from building_kb to ./chroma_data
INFO - Processing: building_kb/floors/floor_01.md
INFO - Processing: building_kb/floors/floor_02.md
INFO - Processing: building_kb/facilities/elevators.md
...
INFO - Ingesting 12 total chunks into ChromaDB...
INFO - Ingestion complete!
```

---

## PHASE 8 — Test the Server (No Microphone Needed)

Before running the full client, let's verify the server responds correctly using a text-only test.

### Step 8.1 — Install the WebSocket Test Tool

```bash
sudo apt-get install -y nodejs npm
sudo npm install -g wscat
```

---

### Step 8.2 — Connect and Send a Test Message

```bash
wscat -c ws://localhost:8765/ws
```

You'll see: `Connected (press CTRL+C to quit)`

Now type this exactly and press Enter:
```json
{"type": "session_start", "kiosk_id": "test-01", "kiosk_location": "Floor 1 Lobby"}
```

You should receive back:
```json
{"type": "status", "state": "listening"}
```

Now send a question:
```json
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "en"}
```

You should see the server streaming back responses like:
```json
{"type": "transcript", "text": "Where is the cafeteria?", "lang": "en", "final": true}
{"type": "llm_text_chunk", "text": "The cafeteria ", "final": false}
{"type": "llm_text_chunk", "text": "is located on ", "final": false}
...
```

This confirms the full pipeline is working: text input → RAG → LLM → response.

Press `Ctrl+C` to disconnect.

---

## PHASE 9 — Run the Full Client (With Microphone + UI)

### Step 9.1 — Set Up Audio in WSL2

WSL2 doesn't have audio by default. You need PulseAudio running:

```bash
# Start PulseAudio
pulseaudio --start --log-target=syslog

# Check it's running
pulseaudio --check && echo "PulseAudio is running"
```

If PulseAudio fails to start, try:
```bash
pulseaudio --kill
pulseaudio --start
```

---

### Step 9.2 — Set the Display Variable

The PyQt6 UI needs to know where to show the window:

```bash
export DISPLAY=:0
```

> **Note for WSL2:** If the UI doesn't appear, you may need to install an X server on Windows like **VcXsrv** or use **WSLg** (available in Windows 11). See the troubleshooting section.

---

### Step 9.3 — Set Environment Variables for the Client

```bash
export SERVER_WS_URL=ws://localhost:8765/ws
export KIOSK_ID=kiosk-01
export KIOSK_LOCATION="Floor 1 Lobby"
```

---

### Step 9.4 — Run the Client

Make sure your virtual environment is active:
```bash
source client_env/bin/activate
```

Run the client:
```bash
python3 client/main.py
```

A fullscreen window should appear. You can:
- **Speak** into your microphone — the system will transcribe and respond
- **Type** a question and press Enter
- **Interrupt** the system while it's speaking by speaking again

---

## PHASE 10 — Daily Usage (After First Setup)

Once everything is set up, here's how to start the system each day:

### Start the Server (run once per session)

```bash
cd ~/voice-kiosk-chatbot
docker compose up -d
```

Wait about 60 seconds for everything to initialize, then check:
```bash
curl http://localhost:8000/health
```

### Run the Client

```bash
cd ~/voice-kiosk-chatbot
source client_env/bin/activate
export SERVER_WS_URL=ws://localhost:8765/ws
export KIOSK_ID=kiosk-01
export KIOSK_LOCATION="Floor 1 Lobby"
python3 client/main.py
```

### Stop the Server

```bash
docker compose down
```

---

## Troubleshooting

### "docker: command not found" in Ubuntu

Docker Desktop WSL integration isn't enabled.
1. Open Docker Desktop on Windows
2. Settings → Resources → WSL Integration
3. Enable for your Ubuntu distro
4. Apply & Restart

---

### Voice server crashes on startup

Check the logs:
```bash
docker compose logs voice-server
```

**Common cause 1:** Can't connect to Ollama
- Make sure Ollama started first: `docker compose up -d ollama`
- Make sure the model was pulled: `docker compose exec ollama ollama list`

**Common cause 2:** CUDA/GPU error
- Try removing GPU sections from `docker-compose.yml` (see Phase 4.4)
- Or change `STT_COMPUTE_TYPE=int8` in `.env`

---

### "CUDA out of memory" error

Your GPU doesn't have enough VRAM. Edit `.env`:
```
STT_COMPUTE_TYPE=int8
```

And in `docker-compose.yml`, reduce vLLM memory (if using vLLM):
```yaml
- --gpu-memory-utilization
- "0.70"
```

Then restart:
```bash
docker compose restart voice-server
```

---

### No audio / microphone not working

```bash
# List available audio devices
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

If you see devices listed, audio is working. If not:
```bash
sudo apt-get install -y pulseaudio
pulseaudio --start
```

---

### PyQt6 window doesn't appear (WSL2 display issue)

**Windows 11 users:** WSLg is built-in. Just run:
```bash
export DISPLAY=:0
python3 client/main.py
```

**Windows 10 users:** Install VcXsrv:
1. Download from: https://sourceforge.net/projects/vcxsrv/
2. Run XLaunch → Multiple windows → Start no client → Disable access control ✅
3. In Ubuntu: `export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0`
4. Then run the client

---

### Ollama model download is very slow

This is normal — the model is 4GB. You can check progress:
```bash
docker compose logs -f ollama
```

If it gets stuck, cancel with `Ctrl+C` and retry:
```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

---

### Port already in use

```bash
# Find what's using port 8765
sudo lsof -i :8765

# Kill it (replace PID with the number shown)
sudo kill -9 PID
```

---

### Reset Everything and Start Fresh

```bash
# Stop and remove all containers and data
docker compose down -v

# Remove ChromaDB data
rm -rf chroma_data/*

# Start fresh
docker compose up -d
```

---

## No GPU Setup (CPU-Only Mode)

If you don't have an NVIDIA GPU, the system still works but will be slower.

### Changes to docker-compose.yml

Open `docker-compose.yml` and remove all three `deploy:` blocks (they appear for `voice-server`, `vllm`, and `ollama`).

Also, **comment out the entire vLLM service** by adding `#` at the start of every line in the `vllm:` section. The system will skip vLLM and use Ollama directly.

### Changes to .env

```
STT_MODEL=base
STT_COMPUTE_TYPE=int8
```

Using the `base` Whisper model instead of `large-v3-turbo` is much faster on CPU.

### Expected Performance Without GPU

| Operation | With GPU | Without GPU |
|-----------|----------|-------------|
| Speech recognition | ~150ms | ~3-5 seconds |
| LLM first response | ~200ms | ~15-30 seconds |
| Text-to-speech | ~150ms | ~2-3 seconds |
| Total response time | ~600ms | ~20-40 seconds |

The system is fully functional, just slower.

---

## Service Ports Reference

| Service | Port | URL | What it does |
|---------|------|-----|-------------|
| Voice Server (WebSocket) | 8765 | `ws://localhost:8765/ws` | Main AI pipeline |
| Voice Server (HTTP) | 8000 | http://localhost:8000/health | Health check |
| Ollama | 11434 | http://localhost:11434 | LLM API |
| VOICEVOX | 50021 | http://localhost:50021 | Japanese TTS |
| SearXNG | 8080 | http://localhost:8080 | Web search UI |

You can open http://localhost:8080 in your **Windows browser** to see SearXNG working.
You can open http://localhost:50021/docs in your **Windows browser** to see VOICEVOX API docs.

---

## Environment Variables Reference

All variables live in your `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_SECRET` | `changeme` | Secret key for SearXNG — change this |
| `BUILDING_NAME` | `Office Building` | Your building name shown in responses |
| `STT_MODEL` | `large-v3-turbo` | Whisper model size (`base` for CPU) |
| `STT_COMPUTE_TYPE` | `float16` | `float16` for GPU ≥12GB, `int8` for less |
| `OLLAMA_MODEL_NAME` | `qwen2.5:7b-instruct` | LLM model name |
| `GROK_API_KEY` | *(empty)* | Optional cloud LLM fallback |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail, `ERROR` for less |
| `SERVER_WS_URL` | `ws://localhost:8765/ws` | Client uses this to connect |
| `KIOSK_ID` | `kiosk-01` | Identifier for this kiosk |
| `KIOSK_LOCATION` | `Floor 1 Lobby` | Physical location shown in responses |

---

## Quick Command Reference

```bash
# Navigate to project
cd ~/voice-kiosk-chatbot

# Start all services
docker compose up -d

# Check all services are running
docker compose ps

# Check server health
curl http://localhost:8000/health

# Watch server logs live
docker compose logs -f voice-server

# Test with WebSocket
wscat -c ws://localhost:8765/ws

# Reload knowledge base
source client_env/bin/activate
python3 server/rag/ingest.py --kb-path building_kb --chroma-path ./chroma_data

# Run the client UI
source client_env/bin/activate
python3 client/main.py

# Stop all services
docker compose down

# Restart one service
docker compose restart voice-server
```
