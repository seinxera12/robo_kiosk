# Deployment as a Distributable Application

## What You're Actually Trying to Do

You want to hand this project to another machine — ideally with a single installer or image — so the recipient doesn't have to manually install Ollama, VOICEVOX, CosyVoice, SearXNG, Whisper, ChromaDB, Python, and wire them all together.

This document analyses the realistic options, their tradeoffs, and gives a concrete recommendation.

---

## What the Stack Actually Consists Of

Before deciding on a packaging strategy, it's important to be clear about what needs to be bundled:

| Component | Type | Size | GPU? |
|-----------|------|------|------|
| Ollama + LLM model (qwen2.5:3b) | Native binary + model weights | ~2.5 GB | Yes (optional) |
| faster-whisper (large-v3-turbo) | Python + model weights | ~1.5 GB | Yes (optional) |
| CosyVoice2 service | Python FastAPI + model | ~1 GB | Yes (optional) |
| VOICEVOX engine | Native Linux binary | ~300 MB | No |
| SearXNG | Docker image / Python | ~200 MB | No |
| ChromaDB + sentence-transformers | Python + model | ~500 MB | No |
| Server (FastAPI + pipeline) | Python | ~50 MB | No |
| Client (PyQt6 UI) | Python | ~100 MB | No |

**Total: ~6–7 GB before OS and Python runtime.**

This is not a typical desktop app. It is a multi-process AI inference system. That distinction drives every decision below.

---

## Option 1 — PyInstaller / cx_Freeze (Bundle Python into .exe)

**Idea:** Use PyInstaller to freeze the Python code and dependencies into a single executable.

**Why it won't work here:**

- PyInstaller bundles Python code and pure-Python packages. It cannot bundle native binaries like Ollama, VOICEVOX, or the CUDA runtime.
- `torch`, `faster-whisper`, and `chromadb` have native C extensions and CUDA dependencies that PyInstaller handles poorly — known to produce broken builds with GPU libraries.
- The result would still require the user to separately install Ollama, VOICEVOX, and CUDA drivers.
- You'd end up with a ~3 GB `.exe` that still requires manual setup of the hard parts.

**Verdict: Not viable for this stack.**

---

## Option 2 — Full Docker Compose Bundle

**Idea:** Ship the existing `docker-compose.yml` with all images pre-pulled and saved as a tarball.

**How it would work:**

```bash
# On your machine — save all images to a tar archive
docker save \
  voice-server \
  ollama/ollama:latest \
  voicevox/voicevox_engine:latest \
  searxng/searxng:latest \
  | gzip > robo_kiosk_images.tar.gz

# On target machine
docker load < robo_kiosk_images.tar.gz
docker-compose up -d
```

**What the recipient needs:**
- Docker Desktop (Windows) or Docker Engine (Linux/Ubuntu)
- NVIDIA Container Toolkit (if GPU is needed)
- ~10 GB disk space

**Pros:**
- Reproducible environment — exact same OS, Python version, library versions
- No manual dependency installation
- Works on Windows (via Docker Desktop) and Linux
- Already have the `docker-compose.yml`

**Cons:**
- Docker Desktop on Windows requires WSL2 and Hyper-V — not available on Windows Home without extra steps
- Ollama model weights (~2.5 GB) are not inside the Docker image — they live in a volume and still need to be pulled once
- CosyVoice is not yet in the main `docker-compose.yml` (it has its own separate compose file)
- First-time GPU passthrough setup can still trip up non-technical users

**Verdict: Best option for a technical recipient. Moderate setup friction.**

---

## Option 3 — VM Image (OVA / VMDK)

**Idea:** Create a full Ubuntu VM with everything pre-installed and pre-configured, export it as an OVA file that can be imported into VirtualBox or VMware.

**How it would work:**

1. Set up a clean Ubuntu 22.04 VM
2. Install all dependencies, pull all models, configure everything
3. Export as `.ova` (VirtualBox) or `.vmdk` (VMware)
4. Recipient imports the VM and runs it

**What the recipient needs:**
- VirtualBox (free) or VMware
- ~20–30 GB disk space for the OVA
- Enough RAM (16 GB+ recommended)

**Pros:**
- Completely self-contained — recipient just imports and runs
- No dependency installation at all
- Works on Windows, macOS, Linux
- Models are pre-downloaded inside the image

**Cons:**
- GPU passthrough in VMs is complex and often broken (VirtualBox has poor GPU support; VMware Workstation Pro is paid)
- Without GPU passthrough, Whisper and CosyVoice run on CPU — very slow (10–30s per response)
- OVA file will be 20–30 GB — difficult to distribute
- VM adds overhead; not suitable for a kiosk that needs low latency

**Verdict: Good for demos on non-GPU machines where latency doesn't matter. Bad for production kiosk use.**

---

## Option 4 — WSL2 Distro Export (Windows-Specific)

**Idea:** Export your configured WSL2 Ubuntu environment as a `.tar` file that can be imported on another Windows machine.

**How it would work:**

```powershell
# On your machine (Windows PowerShell)
wsl --export Ubuntu robo_kiosk_wsl.tar

# On target machine (Windows PowerShell)
wsl --import RoboKiosk C:\RoboKiosk\ robo_kiosk_wsl.tar
wsl -d RoboKiosk
```

**What the recipient needs:**
- Windows 10/11 with WSL2 enabled
- ~15–20 GB disk space
- Ollama installed on Windows (separate step)

**Pros:**
- Captures your exact WSL2 environment — Python venv, installed packages, model weights, ChromaDB data, all configs
- No Docker required
- Recipient just imports and runs — no pip install, no apt-get
- Ollama on Windows is a simple `.exe` installer

**Cons:**
- Windows-only
- WSL2 export includes the entire Ubuntu filesystem — large file (~15 GB)
- GPU access from WSL2 requires NVIDIA drivers with WSL2 support (CUDA on WSL2) — works on modern NVIDIA cards but needs driver version ≥ 525
- Recipient still needs to install Ollama on Windows and pull the model once

**Verdict: Best option specifically for Windows-to-Windows delivery. Lowest friction for a technical-but-not-AI-expert recipient.**

---

## Option 5 — Nix Flake / Conda-Pack (Reproducible Python Environment)

**Idea:** Use `conda-pack` or a Nix flake to create a portable, self-contained Python environment tarball.

**Why it's insufficient here:**

- Handles Python dependencies only — not Ollama, VOICEVOX, or SearXNG
- Still requires the recipient to install native binaries separately
- Adds complexity without solving the core distribution problem

**Verdict: Useful as a component of a larger solution, not a standalone answer.**

---

## Recommendation

### For Windows → Windows delivery (most likely scenario):

**Use WSL2 distro export + Ollama Windows installer.**

This is the lowest-friction path that preserves GPU access and doesn't require Docker.

Delivery package:
1. `robo_kiosk_wsl.tar` — exported WSL2 distro with everything pre-installed
2. A one-page `INSTALL.md` with three steps (see below)
3. Ollama Windows installer (or a link to it)

### For cross-platform or production deployment:

**Use Docker Compose with pre-saved images.**

Consolidate `docker-compose.yml` and `docker-compose.cosyvoice.yml` into a single compose file, save all images to a tar archive, and ship that with a startup script.

---

## Implementation Plan

### Path A — WSL2 Export (Windows → Windows)

#### Step 1: Prepare the WSL2 environment

Before exporting, make sure everything is working in your current WSL2:

- All Python packages installed in the venv
- ChromaDB ingested with building knowledge
- CosyVoice model downloaded (`iic/CosyVoice2-0.5B` in HuggingFace cache)
- Whisper model cached (`~/.cache/huggingface/`)
- VOICEVOX binary present and tested
- `.env.nodocker` configured and working
- SearXNG running (or note it as optional)

#### Step 2: Clean up before export

```bash
# Remove Python cache files to reduce size
find ~/icn/robo_kiosk -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
find ~/icn/robo_kiosk -name "*.pyc" -delete 2>/dev/null

# Remove any large log files
truncate -s 0 ~/icn/robo_kiosk/logs/*.txt 2>/dev/null || true
```

#### Step 3: Export the distro

On Windows PowerShell (not WSL):

```powershell
# Shut down WSL first for a clean export
wsl --shutdown

# Export (this will take several minutes — ~15 GB)
wsl --export Ubuntu D:\robo_kiosk_wsl.tar

# Compress it (optional, saves ~30% space)
# Use 7-Zip or:
Compress-Archive -Path D:\robo_kiosk_wsl.tar -DestinationPath D:\robo_kiosk_wsl.zip
```

#### Step 4: Create the recipient install script

Create `INSTALL_WINDOWS.md` for the recipient:

```
Prerequisites:
  - Windows 10 (build 19041+) or Windows 11
  - WSL2 enabled: run in PowerShell as Admin:
      wsl --install
      (reboot if prompted)
  - NVIDIA GPU drivers 525+ (for GPU acceleration)
    Download from: https://www.nvidia.com/drivers

Step 1 — Install Ollama on Windows
  Download from: https://ollama.com/download
  Run the installer. It starts automatically.
  Open PowerShell and run:
    ollama pull qwen2.5:3b-instruct

Step 2 — Import the WSL2 environment
  Open PowerShell as Administrator:
    wsl --import RoboKiosk C:\RoboKiosk\ robo_kiosk_wsl.tar

Step 3 — Start the kiosk
  Open PowerShell:
    wsl -d RoboKiosk -- bash /home/<user>/icn/robo_kiosk/start_kiosk.sh
```

#### Step 5: Create a startup script

Create `start_kiosk.sh` in the project root:

```bash
#!/bin/bash
# Start all kiosk services and the client UI

PROJECT_DIR="$HOME/icn/robo_kiosk"
cd "$PROJECT_DIR"

source .venv/bin/activate
export $(grep -v '^#' .env.nodocker | xargs)
export PYTHONPATH="$PROJECT_DIR"

# Start VOICEVOX in background
echo "Starting VOICEVOX..."
~/voicevox_engine/run --host 0.0.0.0 --port 50021 &
VOICEVOX_PID=$!

# Start CosyVoice service in background
echo "Starting CosyVoice service..."
cd cosyvoice_service
source venv/bin/activate
python app.py &
COSYVOICE_PID=$!
cd "$PROJECT_DIR"
source .venv/bin/activate

# Wait for services to be ready
sleep 5

# Start the main server in background
echo "Starting voice server..."
uvicorn server.main:app --host 0.0.0.0 --port 8765 &
SERVER_PID=$!

# Wait for server to be ready
sleep 8

# Start the client
echo "Starting kiosk UI..."
python client/main.py

# Cleanup on exit
kill $VOICEVOX_PID $COSYVOICE_PID $SERVER_PID 2>/dev/null
```

---

### Path B — Docker Compose Bundle (Cross-Platform)

#### Step 1: Consolidate compose files

Merge `docker-compose.cosyvoice.yml` into `docker-compose.yml` so there is one file to manage.

Add the CosyVoice service block to the main compose file with the correct network and dependency settings.

#### Step 2: Build and save all images

```bash
# Build the voice-server image
docker-compose build voice-server

# Pull all external images
docker-compose pull

# Save everything to a single archive
docker save \
  $(docker-compose config --images | tr '\n' ' ') \
  | gzip > robo_kiosk_docker_images.tar.gz
```

#### Step 3: Package for delivery

Create a zip containing:
```
robo_kiosk_delivery/
├── robo_kiosk_docker_images.tar.gz   (~8 GB)
├── docker-compose.yml                (consolidated)
├── .env.example                      (recipient fills in their values)
├── searxng/settings.yml              (SearXNG config)
├── building_kb/                      (knowledge base documents)
└── INSTALL_DOCKER.md
```

#### Step 4: Recipient install script

```
Prerequisites:
  - Docker Desktop (Windows/macOS) or Docker Engine (Linux)
  - NVIDIA Container Toolkit (for GPU)
  - 20 GB free disk space

Step 1 — Load images
  docker load < robo_kiosk_docker_images.tar.gz

Step 2 — Configure
  cp .env.example .env
  # Edit .env: set BUILDING_NAME, GROK_API_KEY (optional)

Step 3 — Pull Ollama model (one-time, ~2.5 GB)
  docker-compose run --rm ollama ollama pull qwen2.5:3b-instruct

Step 4 — Ingest knowledge base (one-time)
  docker-compose run --rm voice-server python server/rag/ingest.py \
    --kb-path /building_kb --chroma-path /chroma

Step 5 — Start everything
  docker-compose up -d

Step 6 — Open the client
  python client/main.py
  (client runs on the host machine, not in Docker)
```

---

## Honest Assessment of Remaining Friction

No matter which path you choose, there are two things that cannot be fully automated:

1. **NVIDIA drivers** — GPU acceleration requires the recipient to have compatible NVIDIA drivers installed. This is a hardware-level dependency that no software bundle can satisfy. If the target machine has no NVIDIA GPU, everything still works but Whisper and CosyVoice will be slow (CPU mode).

2. **Ollama model pull** — The LLM weights (~2.5 GB) are not practical to bundle inside a Docker image or WSL export due to size. A one-time `ollama pull` is unavoidable unless you pre-bake the weights into the WSL export (which you can do — they live in `~/.ollama/models/` inside WSL if Ollama is run inside WSL, but in this project Ollama runs on Windows, so the weights are on the Windows side).

Everything else — Python, VOICEVOX, CosyVoice, Whisper, ChromaDB, SearXNG — can be fully pre-installed in either the WSL export or Docker images.

---

## Summary

| Option | Recipient effort | GPU support | File size | Best for |
|--------|-----------------|-------------|-----------|----------|
| PyInstaller .exe | High (still needs Ollama etc.) | Broken | ~3 GB | Not viable |
| Docker Compose bundle | Low-medium | Good (with toolkit) | ~10 GB | Cross-platform, technical recipient |
| WSL2 export | Low (Windows only) | Good (WSL2 CUDA) | ~15 GB | Windows → Windows, fastest path |
| VM image (OVA) | Very low | Poor (no GPU passthrough) | ~25 GB | Demo only, no latency requirement |

**Recommended path for your use case:** WSL2 export for Windows kiosk delivery, Docker Compose bundle for anything else.
