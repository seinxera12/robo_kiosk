#!/usr/bin/env bash
# =============================================================================
# Deployment status checker for the voice-server stack.
#
# Runs layered connectivity/health checks. Two modes:
#
#   Server-side (default) — run ON the deployment host. Checks the internal
#   Docker-network endpoints (LiteLLM, faster-whisper) via `docker compose exec`
#   plus the loopback health port.
#
#   Remote — run from a client machine. Checks reachability through the
#   Tailscale Funnel (HTTPS/WSS) only; it cannot see internal Docker DNS.
#
# Usage:
#   ./check_deploy.sh                         # server-side, defaults
#   ./check_deploy.sh --remote https://<machine>.<tailnet>.ts.net:8443
#
# Env overrides (server mode):
#   COMPOSE_SERVICE   voice-server            compose service name
#   HEALTH_URL        http://127.0.0.1:8765/health
#   STT_URL           http://stt-fastwhisper:8000/health
#   LLM_URL           http://litellm:4000/v1/models
#   VLLM_API_KEY      (from .env)             bearer token for LiteLLM
# =============================================================================
set -uo pipefail

MODE="server"
BASE_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) MODE="remote"; BASE_URL="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

# ---- pretty pass/fail -------------------------------------------------------
PASS=0; FAIL=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
head() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# Load .env if present (server mode) so VLLM_API_KEY etc. are available.
if [[ -f .env ]]; then set -a; . ./.env; set +a; fi

COMPOSE_SERVICE="${COMPOSE_SERVICE:-voice-server}"

# dexec: run a command inside the voice-server container.
dexec() { docker compose exec -T "$COMPOSE_SERVICE" "$@"; }

# ---------------------------------------------------------------------------
if [[ "$MODE" == "remote" ]]; then
  if [[ -z "$BASE_URL" ]]; then
    echo "Remote mode needs a base URL, e.g. --remote https://host.ts.net:8443"; exit 2
  fi
  WS_URL="${BASE_URL/https:/wss:}/ws"
  HTTP_HEALTH="${BASE_URL}/health"

  head "Remote reachability (through funnel)"
  if curl -fsS --max-time 10 "$HTTP_HEALTH" >/tmp/_h.json 2>/dev/null; then
    ok "GET $HTTP_HEALTH -> 200"
    if command -v jq >/dev/null; then
      status=$(jq -r '.status // "?"' /tmp/_h.json)
      comps=$(jq -rc '.components // {}' /tmp/_h.json)
      [[ "$status" == "healthy" ]] && ok "health status=healthy" || bad "health status=$status"
      echo "     components: $comps"
    fi
  else
    bad "GET $HTTP_HEALTH unreachable (funnel not pointing at voice-server? TLS? port?)"
  fi

  head "WebSocket handshake"
  echo "  Run the end-to-end WS probe from the client:"
  echo "    python scripts/test/test_ws.py --url $WS_URL"

  printf '\n\033[1mRESULT:\033[0m %d passed, %d failed\n' "$PASS" "$FAIL"
  [[ $FAIL -eq 0 ]] && exit 0 || exit 1
fi

# ---------------------------------------------------------------------------
# Server-side checks
# ---------------------------------------------------------------------------
head "Container status"
if docker compose ps "$COMPOSE_SERVICE" 2>/dev/null | grep -qiE "up|running"; then
  state=$(docker compose ps "$COMPOSE_SERVICE" --format '{{.Status}}' 2>/dev/null)
  ok "voice-server: $state"
  echo "$state" | grep -qi "healthy" && ok "health check: healthy" \
    || bad "health check not passing yet (allow ~180s start_period)"
else
  bad "voice-server not running (docker compose ps)"
fi

head "Local health endpoint"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8765/health}"
if curl -fsS --max-time 10 "$HEALTH_URL" >/tmp/_h.json 2>/dev/null; then
  ok "GET $HEALTH_URL -> 200"
  if command -v jq >/dev/null; then
    jq -r '.components // {} | to_entries[] | "     \(.key)=\(.value)"' /tmp/_h.json
    jq -e '.components | to_entries | all(.value=="ready")' /tmp/_h.json >/dev/null 2>&1 \
      && ok "all components ready" || bad "some components not ready"
  fi
else
  bad "GET $HEALTH_URL failed (is the host port bound to 127.0.0.1?)"
fi

head "Egress: STT service (from inside voice-server)"
STT_URL="${STT_URL:-http://stt-fastwhisper:8000/health}"
if dexec curl -fsS --max-time 10 "$STT_URL" >/dev/null 2>&1; then
  ok "reach $STT_URL"
else
  bad "cannot reach $STT_URL (shared network name / container alias?)"
fi

head "Egress: LiteLLM proxy + model presence"
LLM_URL="${LLM_URL:-http://litellm:4000/v1/models}"
AUTH="Authorization: Bearer ${VLLM_API_KEY:-local}"
if dexec curl -fsS --max-time 10 -H "$AUTH" "$LLM_URL" >/tmp/_m.json 2>&1; then
  ok "reach $LLM_URL"
  if command -v jq >/dev/null && [[ -n "${VLLM_MODEL_NAME:-}" ]]; then
    if jq -e --arg m "$VLLM_MODEL_NAME" '.data[]?.id == $m' /tmp/_m.json >/dev/null 2>&1; then
      ok "model '$VLLM_MODEL_NAME' advertised by proxy"
    else
      bad "model '$VLLM_MODEL_NAME' NOT in proxy model list — LLM will fail over to Ollama"
      echo "     advertised: $(jq -rc '[.data[]?.id]' /tmp/_m.json 2>/dev/null)"
    fi
  fi
else
  bad "cannot reach $LLM_URL (network / api key?)"
fi

printf '\n\033[1mRESULT:\033[0m %d passed, %d failed\n' "$PASS" "$FAIL"
echo "Next: python scripts/test/test_llm.py   and   scripts/test/test_stt.py   and   scripts/test/test_ws.py"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
