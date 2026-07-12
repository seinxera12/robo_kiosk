#!/usr/bin/env python3
"""
LLM inference probe — mimics server/llm/vllm_backend.py.

Sends an OpenAI-compatible streaming chat completion to the LiteLLM proxy
(the same call the voice-server makes) and prints the streamed reply.

Run ON THE SERVER (reaches litellm over the Docker network) or anywhere the
proxy URL is reachable.

Usage:
  python test_llm.py
  python test_llm.py --url http://litellm:4000/v1 --model <id> --key sk-...
  python test_llm.py --prompt "What floor is the cafeteria on?"

Defaults come from env (VLLM_BASE_URL / VLLM_MODEL_NAME / VLLM_API_KEY) so on
the server you can just:  set -a; . ./.env; set +a; python test_llm.py
"""
import argparse
import os
import sys
import time

import httpx

from _env import load_dotenv
load_dotenv()  # populate os.environ from ./.env (safe: ignores comments/quotes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("VLLM_BASE_URL", "http://litellm:4000/v1"),
                    help="OpenAI-compatible base URL (must end in /v1)")
    ap.add_argument("--model", default=os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct-AWQ"))
    ap.add_argument("--key", default=os.getenv("VLLM_API_KEY", "local"))
    ap.add_argument("--prompt", default="Say 'deployment OK' and nothing else.")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    base = args.url.rstrip("/")
    endpoint = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {args.key}", "Content-Type": "application/json"}
    body = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "stream": True,
        "max_tokens": 64,
        "temperature": 0.3,
    }

    print(f"→ POST {endpoint}")
    print(f"  model={args.model!r}  prompt={args.prompt!r}")

    # First, list models (same as VLLMBackend.ping) to catch model-name mismatch.
    try:
        r = httpx.get(f"{base}/models", headers=headers, timeout=args.timeout)
        r.raise_for_status()
        ids = [m.get("id") for m in r.json().get("data", [])]
        if args.model in ids:
            print(f"  ✓ model advertised by proxy")
        else:
            print(f"  ✗ model NOT advertised; available: {ids}")
    except Exception as e:
        print(f"  ✗ /models probe failed: {e}")
        return 1

    t0 = time.time()
    first_token_at = None
    reply = []
    try:
        with httpx.stream("POST", endpoint, headers=headers, json=body, timeout=args.timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                import json
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except Exception:
                    continue
                if delta:
                    if first_token_at is None:
                        first_token_at = time.time() - t0
                    reply.append(delta)
                    sys.stdout.write(delta); sys.stdout.flush()
    except Exception as e:
        print(f"\n  ✗ streaming failed: {e}")
        return 1

    total = time.time() - t0
    text = "".join(reply).strip()
    print(f"\n\n  ✓ reply: {text!r}")
    print(f"  ttft={first_token_at:.2f}s  total={total:.2f}s  chars={len(text)}")
    return 0 if text else 1


if __name__ == "__main__":
    sys.exit(main())
