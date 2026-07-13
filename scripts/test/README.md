# Deployment test scripts

Probes that mimic each inference path so you can confirm the voice-server
deployment end to end, from both the **server** and a **remote client**.

| Script | Mimics | Run from | What it proves |
|--------|--------|----------|----------------|
| `check_deploy.sh` | — (health/connectivity) | server or remote | Container healthy; egress to LiteLLM + STT; funnel reachability |
| `test_llm.py` | `vllm_backend.py` | server | LiteLLM proxy serves the configured model (streaming) |
| `test_stt.py` | `remote_whisper_stt.py` | server | faster-whisper returns `verbose_json` with `language` + `no_speech_prob` |
| `test_ws.py` | full pipeline (`text_input`) | server **and** remote | voice-server → LiteLLM → TTS produces text **and** audio |

## Deps
```bash
pip install httpx websockets       # jq recommended for check_deploy.sh
```

## On the SERVER
All scripts auto-load `.env` from the repo root safely (inline comments, quotes,
and odd values are handled — do NOT `source .env`, that corrupts values). Just run:
```bash
cd ~/robo-deploy/voice-backend

./scripts/test/check_deploy.sh      # layered pass/fail overview
python scripts/test/test_llm.py     # LLM path (LiteLLM)
python scripts/test/test_stt.py     # STT path (add --wav speech.wav for a real transcript)
python scripts/test/test_ws.py --url ws://127.0.0.1:8765/ws   # full pipeline
```

## From a REMOTE client (through the Tailscale Funnel)
Internal Docker DNS (litellm / stt-fastwhisper) is NOT reachable remotely —
only the funnel is. So remotely you test the *product surface*, the WebSocket:
```bash
./scripts/test/check_deploy.sh --remote https://<machine>.<tailnet>.ts.net:8443
python scripts/test/test_ws.py --url wss://<machine>.<tailnet>.ts.net:8443/ws
```
A green `test_ws.py` over `wss://` means the whole chain works for real clients:
funnel TLS + WS upgrade → voice-server → LiteLLM (LLM) → Kokoro (TTS).

## Interpreting failures
- `test_llm.py` says model not advertised → `VLLM_MODEL_NAME` ≠ what LiteLLM
  serves; fix `.env` (the LLM would otherwise silently fail over to Ollama).
- `check_deploy.sh` STT/LLM egress ✗ → `SHARED_INFRA_NETWORK` / container alias
  wrong, or the URL uses the host loopback instead of the container name.
- `test_ws.py` connects but no `session_ack` → wrong path (must end in `/ws`).
- Remote health ✓ but WS ✗ → funnel isn't proxying the WebSocket upgrade.
- `test_ws.py` text ✓ but audio 0 bytes → TTS (Kokoro) not initialized; check
  `/health` `components` and voice-server logs.
