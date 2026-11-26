"""Ollama connectivity + completion test CLI — for TESTING the Ollama
provider without switching the app's active provider.

This does NOT touch `llm_provider` in settings, so Anthropic/whatever is
currently configured keeps being what the app and every agent actually
use. It only exercises adapters.llm_ollama.OllamaProvider directly (the
same class llm_factory.get_provider('ollama') would build), optionally
saving the host/model choice to the ollama_* settings keys so they're
ready if you later flip llm_provider to 'ollama' from the Settings UI.

Usage:
    python test_ollama.py --url http://localhost:11434
    python test_ollama.py --url http://192.168.1.50:11434 --model llama3.1:70b
    python test_ollama.py --url http://192.168.1.50:11434 --save   # persist to settings
    python test_ollama.py --url http://192.168.1.50:11434 --prompt "list P&ID valve types"

Exit codes: 0 ok, 1 unreachable, 2 reachable but completion failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STUDIO_DIR = Path(__file__).parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

DEFAULT_PROMPT = (
    "Reply with exactly one word: are you online? Answer 'yes'."
)


def probe_tags(base_url: str, timeout: float = 3.0) -> dict:
    """GET /api/tags — lists locally pulled models. The cheapest possible
    reachability + "is this actually Ollama" check."""
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    req = urllib.request.Request(f"{url}/api/tags",
                                 headers={"User-Agent": "studio-ollama-test"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def format_models(tags_response: dict) -> list[str]:
    return [m.get("name", "?") for m in tags_response.get("models", [])]


def run_completion(base_url: str, model: str, prompt: str,
                   tier: str = "fast", max_tokens: int = 200) -> tuple[str, float]:
    """Real completion via the app's own OllamaProvider class — proves
    the exact code path the agents would use, not a hand-rolled request."""
    from adapters.llm_ollama import OllamaProvider
    provider = OllamaProvider(base_url=base_url,
                              model_fast=model, model_smart=model)
    t0 = time.monotonic()
    resp = provider.complete(prompt, max_tokens=max_tokens, tier=tier)
    elapsed = time.monotonic() - t0
    return resp.text, elapsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:11434",
                    help="Ollama base URL, e.g. http://192.168.1.50:11434 for a Mac Mini")
    ap.add_argument("--model", default=None,
                    help="Model name to test with (default: whatever's already "
                         "in ollama_model_fast, or qwen2.5:3b-instruct)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=3.0,
                    help="Reachability probe timeout, seconds")
    ap.add_argument("--save", action="store_true",
                    help="Persist --url/--model to the settings table "
                         "(ollama_url / ollama_model_fast) WITHOUT changing "
                         "the active llm_provider")
    ap.add_argument("--hub", default=None,
                    help="ENGINEERING_HUB path (needed for --save; reads/"
                         "writes studio.db's settings table)")
    args = ap.parse_args()

    print(f"[1/3] Probing {args.url} ...")
    try:
        tags = probe_tags(args.url, timeout=args.timeout)
    except urllib.error.URLError as e:
        print(f"  UNREACHABLE: {e}")
        print("  Check: Ollama running on that host? Same network? "
              "Firewall open on port 11434?")
        return 1
    except Exception as e:
        print(f"  UNREACHABLE: {e}")
        return 1

    models = format_models(tags)
    print(f"  OK — server responding. {len(models)} model(s) pulled:")
    for m in models:
        print(f"    - {m}")

    model = args.model
    if not model:
        if models:
            model = models[0]
            print(f"  No --model given; using first available: {model}")
        else:
            print("  No --model given and no models pulled on that host. "
                 "Run `ollama pull <model>` there first, or pass --model.")
            return 1

    if args.save:
        if not args.hub:
            print("  --save requires --hub (points at the folder containing "
                 "studio.db)")
            return 1
        import os
        os.environ["ENGINEERING_HUB"] = args.hub
        from adapters.config import save_config
        # Both tiers: Ollama models are typically one size class, not a
        # fast/smart pair like the hosted APIs (this mirrors the same
        # both-tiers choice llm_factory.get_provider('ollama') makes for
        # OLLAMA_MODEL) — saving only ollama_model_fast left the smart
        # tier silently pointed at whatever default/prior value was there.
        save_config({"ollama_url": args.url, "ollama_model_fast": model,
                     "ollama_model_smart": model})
        print(f"[2/3] Saved ollama_url={args.url}, model={model} "
             "(both fast and smart tiers) to settings (llm_provider "
             "unchanged — still using whatever the app is currently set to).")
    else:
        print("[2/3] --save not passed; not touching studio.db settings.")

    print(f"[3/3] Running a real completion against '{model}' "
         f"via adapters.llm_ollama.OllamaProvider ...")
    try:
        text, elapsed = run_completion(args.url, model, args.prompt,
                                       max_tokens=args.max_tokens)
    except Exception as e:
        print(f"  Reachable, but completion FAILED: {e}")
        print("  Common cause: model not vision-capable if you intended "
             "an image call, or model name typo'd vs `ollama list`.")
        return 2

    print(f"  OK — {elapsed:.1f}s")
    print(f"  Prompt:   {args.prompt!r}")
    print(f"  Response: {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
