# Task: Deployment Readiness Audit & Plan for Backend-Only Remote Deployment

## Context
- The project was just cleaned up to contain only the features/services/configs in active use.
- Target environment: remote Ubuntu server.
  - Docker is already installed and running other unrelated services.
  - NVIDIA/CUDA drivers are already installed and working.
  - vLLM (and possibly other) Docker images are already pulled.
- The frontend is **not** deployed to the server. It runs on a separate client device and only needs network access to the backend.
- All code changes must happen in this local repo — no manual edits on the server.

## Objective
Produce two deliverables:
1. `DEPLOYMENT_CODE_CHANGES.md` — a plan of local code/config changes needed for deployment readiness.
2. `DEPLOYMENT_GUIDE.md` — a step-by-step guide for migrating to and operating on the remote server.

**Do not modify code in this pass.** This is an audit + planning task only.

---

## Step 1: Repository Audit

Explore and document the following, in order:

1. **Structure map** — list top-level directories/files and their purpose (backend, frontend, docker, scripts, configs).
2. **Service inventory** — every Docker service/container defined (compose files, Dockerfiles), what it does, its ports, its dependencies on other services.
3. **Frontend/backend boundary** — identify every point where frontend and backend are coupled (shared env vars, shared network, hardcoded URLs, shared build steps, shared docker-compose).
4. **Config & secrets inventory** — list all `.env`, config files, and any hardcoded secrets/paths/URLs/ports found in code or configs.
5. **Network inventory** — internal Docker networks, exposed ports, any assumptions of localhost/co-located frontend-backend communication.
6. **GPU/resource inventory** — how vLLM or other GPU-using services request/limit GPU resources currently.

Output this as an **Audit Findings** section (can be inline in your response or a separate `AUDIT.md` — your choice, but must exist before proceeding).

---

## Step 2: Identify Deployment Blockers

For each item found in Step 1, flag issues in this checklist format:

| # | Issue | Location (file/service) | Why it blocks deployment | Severity (Blocker/Warning/Nice-to-have) |
|---|-------|--------------------------|---------------------------|-------------------------------------------|

Explicitly check for, at minimum:
- [ ] Hardcoded localhost / local IPs / local file paths
- [ ] Dev-only configs mixed with prod-required configs
- [ ] Secrets committed in repo or docker-compose files
- [ ] Missing `.env.example` / unclear required env vars
- [ ] CORS or network config that assumes frontend and backend are co-located
- [ ] Port numbers that may collide with existing services on the server
- [ ] Missing container restart policies
- [ ] Missing/incomplete health checks
- [ ] No GPU memory/resource scoping for vLLM (risk of conflicting with other GPU workloads)
- [ ] No logging/log rotation strategy
- [ ] Frontend build artifacts or dependencies bundled into backend-deployable paths
- [ ] Anything else discovered during the audit not listed above

---

## Step 3: `DEPLOYMENT_CODE_CHANGES.md`

For every flagged blocker/warning from Step 2, write an entry using this exact template:

```md
### [Issue Title]
- **Problem:** ...
- **Impact if unresolved:** ...
- **Proposed fix:** ...
- **Files affected:** ...
- **Risk of fix (if any):** ...
```

Group entries under these headers, in this order:
1. Backend/Frontend Decoupling
2. Environment & Secrets Management
3. Docker & Networking (ports, restart policies, health checks)
4. GPU / Resource Scoping (vLLM coexistence with other server workloads)
5. Logging & Observability
6. Miscellaneous

---

## Step 4: `DEPLOYMENT_GUIDE.md`

Write this guide using the exact section structure below.

### 1. Migration Method
- Compare **git-based deploy** (clone/pull via dedicated branch or tag) vs **rsync**.
- Recommend one for this project, with justification.
- Provide exact commands for the recommended method.

### 2. Branching Strategy
- Propose a git branching/tagging model, e.g.:
  - `main` — full source of truth (includes frontend)
  - `deploy/server` (or a release tag) — backend-only deployable snapshot
- Describe exactly how frontend code/artifacts are excluded from what reaches the server (build step, sparse checkout, subtree, exclude list — pick one and justify).

### 3. File Handling Rules
Provide three explicit lists:
- **Never send to server** (e.g. frontend source, dev tooling, local secrets)
- **Send but handle differently** (e.g. `.env.production` created on server, not committed)
- **Send as-is**

Include concrete `.gitignore` / `.dockerignore` / rsync `--exclude` entries.

### 4. Sync Workflow (ongoing changes)
Step-by-step procedure for pushing future local changes to the server:
1. Local: commit → merge/tag into deploy branch
2. Transfer step (git pull or rsync command)
3. Server: rebuild/restart steps
4. Versioning/tagging convention
5. Rollback procedure (previous tag/commit + redeploy command)

### 5. Pre-Deployment Checks (run on server before first launch)
Checklist format:
- [ ] Docker network/port availability confirmed (no collision with existing containers)
- [ ] Required env vars/secrets present
- [ ] vLLM image version compatibility confirmed
- [ ] GPU memory availability confirmed for new workload alongside existing ones
- [ ] Disk space sufficient for images/volumes

### 6. Post-Deployment Validation
Checklist format:
- [ ] Container health checks passing
- [ ] Connectivity test from a simulated remote client (command/example included)
- [ ] Logs show clean startup, no errors
- [ ] Rollback tested or documented

### 7. Additional Considerations
Address explicitly (add more if discovered during audit):
- Firewall / port exposure rules
- TLS / reverse proxy needs for client → server communication
- Monitoring/alerting recommendations
- Backup strategy for volumes/persistent data
- Update/versioning discipline going forward

---

## Constraints
- No code changes in this pass — audit and planning only.
- Every claim in the plans must trace back to something found in the actual codebase, not assumptions.
- If information is missing/ambiguous (e.g. unclear which ports are free on the server), state the assumption explicitly rather than guessing silently.
- Output both files as actual markdown files in the repo (or `/mnt/user-data/outputs` if this is a sandboxed session), not just chat text.