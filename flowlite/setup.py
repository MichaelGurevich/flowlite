"""One-time setup: download the speech model and make sure the local LLM is present.

This is the only step that touches the internet (Hugging Face for Whisper weights,
the Ollama registry for the LLM). No audio or text is ever sent anywhere.

    python -m flowlite.setup [--whisper small.en] [--llm llama3.2:3b]
"""

import argparse
import json
import urllib.request

from faster_whisper import download_model

from .formatter import OLLAMA_URL


def ollama_models():
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
        return {m["name"] for m in json.load(r)["models"]}


def ollama_pull(name):
    req = urllib.request.Request(f"{OLLAMA_URL}/api/pull", json.dumps({"name": name}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        last = None
        for line in r:
            status = json.loads(line).get("status")
            if status != last:
                print(f"  {status}")
                last = status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default="base.en")
    ap.add_argument("--llm", default="llama3.2:3b")
    args = ap.parse_args()

    print(f"Downloading Whisper model '{args.whisper}' (cached under ~/.cache/huggingface)...")
    path = download_model(args.whisper)
    print(f"  ok: {path}")
    if not args.whisper.endswith(".en"):
        print("Downloading the tiny model used for fast language detection...")
        print(f"  ok: {download_model('tiny')}")

    print(f"Checking Ollama model '{args.llm}'...")
    try:
        models = ollama_models()
    except OSError:
        print("  Ollama is not running. Install it from ollama.com, start it, then re-run setup.")
        return
    if args.llm in models or f"{args.llm}:latest" in models:
        print("  ok: already installed")
    else:
        ollama_pull(args.llm)
    print("Setup complete. From now on FlowLite runs fully offline.")


if __name__ == "__main__":
    main()
