"""Evaluate the base checkpoint or base + LoRA adapter on the T2b validation items (seed 1) and on
10 seeded CoopGrid-Jam-PO test runs, with the same scoring as Route A. Same runtime for both
(transformers, 4-bit nf4 on the GPU), so the comparison isolates the fine-tuning.

    ~/.venvs/maaos-ft/bin/python generate_eval.py --name base
    ~/.venvs/maaos-ft/bin/python generate_eval.py --name lora_r16 --adapter adapters/r16
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import torch

import common

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "g0_dspy"))
sys.path.insert(0, str(HERE.parent / "g0_structure"))
import metric  # noqa: E402
import score as rubric  # noqa: E402
from make_data import user_turn  # noqa: E402


def generate(tok, model, user, seed, max_new):
    text = common.prompt_text(tok, user)
    ids = tok(text, return_tensors="pt", add_special_tokens=False).to(model.device)
    torch.manual_seed(seed)
    with torch.no_grad():
        out = model.generate(**ids, do_sample=True, temperature=0.7, top_p=0.95, top_k=64,
                             max_new_tokens=max_new, pad_token_id=tok.pad_token_id or tok.eos_token_id)
    return tok.decode(out[0, ids["input_ids"].shape[1]:], skip_special_tokens=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--max-new", type=int, default=6144)
    a = ap.parse_args()
    out_path = HERE / "results" / f"{a.name}.json"
    out_path.parent.mkdir(exist_ok=True)
    done = json.load(open(out_path)) if out_path.exists() else {"val": [], "test": []}
    tok, model = common.load(adapter=a.adapter)
    val = [json.loads(l) for l in open(HERE / "data" / "val.jsonl")]
    gold = {it["id"]: it["model"] for it in json.load(open(HERE.parent / "g0_dspy" / "corpus.json"))}
    true = json.load(open(HERE.parent / "g0_structure" / "coopgrid_jam_po_true.json"))
    for q in true["domain"]["parameters"]:
        q.pop("value", None)
    desc = (HERE.parent / "g0_structure" / "description.md").read_text()
    have_v = {r["id"] for r in done["val"]}
    for it in val:
        if it["id"] in have_v:
            continue
        t = time.time()
        reply = generate(tok, model, it["messages"][0]["content"], 1, a.max_new)
        s, fb = metric.compare(gold[it["id"]], reply)
        sr, _ = metric.compare(gold[it["id"]], reply, repair=True)
        done["val"].append({"id": it["id"], "score": s, "score_repaired": sr, "seconds": round(time.time() - t, 1),
                            "feedback": fb[:400], "reply": reply})
        out_path.write_text(json.dumps(done, indent=1) + "\n")
        print(f"[{a.name}] val {it['id']} {s:.3f} repaired {sr:.3f}", flush=True)
    have_t = {r["seed"] for r in done["test"]}
    for seed in range(1, 11):
        if seed in have_t:
            continue
        t = time.time()
        reply = generate(tok, model, user_turn(desc), seed, a.max_new)
        s, fb = metric.compare(true, reply)
        row = {"seed": seed, "score": s, "seconds": round(time.time() - t, 1), "feedback": fb[:400], "reply": reply}
        for rep in (False, True):
            try:
                checks, errs = rubric.score(metric.extract(reply, repair=rep))
                row[f"rubric{'_repaired' if rep else ''}"] = sum(checks.values())
                row[f"valid{'_repaired' if rep else ''}"] = not errs
            except Exception:
                row[f"rubric{'_repaired' if rep else ''}"] = 0
                row[f"valid{'_repaired' if rep else ''}"] = False
        done["test"].append(row)
        out_path.write_text(json.dumps(done, indent=1) + "\n")
        print(f"[{a.name}] test seed {seed} rubric {row['rubric']} (repaired {row['rubric_repaired']}) "
              f"valid {row['valid']}", flush=True)


if __name__ == "__main__":
    main()
