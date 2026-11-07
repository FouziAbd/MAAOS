"""G0 spike runner: ask each model for the CoopGrid-Jam-PO model, once per seed. OPT-IN.

Needs a running local ollama (http://localhost:11434) and MAAOS_LIVE_LM=1. A "-cloud" model
sends the prompt to Ollama's cloud service. Never run by the offline suite.

    MAAOS_LIVE_LM=1 python run_spike.py --models gemma4:e4b gemma3:27b-cloud --seeds 10
    python score.py results
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).parent
OLLAMA = "http://localhost:11434/api/chat"


def build_prompt() -> str:
    template = (HERE / "prompt.md").read_text()
    example = json.dumps(json.load(open(HERE / "example_lamp.json")), separators=(",", ":"))
    return template.replace("{{EXAMPLE}}", example).replace(
        "{{DESCRIPTION}}", (HERE / "description.md").read_text())


def ask(model: str, prompt: str, seed: int, temperature: float, json_mode: bool) -> dict:
    body = {"model": model, "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"seed": seed, "temperature": temperature,
                        "num_ctx": 16384, "num_predict": 8192}}
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as resp:
        return json.load(resp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--out", default=str(HERE / "results"))
    ap.add_argument("--free-text", action="store_true",
                    help="no ollama JSON mode; the JSON object is extracted from the reply")
    a = ap.parse_args()
    if os.environ.get("MAAOS_LIVE_LM") != "1":
        sys.exit("opt-in only: set MAAOS_LIVE_LM=1")
    prompt = build_prompt()
    for model in a.models:
        d = pathlib.Path(a.out) / (model.replace(":", "_").replace("/", "_")
                                   + ("_free" if a.free_text else ""))
        d.mkdir(parents=True, exist_ok=True)
        for seed in range(1, a.seeds + 1):
            if (d / f"seed{seed:02d}.meta.json").exists():
                continue
            t0 = time.time()
            try:
                r = ask(model, prompt, seed, a.temperature, json_mode=not a.free_text)
                text, err = r.get("message", {}).get("content", ""), None
            except Exception as e:  # recorded, not fatal: a failed call scores 0
                r, text, err = {}, "", repr(e)
            meta = {"model": model + (" (free text)" if a.free_text else " (JSON mode)"),
                    "seed": seed, "temperature": a.temperature,
                    "seconds": round(time.time() - t0, 1), "error": err,
                    "eval_count": r.get("eval_count"), "prompt_eval_count": r.get("prompt_eval_count")}
            (d / f"seed{seed:02d}.txt").write_text(text)
            (d / f"seed{seed:02d}.meta.json").write_text(json.dumps(meta, indent=1) + "\n")
            print(f"{model} seed {seed}: {meta['seconds']}s err={err}", flush=True)


if __name__ == "__main__":
    main()
