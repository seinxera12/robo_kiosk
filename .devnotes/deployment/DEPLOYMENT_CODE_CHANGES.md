# DEPLOYMENT_CODE_CHANGES.md

Local code/config changes required before the backend can be deployed to the
remote Ubuntu server. **No code was modified in this pass** — this is the plan.

Every item traces to a specific file/line found during the audit. Assumptions
about the remote server (free ports, existing containers) are stated explicitly
where the codebase cannot confirm them.

---

## Audit Findings (summary)

**Structure map**

| Path | Purpose | Server-needed? |
|------|---------|----------------|
| `server/` | FastAPI backend: STT, LLM fallback chain, RAG, TTS router, search, tools | **Yes** |
| `frontend/` | React/Vite kiosk UI (57 tracked files, incl. `dist/`, `node_modules/`) | No — runs on client device |
| `client/` | Legacy Python UI + `client-venv/` | No |
| `docker-compose.yml` | voice-server, ollama, searxng, searxng-redis (+ commented vLLM) | **Yes** |
| `searxng/` | SearXNG `settings.yml` (gitignored) | **Yes** |
| `models/`, `building_kb/`, `chroma_data/` | Volume-mounted data (gitignored) | **Yes** (provisioned on server) |
| `scripts/` | `download_models.sh`, `ingest_kb.sh`, `setup_docker_dirs.sh`, `validate_docker_setup.sh` | **Yes** |
| `Makefile` | Docker Compose wrapper commands | **Yes** |
| `.env`, `.env.local` | **Contain real secrets** (see below); gitignored | No (recreated on server) |
| `kokoclone/` | Git submodule (Japanese TTS microservice) — separate venv, not containerised | Optional |

**Service inventory**

| Service | Image / build | Ports (host:container) | Depends on | GPU |
|---------|---------------|------------------------|-----------|-----|
| `voice-server` | `build: ./server` (**Dockerfile missing**) | `8765:8765` (WS), `8000:8000` (health) | ollama, searxng | 1 GPU, no mem cap |
| `ollama` | `ollama/ollama:latest` | `11434:11434` | — | 1 GPU, no mem cap |
| `searxng` | `searxng/searxng:latest` | `8081:8080` | searxng-redis | — |
| `searxng-redis` | `redis:alpine` | none | — | — |
| `vllm` | `vllm/vllm-openai:latest` | `8001:8001` | — | **entire block commented out** |

**Config & secrets** — `.env` and `.env.local` hold a live Hugging Face token
(`hf_QzaLXwRO…`) and SearXNG secret (`myvoicekiosk2026secret`). `.env.example`
uses placeholders (good). Three `.env` files disagree on TTS engine, model
names, and URLs.

**Network** — single `voice-network` bridge. In-container URLs correctly use
service names in compose (`http://vllm:8001`, `http://searxng:8080`), **but**
`server/search/query_reformulator.py:12` and `KOKOCLONE_URL` hardcode
`localhost`, which does not resolve to sibling containers/host.

**GPU** — voice-server and ollama each `reservations: devices: [gpu] count:1`.
No `VLLM_GPU_MEMORY_UTILIZATION` scoping is active (vLLM commented out); nothing
prevents contention with the server's existing GPU workloads.

---

## 1. Backend/Frontend Decoupling

### Frontend and legacy client are on the deploy branch
- **Problem:** `frontend/` (incl. `dist/` and `node_modules/`) and `client/` (incl. `client-venv/`) are git-tracked and present on `deploy/server`. The instruction states the frontend is deployed elsewhere.
- **Impact if unresolved:** Bloats the transfer, ships `node_modules` and a Python venv to the server, and blurs the deploy boundary. Potential for stale build artifacts to be served accidentally.
- **Proposed fix:** Exclude `frontend/` and `client/` from what reaches the server via `.dockerignore` (already lists both) **and** a deploy-time exclude list / sparse checkout on the deploy branch. Remove `frontend/dist` and both `node_modules`/`client-venv` from tracking (`git rm -r --cached`).
- **Files affected:** `.gitignore`, `.dockerignore`, deploy branch tree.
- **Risk of fix:** Low. `main` remains full source of truth; only the deploy path is trimmed.

### CORS wildcard with credentials
- **Problem:** `server/main.py:90-96` sets `allow_origins=["*"]` **with** `allow_credentials=True`. Browsers reject this combination; it is also over-permissive for a network-exposed service.
- **Impact if unresolved:** Credentialed requests fail; any origin can call the API.
- **Proposed fix:** Drive allowed origins from an env var (e.g. `ALLOWED_ORIGINS`) defaulting to the kiosk client host(s); set `allow_credentials=False` if credentials are unused (the WS handshake here uses none).
- **Files affected:** `server/main.py`, `.env.example`.
- **Risk of fix:** Low, but verify the kiosk client origin is included before locking down.

---

## 2. Environment & Secrets Management

### Live secrets present in local `.env` / `.env.local`
- **Problem:** `.env:11` and `.env.local:1` contain a real Hugging Face token; `.env:13`/`.env.local:3` a real SearXNG secret. Files are gitignored (verified: only `.env.example` and `frontend/.env.example` are tracked), so they are **not in git history**, but they exist on disk and are trivially copyable.
- **Impact if unresolved:** If either file is ever transferred or the token reused, it is a credential leak. `SEARXNG_SECRET` predictable/committed weakens SearXNG.
- **Proposed fix:** Treat both as compromised — **rotate the HF token** and generate a fresh random `SEARXNG_SECRET` on the server. Never transfer `.env*`; create `.env` on the server from `.env.example`. Confirm `.gitignore` keeps `.env` and `.env.local` untracked (it does).
- **Files affected:** `.env`, `.env.local` (server-side only), `.env.example` (already placeholder).
- **Risk of fix:** Low. Rotation requires re-pulling any gated HF models.

### `.env` files disagree and reference removed engines
- **Problem:** `.env` and `.env.local` still set `TTS_EN_ENGINE=cosyvoice`, `COSYVOICE_URL`, `TTS_JP_URL` (VOICEVOX), and `QWEN3_TTS_*` — but the cleanup removed CosyVoice/VOICEVOX, and `config.py` no longer reads these keys. `.env.local:11` sets `VLLM_MODEL_NAME=disabled`; `.env:33` sets `Qwen2.5-3B`; `.env.example:34` sets `Qwen2.5-7B-AWQ`.
- **Impact if unresolved:** Operator confusion; wrong model served; dead keys mask the real (Kokoro-based) config.
- **Proposed fix:** Make `.env.example` the single canonical template (it already matches `config.py`'s keys). Delete stale keys from the server `.env`. Pick one authoritative `VLLM_MODEL_NAME`.
- **Files affected:** `.env.example` (canonical), server `.env`.
- **Risk of fix:** Low.

### `KOKOCLONE_REF_AUDIO` hardcodes a local absolute path
- **Problem:** `.env.example:96` / `.env.local:71` point to `/home/seinxera12/robotic_robo/voices_reference/...`. Inside the container this path does not exist unless mounted; `voices_reference/` is not a compose volume.
- **Impact if unresolved:** KokoClone TTS silently disabled (Japanese primary falls back to Kokoro JP).
- **Proposed fix:** Mount `./voices_reference:/voices_reference:ro` in compose and set `KOKOCLONE_REF_AUDIO=/voices_reference/ref.wav`, **or** leave KokoClone disabled (`KOKOCLONE_ENABLED=false`, as `.env.local` already does).
- **Files affected:** `docker-compose.yml`, server `.env`.
- **Risk of fix:** Low.

---

## 3. Docker & Networking

### `server/Dockerfile` does not exist (BLOCKER)
- **Problem:** `docker-compose.yml:6-8` declares `build: context: ./server / dockerfile: Dockerfile`, but no Dockerfile exists anywhere in the repo (verified via glob and git ls-files).
- **Impact if unresolved:** `docker compose build`/`up --build` fails immediately. **Deployment is impossible.**
- **Proposed fix:** Author `server/Dockerfile` (CUDA-enabled Python base, install `server/requirements.txt`, copy `server/`, `CMD python -m server.main`). Ensure it exposes 8765 and installs `curl` for the health check.
- **Files affected:** new `server/Dockerfile`.
- **Risk of fix:** Medium — base image/CUDA/torch wheel compatibility must match the server's driver.

### Health check targets a port nothing listens on (BLOCKER)
- **Problem:** `main.py` binds a single uvicorn app to `config.port` (8765) and serves `/health` on that same app. Compose maps `8000:8000` and healthchecks `http://localhost:8000/health` (`docker-compose.yml:11,55`). Nothing listens on 8000.
- **Impact if unresolved:** Container health check always fails → `unhealthy` → `depends_on`/restart churn; `make health` (curl :8000) misreports.
- **Proposed fix:** Point the health check and README at 8765 (`http://localhost:8765/health`) and drop the `8000:8000` mapping, **or** run a second lightweight listener on 8000. Simplest: use 8765 everywhere.
- **Files affected:** `docker-compose.yml`, `Makefile` (`health` target), `README.md:197`.
- **Risk of fix:** Low.

### `query_reformulator.py` hardcodes `localhost:11434`
- **Problem:** `server/search/query_reformulator.py:12` sets `OLLAMA_BASE_URL = "http://localhost:11434"` as a module constant, ignoring config/env.
- **Impact if unresolved:** Inside the container, `localhost` is the container itself, not the `ollama` service → search query reformulation fails.
- **Proposed fix:** Read from `Config`/env (`http://ollama:11434` in Docker), don't hardcode.
- **Files affected:** `server/search/query_reformulator.py`.
- **Risk of fix:** Low.

### Port collisions with existing server containers
- **Problem:** Host ports published: 8765, 8000, 11434 (ollama), 8081 (searxng), and 8001 if vLLM is enabled. **Assumption:** the remote server already runs unrelated Docker services and may occupy some of these (cannot verify from the repo).
- **Impact if unresolved:** `docker compose up` fails on bind conflict, or hijacks a port another service expects.
- **Proposed fix:** Make host ports env-driven (e.g. `${SERVER_PORT_HOST:-8765}:8765`) so they can be remapped without editing compose. Confirm availability in the pre-deployment checklist.
- **Files affected:** `docker-compose.yml`, `.env.example`.
- **Risk of fix:** Low.

### Dev bind-mount of source in compose
- **Problem:** `docker-compose.yml:17` mounts `./server:/app/server` ("Development: mount source code"). In production this overlays the image's code with whatever is on the server's disk.
- **Impact if unresolved:** Image contents become meaningless; drift between built image and running code; violates "no manual edits on server".
- **Proposed fix:** Remove the source bind-mount for production (keep model/kb/chroma volumes). Optionally use a `docker-compose.override.yml` for the dev mount only.
- **Files affected:** `docker-compose.yml`.
- **Risk of fix:** Low.

### vLLM (declared "primary" backend) is fully commented out
- **Problem:** `docker-compose.yml:70-110` is commented; yet `.env`/`.env.example` treat vLLM as primary (`VLLM_BASE_URL=http://vllm:8001/v1`). `LLMFallbackChain` will try vLLM first and always fail over to Ollama.
- **Impact if unresolved:** Wasted first-attempt latency on every request; confusion about which engine is actually serving. The instruction says vLLM images are already pulled on the server.
- **Proposed fix:** Decide explicitly: either uncomment/enable vLLM (with GPU mem scoping, below) and set the real model, or set `VLLM_MODEL_NAME=disabled` (as `.env.local` does) so the chain skips it cleanly.
- **Files affected:** `docker-compose.yml`, server `.env`.
- **Risk of fix:** Medium (GPU contention if enabled).

### No `depends_on` for a required Ollama model pull
- **Problem:** `LLMFallbackChain`/reformulator expect `qwen2.5:3b`/`7b` in Ollama, but nothing pulls the model on first boot (only a manual `make ollama-pull`).
- **Impact if unresolved:** First requests fail until an operator manually pulls the model.
- **Proposed fix:** Document the pull as a mandatory post-deploy step (guide §6) or add an init step.
- **Files affected:** `DEPLOYMENT_GUIDE.md`, optionally an init script.
- **Risk of fix:** Low.

---

## 4. GPU / Resource Scoping

### No GPU memory limit for any GPU service
- **Problem:** `voice-server` and `ollama` reserve a GPU but set no memory ceiling; vLLM (if enabled) defaults to `--gpu-memory-utilization 0.90` (commented example). The server already runs other GPU workloads.
- **Impact if unresolved:** OOM or eviction of the server's existing GPU services; unpredictable coexistence.
- **Proposed fix:** Pin `CUDA_VISIBLE_DEVICES` / `device_ids` to a specific GPU index, and if vLLM is enabled lower `--gpu-memory-utilization` (e.g. 0.4–0.5) sized to free VRAM. STT (`STT_DEVICE`) and Kokoro (`KOKORO_DEVICE`) can run on CPU to reduce pressure. Make these env-driven.
- **Files affected:** `docker-compose.yml`, `.env.example`.
- **Risk of fix:** Medium — under-provisioning slows inference; must be sized against `nvidia-smi` on the server.

---

## 5. Logging & Observability

### No log rotation / structured logging
- **Problem:** `main.py` logs to stdout only; compose sets no `logging:` driver options. A `logs/` dir exists but nothing writes rotated files.
- **Impact if unresolved:** Container JSON logs grow unbounded; disk exhaustion risk on a shared server.
- **Proposed fix:** Add per-service `logging: driver: json-file, options: {max-size: "10m", max-file: "5"}` in compose.
- **Files affected:** `docker-compose.yml`.
- **Risk of fix:** Low.

### Health check gives no readiness signal for LLM/STT load
- **Problem:** `/health` returns 200 immediately once the app is up; heavy model loads happen in `lifespan` but the endpoint reports "healthy" regardless of whether STT/LLM finished loading. `start_period: 60s` may be too short for large-v3 + model downloads.
- **Impact if unresolved:** Container marked healthy before it can serve; first client hits errors.
- **Proposed fix:** Extend `start_period` (e.g. 180s) and/or have `/health` report component readiness (it already checks TTS; extend to STT/LLM).
- **Files affected:** `docker-compose.yml`, `server/main.py`.
- **Risk of fix:** Low.

---

## 6. Miscellaneous

### `all_requirments.txt` vs `server/requirements.txt`
- **Problem:** A root `all_requirments.txt` (typo'd) coexists with `server/requirements.txt`. Unclear which the Dockerfile should use.
- **Impact if unresolved:** Wrong/duplicate dependency set baked into the image.
- **Proposed fix:** Build from `server/requirements.txt`; keep `all_requirments.txt` as a dev-only convenience or remove it.
- **Files affected:** new `server/Dockerfile`, root.
- **Risk of fix:** Low.

### `kokoclone` submodule
- **Problem:** `.gitmodules` references a submodule that runs as a separate venv microservice, not containerised. If unused (`KOKOCLONE_ENABLED=false` in `.env.local`), it is dead weight on the server.
- **Impact if unresolved:** Extra clone/setup complexity; confusion about the TTS path.
- **Proposed fix:** If Japanese cloning isn't needed at launch, keep `KOKOCLONE_ENABLED=false` and skip `--recurse-submodules` on the server. Document as optional.
- **Files affected:** `DEPLOYMENT_GUIDE.md`.
- **Risk of fix:** Low.
