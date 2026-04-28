# Remote Ubuntu Server Setup Guide

Complete A-Z guide to set up and run the Voice Kiosk Chatbot on a fresh Ubuntu machine.

---

## Overview of What We're Running

| Component | Type | How it runs |
|---|---|---|
| **Ollama** | LLM inference | Docker container (port 11434) |
| **SearXNG** | Web search | Docker container (port 8081) |
| **faster-whisper** | Speech-to-text | In-process, loaded by server |
| **Kokoro TTS** | English TTS | In-process, loaded by server |
| **CosyVoice2** | English TTS fallback | Python venv process (port 5002) |
| **Server app** | FastAPI + WebSocket | Python venv (`venv/`) at project root |
| **Client app** | PyQt6 / headless | Python venv (`client/client-venv/`) |

---

## Part 1 — System Prerequisites

### 1.1 Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.2 Install core system packages

```bash
sudo apt install -y \
    git curl wget build-essential \
    python3 python3-pip python3-venv python3-dev \
    ffmpeg libsndfile1 libsndfile1-dev \
    portaudio19-dev libasound2-dev \
    espeak-ng \
    ca-certificates gnupg lsb-release \
    software-properties-common
```

### 1.3 Install Docker

```bash
# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (avoids needing sudo for docker commands)
sudo usermod -aG docker $USER

# Apply group change without logging out
newgrp docker

# Verify
docker --version
docker compose version
```

### 1.4 Install NVIDIA drivers and CUDA (skip if no GPU)

Check if a GPU is present first:
```bash
lspci | grep -i nvidia
```

If you have an NVIDIA GPU:
```bash
# Install the recommended driver
sudo ubuntu-drivers autoinstall

# Reboot to load the driver
sudo reboot
```

After reboot, verify:
```bash
nvidia-smi
```

### 1.5 Install NVIDIA Container Toolkit (for GPU in Docker)

```bash
# Add NVIDIA Container Toolkit repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit

# Configure Docker to use NVIDIA runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU is accessible inside Docker
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

---

## Part 2 — Clone the Repository

```bash
# Navigate to your home directory (or wherever you want the project)
cd ~

# Clone the project
git clone <your-repository-url> robotic_robo
cd robotic_robo
```

> Replace `<your-repository-url>` with the actual git remote URL.

---

## Part 3 — Environment Configuration

The app reads from `.env.local` (highest priority) then `.env` as fallback. Since `.env.local` is not committed, create it manually:

```bash
nano .env.local
```

Paste and adjust the following (this mirrors your current working config):

```dotenv
HUGGING_FACE_HUB_TOKEN=your_hf_token_here

SEARXNG_SECRET=myvoicekiosk2026secret

LOG_LEVEL=INFO

SERVER_HOST=0.0.0.0
SERVER_PORT=8765

VLLM_BASE_URL=http://localhost:8001/v1
VLLM_MODEL_NAME=disabled

OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL_NAME=qwen2.5:3b-instruct

GROK_API_KEY=

STT_MODEL=large-v3
STT_COMPUTE_TYPE=int8
STT_DEVICE=cuda

TTS_EN_ENGINE=cosyvoice

TTS_JP_URL=http://localhost:10101

COSYVOICE_MODEL_PATH=iic/CosyVoice2-0.5B
COSYVOICE_DEVICE=cuda
COSYVOICE_URL=http://localhost:5002

USE_RAG=true
CHROMADB_PATH=./chroma_data

BUILDING_NAME=OfficeBuilding

SEARXNG_URL=http://localhost:8081

SERVER_WS_URL=ws://localhost:8765/ws

KIOSK_ID=kiosk-01
KIOSK_LOCATION=Floor_1_Lobby

KOKORO_VOICE=af_heart
KOKORO_SPEED=1.1
KOKORO_DEVICE=cuda
KOKORO_LANG=a

KOKORO_JP_VOICE=jf_nezumi
KOKORO_JP_ENABLED=true
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

> **Note on `STT_DEVICE`**: If you have no GPU, change `STT_DEVICE=cpu` and `STT_COMPUTE_TYPE=int8`. Whisper will be slower but functional.

> **Note on `KOKORO_DEVICE`**: Same — use `cpu` if no GPU.

---

## Part 4 — Docker Services (SearXNG + Ollama)

### 4.1 Create required directories

```bash
chmod +x scripts/setup_docker_dirs.sh
./scripts/setup_docker_dirs.sh
```

### 4.2 Start SearXNG and Ollama via Docker Compose

The `docker-compose.yml` includes several services. For your current setup you only need **SearXNG** and **Ollama** from it (CosyVoice runs as a separate venv process, and the server/client run outside Docker).

```bash
docker compose up -d searxng ollama
```

Verify they are running:
```bash
docker compose ps
```

Expected output shows both `searxng` and `ollama` as `running`.

### 4.3 Pull the Ollama model

Wait about 30 seconds for Ollama to fully start, then pull the model:

```bash
docker compose exec ollama ollama pull qwen2.5:3b-instruct
```

This downloads ~2GB. Wait for it to complete.

Verify the model is available:
```bash
docker compose exec ollama ollama list
```

### 4.4 Verify SearXNG

```bash
curl http://localhost:8081/search?q=test&format=json
```

You should get a JSON response with search results.

---

## Part 5 — Server App Virtual Environment

The server runs from the project root using the `venv/` environment.

### 5.1 Create the venv

```bash
# From project root
python3 -m venv venv
source venv/bin/activate
```

### 5.2 Install server dependencies

```bash
pip install --upgrade pip

# Install from the server-specific requirements
pip install -r server/requirements.txt
```

> **Note**: `server/requirements.txt` is the focused list for the server. The `all_requirments.txt` at the root is a full freeze of the dev environment — you do not need to install all of it. The server requirements file covers everything the server needs.

### 5.3 Install the misaki English G2P package (required by Kokoro)

```bash
pip install "misaki[en]"
```

### 5.4 Verify the server can import its modules

```bash
python -c "from server.config import Config; print('Config OK')"
python -c "from faster_whisper import WhisperModel; print('faster-whisper OK')"
python -c "import kokoro; print('kokoro OK')"
```

If any import fails, install the missing package:
```bash
pip install <package-name>
```

---

## Part 6 — CosyVoice2 TTS Service

CosyVoice runs as a separate Python process in its own venv inside `cosyvoice_service/`.

### 6.1 Run the setup script

```bash
cd cosyvoice_service
bash setup.sh
cd ..
```

This will:
- Create `cosyvoice_service/venv/`
- Clone the CosyVoice repo into `cosyvoice_service/cosyvoice_repo/`
- Install all dependencies
- Run a quick smoke test

> This step takes several minutes and requires internet access to clone the repo and download pip packages.

### 6.2 Start the CosyVoice service

Open a dedicated terminal (or use `tmux`/`screen`) and run:

```bash
cd cosyvoice_service
bash start.sh
```

The service starts on `http://localhost:5002`. The first run will download the `iic/CosyVoice2-0.5B` model weights from HuggingFace (~1GB). Subsequent starts are instant.

Verify it is healthy:
```bash
curl http://localhost:5002/health
```

Expected: `{"status": "healthy"}` or similar JSON.

> **Tip**: Use `tmux new -s cosyvoice` before running `start.sh` so it keeps running after you detach. Detach with `Ctrl+B D`.

---

## Part 7 — Run the Server App

### 7.1 Activate the server venv

```bash
cd ~/robotic_robo
source venv/bin/activate
```

### 7.2 Start the server

```bash
python -m uvicorn server.main:app --host 0.0.0.0 --port 8765 --log-level info
```

Or use the built-in entry point:
```bash
python -m server.main
```

On first run, faster-whisper will download the Whisper model weights from HuggingFace (the `large-v3` model is ~3GB). This only happens once; subsequent starts load from cache.

**Expected startup log sequence:**
```
Starting voice chatbot server...
Pre-loading STT (Whisper)...
Pre-loading LLM fallback chain...
Pre-loading RAG knowledge base...
Pre-loading TTS router...
KokoroTTS initialised (English primary)
CosyVoiceTTS initialised (English fallback)
Server ready — host=0.0.0.0, port=8765
```

### 7.3 Verify the server health endpoint

```bash
curl http://localhost:8765/health
```

You should get a JSON response with `"status": "healthy"`.

> **Tip**: Run the server in a `tmux` session: `tmux new -s server`

---

## Part 8 — Client App Virtual Environment

The client runs from `client/` using `client/client-venv/`.

### 8.1 Create the client venv

```bash
cd ~/robotic_robo/client
python3 -m venv client-venv
source client-venv/bin/activate
```

### 8.2 Install client dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 8.3 Install PyQt6 system dependencies (for UI mode)

```bash
sudo apt install -y \
    libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-xkb1 libxkbcommon-x11-0 \
    libgl1-mesa-glx libglib2.0-0 libdbus-1-3
```

---

## Part 9 — Run the Client

Make sure the server is running first (Part 7), then activate the client venv:

```bash
cd ~/robotic_robo
source client/client-venv/bin/activate
```

### Option A — Text mode (no microphone, no display — best for initial testing)

```bash
python -m client.main --text
```

Type a message and press Enter. You will see the LLM response streamed back in the terminal.

### Option B — Headless audio mode (microphone, no display)

```bash
python -m client.main --no-ui
```

Speak into your microphone. The response is printed to the terminal and played back through speakers.

### Option C — Full kiosk UI (requires display)

```bash
python -m client.main
```

Launches the PyQt6 fullscreen kiosk window. Requires a display (X11 or Wayland).

---

## Part 10 — Verify the Full Pipeline

With everything running, do a quick end-to-end test:

```bash
# In a new terminal, activate client venv
source client/client-venv/bin/activate

# Run text mode
python -m client.main --text
```

Type: `What is the weather today?`

Expected flow:
1. Client sends text to server over WebSocket
2. Server detects intent → calls SearXNG for web search
3. LLM (Ollama) generates a response using search results
4. Kokoro TTS synthesises audio (or CosyVoice as fallback)
5. Audio streams back to client
6. Text response prints in terminal

---

## Part 11 — tmux Session Layout (Recommended)

Running multiple processes is easier with `tmux`. Install it:

```bash
sudo apt install -y tmux
```

Suggested session layout:

```bash
# Window 1: Docker services (already running in background)
docker compose ps

# Window 2: CosyVoice service
tmux new -s cosyvoice
cd ~/robotic_robo/cosyvoice_service && bash start.sh
# Detach: Ctrl+B D

# Window 3: Server
tmux new -s server
cd ~/robotic_robo && source venv/bin/activate
python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
# Detach: Ctrl+B D

# Window 4: Client (when testing)
tmux new -s client
cd ~/robotic_robo && source client/client-venv/bin/activate
python -m client.main --text
```

Reattach to any session:
```bash
tmux attach -t server
tmux attach -t cosyvoice
```

---

## Part 12 — Firewall (if needed)

If the Ubuntu machine has `ufw` enabled and you need to access it from another machine on the network:

```bash
sudo ufw allow 8765/tcp   # Server WebSocket
sudo ufw allow 8081/tcp   # SearXNG (optional, local only)
sudo ufw allow 11434/tcp  # Ollama (optional, local only)
sudo ufw allow 5002/tcp   # CosyVoice (optional, local only)
```

---

## Troubleshooting

### Docker: permission denied

```bash
# Make sure your user is in the docker group
sudo usermod -aG docker $USER
newgrp docker
```

### Ollama model not found

```bash
docker compose exec ollama ollama list
# If empty, pull again:
docker compose exec ollama ollama pull qwen2.5:3b-instruct
```

### SearXNG returns no results

Check the container logs:
```bash
docker compose logs searxng
```

Make sure `searxng/settings.yml` has `formats: [html, json]` — the server queries the JSON format.

### Whisper model download fails

Set your HuggingFace token in `.env.local`:
```
HUGGING_FACE_HUB_TOKEN=hf_your_token_here
```

Or download manually and point `STT_MODEL` to the local path.

### CosyVoice import error

```bash
cd cosyvoice_service
source venv/bin/activate
python -c "import sys; sys.path.insert(0, 'cosyvoice_repo'); from cosyvoice.cli.cosyvoice import CosyVoice2; print('OK')"
```

If it fails, re-run `bash setup.sh`.

### No audio device (headless server)

If the server machine has no audio hardware and you get `sounddevice` errors on the client, run the client in `--text` mode or run the client on a separate machine that has audio.

### PyQt6 display error (`cannot connect to X server`)

The full UI mode requires a display. Use `--text` or `--no-ui` mode on a headless server, or set up X11 forwarding:
```bash
ssh -X user@server-ip
```

### GPU not detected by Docker

```bash
# Verify NVIDIA runtime is configured
docker info | grep -i runtime
# Should show: nvidia

# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

If it fails, re-run:
```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

---

## Quick Reference — Startup Order

Every time you start the machine, bring services up in this order:

```
1. docker compose up -d searxng ollama
2. (tmux) cd cosyvoice_service && bash start.sh
3. (tmux) source venv/bin/activate && python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
4. (tmux) source client/client-venv/bin/activate && python -m client.main --text
```

---

## Quick Reference — Port Map

| Port | Service |
|---|---|
| `8765` | Server WebSocket + HTTP health |
| `8081` | SearXNG web search |
| `11434` | Ollama LLM API |
| `5002` | CosyVoice2 TTS service |
| `50021` | VOICEVOX Japanese TTS (if used) |
