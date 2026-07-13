# DEPLOYMENT_GUIDE.md

Step-by-step guide for migrating the **backend-only** voice-kiosk stack to the
remote Ubuntu server and operating it. The frontend runs on a separate client
device and only needs network access to the backend.

> Blockers from `DEPLOYMENT_CODE_CHANGES.md` (missing `server/Dockerfile`,
> health-port mismatch, hardcoded `localhost:11434`) must be resolved **before**
> the first deploy. This guide assumes they are.

**Stated assumptions** (not verifiable from the repo):
- Remote host runs Docker + NVIDIA Container Toolkit; CUDA drivers work.
- vLLM and other base images are already pulled.
- Free host ports are **unknown** — the guide makes them env-configurable and
  the pre-deploy checklist verifies availability.

---

## 1. Migration Method

**Options**

- **git-based deploy** — server clones a dedicated `deploy/server` branch and
  pulls updates. Pros: versioned, auditable, trivial rollback (`git checkout
  <tag>`), no local↔remote path coupling. Cons: puts a git remote on the server.
- **rsync** — push a filtered working tree over SSH. Pros: no git on server,
  precise `--exclude`. Cons: no built-in versioning/rollback, easy to drift,
  harder to answer "what exactly is deployed?".

**Recommendation: git-based deploy** on the existing `deploy/server` branch.
The repo already maintains this branch (current branch is `deploy/server`), the
"no manual edits on server" constraint maps cleanly to "server only ever pulls",
and rollback becomes a tag checkout + rebuild.

**Commands (first-time, on the server)**
```bash
# Clone only the deploy branch, no frontend history noise
git clone --branch deploy/server --single-branch \
  https://github.com/seinxera12/robotic_robo.git voice-backend
cd voice-backend

# Provision runtime data + secrets (never transferred — see §3)
cp .env.example .env && $EDITOR .env        # fill real secrets, rotate SEARXNG_SECRET
./scripts/setup_docker_dirs.sh              # creates models/ building_kb/ chroma_data/
# place model weights + KB (scripts/download_models.sh, scripts/ingest_kb.sh)

docker compose build            # requires server/Dockerfile to exist
docker compose up -d
```

---

## 2. Branching Strategy

- **`main`** — full source of truth, includes `frontend/` and `client/`.
- **`deploy/server`** — backend-only deployable snapshot. What the server pulls.
- **Release tags** — `deploy-vYYYY.MM.DD` (or semver) cut on `deploy/server` for
  rollback anchors.

**Excluding frontend/client from the server — chosen method: git sparse-checkout
on the deploy branch** (justification: keeps a single branch and history, needs
no build step, and the exclusion is enforced at checkout so stale artifacts can't
sneak onto the server; a subtree split would fragment history, and a manual
exclude list is easy to forget).

On the server, after clone:
```bash
git sparse-checkout init --cone
git sparse-checkout set server searxng scripts docker-compose.yml Makefile \
  .env.example .dockerignore all_requirments.txt
```
This materialises only backend paths; `frontend/`, `client/`, `.kiro/`, `guides/`
never touch disk. `.dockerignore` already excludes `frontend/` and `client/` from
the build context as a second layer of defence.

> Housekeeping (in `main`, per code-changes plan): `git rm -r --cached
> frontend/dist frontend/node_modules client/client-venv` so build artifacts and
> venvs stop being tracked at all.

---

## 3. File Handling Rules

**Never send to server**
- `frontend/` (source, `dist/`, `node_modules/`) — deployed on the client device.
- `client/` and `client/client-venv/` — legacy Python UI.
- `.env`, `.env.local` — contain live secrets; recreated on server.
- `venv/`, `.hypothesis/`, `.pytest_cache/`, `.vscode/`, `.kiro/`, `guides/`.
- Local model/data caches you don't want overwritten.

**Send but handle differently**
- `.env` → **created on the server** from `.env.example`; never committed/transferred.
- `SEARXNG_SECRET`, `HUGGING_FACE_HUB_TOKEN` → set on server only; **rotate** the
  currently-committed-locally values (treat as compromised).
- `models/`, `building_kb/`, `chroma_data/` → provisioned on server via
  `scripts/`, not shipped in git (already gitignored).
- `searxng/settings.yml` → generated on server (gitignored).

**Send as-is**
- `server/` (all backend code), `server/Dockerfile` (once authored),
  `docker-compose.yml`, `Makefile`, `scripts/`, `.dockerignore`, `.env.example`.

**Concrete exclude entries**

`.gitignore` (already covers `.env`, `.env.local`, `venv/`, `chroma_data/`,
`models/`; add):
```
frontend/dist/
frontend/node_modules/
client/client-venv/
```

`.dockerignore` (already excludes `client/`, `frontend`-via-source, `.env`,
`models/`, `scripts/`, `*.md` — keep). Confirm `frontend/` is excluded explicitly:
```
frontend/
```

rsync exclude list (only if you ever fall back to rsync):
```
rsync -avz --delete \
  --exclude '.git' --exclude 'frontend' --exclude 'client' \
  --exclude '.env' --exclude '.env.local' --exclude 'venv' \
  --exclude 'node_modules' --exclude 'chroma_data' --exclude 'models' \
  --exclude '.kiro' --exclude 'guides' \
  ./ user@server:/opt/voice-backend/
```

---

## 4. Sync Workflow (ongoing changes)

1. **Local:** commit on a feature branch → merge into `main` → merge (or
   cherry-pick backend-only changes) into `deploy/server`.
   ```bash
   git checkout deploy/server
   git merge --no-ff main            # or cherry-pick server/* commits
   git tag deploy-2026.07.10
   git push origin deploy/server --tags
   ```
2. **Transfer (server):**
   ```bash
   cd /opt/voice-backend && git fetch --tags && git checkout deploy/server && git pull
   ```
3. **Rebuild/restart (server):**
   ```bash
   docker compose build voice-server        # only if server/ or Dockerfile changed
   docker compose up -d                      # recreates changed containers only
   docker compose ps                         # confirm healthy
   ```
4. **Versioning/tagging convention:** tag every server-facing release
   `deploy-YYYY.MM.DD` (append `-N` for same-day re-cuts). The checked-out tag on
   the server is the authoritative "what's running".
5. **Rollback:**
   ```bash
   cd /opt/voice-backend
   git checkout deploy-2026.07.09      # previous known-good tag
   docker compose up -d --build
   ```

---

## 5. Pre-Deployment Checks (on server, before first launch)

- [ ] **Ports free** — none of the published host ports are taken by existing
      containers: `sudo lsof -i :8765 -i :11434 -i :8081` and
      `docker ps --format '{{.Names}} {{.Ports}}'`. Remap via env if occupied.
- [ ] **Required env/secrets present** — `.env` created from `.env.example`;
      `SEARXNG_SECRET` regenerated (`openssl rand -hex 32`); `HUGGING_FACE_HUB_TOKEN`
      rotated; stale CosyVoice/VOICEVOX/Qwen3 keys removed.
- [ ] **vLLM image compatibility** — `docker image ls | grep vllm`; if enabling
      vLLM, confirm the tag matches the model (`Qwen2.5-*`) and driver.
- [ ] **GPU memory available** — `nvidia-smi` shows enough free VRAM for the new
      workload alongside existing GPU services; `device_ids`/`CUDA_VISIBLE_DEVICES`
      pinned to the intended GPU.
- [ ] **Disk space** — `df -h`; room for images, model weights, and ChromaDB
      volume growth.
- [ ] **NVIDIA runtime** — `docker run --rm --gpus all nvidia/cuda:12-base nvidia-smi`
      succeeds.
- [ ] **`server/Dockerfile` exists** and builds (blocker from code-changes plan).

---

## 6. Post-Deployment Validation

- [ ] **Container health** — `docker compose ps` shows `voice-server` healthy
      (after the health-port fix, this curls 8765): 
      `curl -f http://localhost:8765/health`.
- [ ] **Ollama model pulled** — `docker compose exec ollama ollama list` shows the
      configured model; if absent: `make ollama-pull`.
- [ ] **Remote client connectivity** — from the client device (or a simulated one):
      ```bash
      # health
      curl -f http://<server-ip>:8765/health
      # websocket handshake
      npx wscat -c ws://<server-ip>:8765/ws       # or: websocat ws://<server-ip>:8765/ws
      ```
- [ ] **Clean startup logs** — `docker compose logs voice-server` shows STT/LLM/RAG/TTS
      pre-load lines and no tracebacks; confirm the LLM chain isn't silently failing
      over from a disabled vLLM.
- [ ] **Rollback documented/tested** — verify a `git checkout <prev-tag> && docker
      compose up -d --build` returns to the prior release.

---

## 7. Additional Considerations

- **Firewall / port exposure** — expose only what the client needs: TCP **8765**
  (WS). Keep 11434 (ollama) and 8081 (searxng) bound to the Docker network / not
  published to the public interface (`127.0.0.1:8081:8080`), or firewall them
  (`ufw allow from <client-subnet> to any port 8765`).
- **TLS / reverse proxy** — the client speaks `ws://` (see `frontend/.env.example`).
  For any non-trusted network, front the server with nginx/Caddy terminating TLS
  and upgrade the client to `wss://`. CORS (`allow_origins`) must then list the
  real client origin, not `*` (see code-changes plan).
- **Monitoring/alerting** — scrape `/health` (extend it to report STT/LLM
  readiness); alert on container `unhealthy` and on GPU VRAM pressure via
  `nvidia-smi`/DCGM so this stack doesn't starve the server's other GPU jobs.
- **Backups** — `chroma_data/` (RAG vectors) and the `ollama_data` volume are the
  only persistent state. Snapshot `chroma_data/` and export the KB source in
  `building_kb/`; models are re-downloadable.
- **Update discipline** — every server change goes through `main` → `deploy/server`
  → tag → pull → rebuild (§4). No manual edits on the server. Pin image tags
  (avoid `:latest` for ollama/searxng/vllm) so rebuilds are reproducible.
