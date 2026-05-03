# Running the Voice Kiosk Chatbot on Windows (WSL)

This guide assumes you have **zero Linux or Docker experience**. We'll go step by step.

---

## What Is WSL?

WSL (Windows Subsystem for Linux) is the Ubuntu terminal app you already have. It lets you run Linux commands inside Windows. Think of it as a mini Linux computer living inside your Windows machine.

---

## What We're Setting Up

The system has two parts:

| Part | What it does | Where it runs |
|------|-------------|---------------|
| **Server** | AI processing — speech recognition, LLM, text-to-speech | Inside Docker containers (WSL) |
| **Client** | The kiosk UI — microphone, speakers, chat window | Python on your machine |

For testing, we'll run the **server via Docker** and test it using a simple WebSocket tool — no need to run the full client UI yet.

---

## Step 1 — Check Your WSL Version

Open your Ubuntu terminal and type:

```bash
wsl --version
```

If that doesn't work, open **PowerShell** (not Ubuntu) and type:

```bash
wsl -l -v
```

You want to see `VERSION 2` next to Ubuntu. If it says `1`, run this in PowerShell:

```bash
wsl --set-default-version 2
wsl --set-version Ubuntu 2
```

---

## Step 2 — Install Docker Desktop on Windows

Docker is the tool that runs all the AI services (LLM, speech recognition, etc.) in isolated containers. You install it on **Windows**, not inside Ubuntu.

1. Go to: **https://www.docker.com/products/docker-desktop/**
2. Click **"Download for Windows"**
3. Run the installer — accept all defaults
4. When asked about WSL 2 backend, **check that box** ✅
5. Restart your computer when prompted

After restart, open Docker Desktop from the Start menu. Wait for it to say **"Engine running"** in the bottom left.

**Verify it works** — open your Ubuntu terminal and type:

```bash
docker --version
```

You should see something like: `Docker version 24.x.x`

```bash
docker compose version
```

You should see: `Docker Compose version v2.x.x`

If both work, Docker is ready.

---

## Step 3 — Check If You Have a GPU (Important)

The AI models need a GPU to run at full speed. Open Ubuntu terminal and type:

```bash
nvidia-smi
```

**If you see a table with your GPU name** → you have a compatible NVIDIA GPU. Continue to Step 3a.

**If you get "command not found"** → you either have no NVIDIA GPU, or it's not set up. Skip to the **"No GPU / CPU-only mode"** section at the bottom.

### Step 3a — Enable GPU in Docker (only if you have NVIDIA GPU)

In your Ubuntu terminal, run these commands one by one. Copy and paste each line:

```bash
# Add NVIDIA package repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
```

```bash
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
```

```bash
# Install the toolkit
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
```

```bash
# Configure Docker to use GPU
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

**Test it works:**

```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

You should see your GPU listed. If yes, GPU is ready.

---

## Step 4 — Navigate to the Project Folder

In your Ubuntu terminal, you need to go to where this project lives. Your Windows files are accessible from WSL under `/mnt/c/`.

For example, if the project is at `C:\Users\YourName\voice-kiosk-chatbot`, type:

```bash
cd /mnt/c/Users/YourName/voice-kiosk-chatbot
```

> **Tip:** Type `cd /mnt/c/Users/` then press **Tab** to autocomplete your username.

Confirm you're in the right place:

```bash
ls
```

You should see files like `docker-compose.yml`, `server/`, `client/`, `README.md`, etc.

---

## Step 5 — Create Your Configuration File

The project needs a `.env` file with settings. We'll create one from the example:

```bash
cp .env.example .env
```

Now open it to edit:

```bash
nano .env
```

You'll see a text editor in the terminal. Here's what to change:

### Minimum Required Changes

Find these lines and update them:

```bash
# Change this — pick a random word as your secret
SEARXNG_SECRET=my-random-secret-word-123

# If you have a Grok API key (optional — leave blank if not)
GROK_API_KEY=

# Your building name (can be anything)
BUILDING_NAME=My Office Building
```

### If You Have a GPU — Also Change:

```bash
# Keep as-is for GPU with 12GB+ VRAM
STT_COMPUTE_TYPE=float16

# If your GPU has less than 12GB VRAM, change to:
STT_COMPUTE_TYPE=int8
```

### If You Have NO GPU — Change:

```bash
# Use smaller/CPU-friendly model
STT_MODEL=base
STT_COMPUTE_TYPE=int8
```

**Save and exit nano:** Press `Ctrl+X`, then `Y`, then `Enter`.

---

## Step 6 — Update docker-compose.yml for Your Setup

The default `docker-compose.yml` requires a GPU. If you **don't have a GPU**, you need to remove the GPU sections.

### If you have NO GPU:

```bash
nano docker-compose.yml
```

Find and **delete** these blocks (they appear 3 times — for `voice-server`, `vllm`, and `ollama`):

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Also change the vLLM command to not use GPU:

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

Save with `Ctrl+X`, `Y`, `Enter`.

---

## Step 7 — Create Required Directories

```bash
mkdir -p models chroma_data searxng
```

---

## Step 8 — Configure SearXNG

SearXNG (the web search service) needs a config file:

```bash
# Create the config directory
mkdir -p searxng

# Create a minimal settings file
cat > searxng/settings.yml << 'EOF'
use_default_settings: true
server:
  secret_key: "changeme-replace-with-your-secret"
  bind_address: "0.0.0.0:8080"
search:
  safe_search: 0
  autocomplete: ""
EOF
```

---

## Step 9 — Start the Services

Now we start everything. This will download Docker images (about 5-10GB total) on first run — it will take a while depending on your internet speed.

### Option A: Start Everything at Once

```bash
docker compose up -d
```

The `-d` means "run in background". You'll see Docker pulling images and starting containers.

### Option B: Start Services One by One (Recommended for First Time)

This lets you see if each service starts correctly before moving on.

**Start Ollama first** (the LLM that works on CPU too):

```bash
docker compose up -d ollama
```

Wait 30 seconds, then check it's running:

```bash
docker compose logs ollama
```

You should see: `Listening on [::]:11434`

**Pull the AI model into Ollama** (this downloads ~4GB — takes a few minutes):

```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

You'll see a progress bar. Wait for it to finish.

**Start VOICEVOX** (Japanese text-to-speech):

```bash
docker compose up -d voicevox
```

Wait 30 seconds, then test it:

```bash
curl http://localhost:50021/version
```

You should see a version number like `"0.14.x"`.

**Start SearXNG** (web search):

```bash
docker compose up -d searxng
```

Test it:

```bash
curl http://localhost:8080/
```

You should see some HTML output.

**Start the Voice Server** (the main AI pipeline):

```bash
docker compose up -d voice-server
```

Watch the logs to see it start up:

```bash
docker compose logs -f voice-server
```

Wait until you see: `Application startup complete`

Press `Ctrl+C` to stop watching logs (the server keeps running).

**Check the health endpoint:**

```bash
curl http://localhost:8000/health
```

You should see:

```json
{"status": "healthy", "service": "voice-kiosk-chatbot", "version": "1.0.0"}
```

---

## Step 10 — Ingest the Building Knowledge Base

This loads the building documents into the AI's memory (ChromaDB):

```bash
docker compose exec voice-server python server/rag/ingest.py
```

You should see output like:
```
Ingesting documents from building_kb/...
Processed floor_01.md
Processed floor_02.md
...
Ingestion complete. X documents stored.
```

---

## Step 11 — Test the Server

### Check All Services Are Running

```bash
docker compose ps
```

You should see all services with status `running` or `healthy`:

```
NAME            STATUS
voice-server    running
ollama          running
voicevox        running
searxng         running
```

### Test With a Text Message (No Microphone Needed)

Install a WebSocket testing tool:

```bash
# Install Node.js first (if not installed)
sudo apt-get update
sudo apt-get install -y nodejs npm

# Install wscat
sudo npm install -g wscat
```

Connect to the server:

```bash
wscat -c ws://localhost:8765/ws
```

You'll see: `Connected (press CTRL+C to quit)`

Now type these messages one at a time and press Enter after each:

**First, start a session:**
```json
{"type": "session_start", "kiosk_id": "test-01", "kiosk_location": "Floor 1 Lobby"}
```

You should get back:
```json
{"type": "status", "state": "listening"}
```

**Then ask a question:**
```json
{"type": "text_input", "text": "Where is the cafeteria?", "lang": "en"}
```

You should see the server respond with transcript and LLM text chunks streaming back.

Press `Ctrl+C` to disconnect.

---

## Step 12 — View Logs (When Something Goes Wrong)

**See all logs:**
```bash
docker compose logs -f
```

**See only voice-server logs:**
```bash
docker compose logs -f voice-server
```

**See only Ollama logs:**
```bash
docker compose logs -f ollama
```

Press `Ctrl+C` to stop watching.

---

## Stopping and Starting

**Stop all services:**
```bash
docker compose down
```

**Start again later:**
```bash
docker compose up -d
```

**Restart one service:**
```bash
docker compose restart voice-server
```

---

## Service Ports Summary

Once running, these are accessible from your Windows browser too:

| Service | URL | What it is |
|---------|-----|-----------|
| Voice Server (WebSocket) | `ws://localhost:8765/ws` | Main AI pipeline |
| Voice Server (Health) | http://localhost:8000/health | Health check |
| Ollama | http://localhost:11434 | LLM API |
| VOICEVOX | http://localhost:50021 | Japanese TTS |
| SearXNG | http://localhost:8080 | Web search UI |

You can open http://localhost:8080 in your **Windows browser** to see SearXNG working.

---

## No GPU / CPU-Only Mode

If you don't have an NVIDIA GPU, the system still works but will be slower.

**Changes needed in `docker-compose.yml`:**

1. Remove all `deploy: resources: reservations: devices:` blocks
2. For vLLM, add `--device cpu` to the command

**Alternative: Skip vLLM, use only Ollama**

Ollama works well on CPU. Edit `docker-compose.yml` and comment out the entire `vllm:` service block by adding `#` before each line. The system will automatically fall back to Ollama.

**Expected performance without GPU:**
- STT (speech recognition): ~3-5 seconds per utterance
- LLM response: ~10-30 seconds
- TTS: ~2-3 seconds

---

## Common Problems

### "docker: command not found"
Docker Desktop isn't installed or WSL integration isn't enabled.
→ Open Docker Desktop → Settings → Resources → WSL Integration → Enable for your Ubuntu distro

### "permission denied" errors
```bash
sudo chmod 666 /var/run/docker.sock
```

### "port already in use"
Another program is using that port. Find and stop it:
```bash
sudo lsof -i :8765   # Check who's using port 8765
```

### Voice server crashes immediately
Check logs:
```bash
docker compose logs voice-server
```
Most likely cause: can't connect to Ollama. Make sure Ollama started first and the model was pulled.

### "CUDA out of memory"
Your GPU doesn't have enough VRAM. Edit `.env`:
```bash
STT_COMPUTE_TYPE=int8
```
And in `docker-compose.yml`, reduce vLLM memory:
```yaml
- --gpu-memory-utilization
- "0.70"
```

### Ollama model download stuck
```bash
# Check download progress
docker compose logs -f ollama
```
Just wait — 4GB takes time on slow connections.

---

## Quick Reference Card

```bash
# Go to project folder
cd /mnt/c/Users/YourName/voice-kiosk-chatbot

# Start everything
docker compose up -d

# Check status
docker compose ps

# Check health
curl http://localhost:8000/health

# Test with WebSocket
wscat -c ws://localhost:8765/ws

# Watch logs
docker compose logs -f voice-server

# Stop everything
docker compose down
```

---

## What's Next

Once the server is running and responding to WebSocket messages, you can:

1. **Run the Python client** (requires microphone + speakers):
   ```bash
   cd /mnt/c/Users/YourName/voice-kiosk-chatbot
   pip install -r client/requirements.txt
   python3 client/main.py
   ```

2. **Add your own building knowledge** — edit files in `building_kb/` then re-run ingestion

3. **Try the VOICEVOX API** in your browser: http://localhost:50021/docs

4. **Try SearXNG** in your browser: http://localhost:8080
