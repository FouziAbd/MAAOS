"""G0 DSPy ladder (thesis phase T2b, Route A). OPT-IN: MAAOS_LIVE_LM=1, local ollama, gemma4:e4b.

Rungs, each evaluated on the 10 validation pairs and on 10 seeded CoopGrid-Jam-PO test runs:
  zero_shot   the format rules only
  fewshot_1   + 1 labelled training example
  fewshot_3   + 3 labelled training examples (round-robin over families)
  bootstrap   BootstrapFewShot: demos the model itself produced that scored >= 0.9
  gepa        GEPA reflective instruction search, started from fewshot_3
CoopGrid-Jam-PO is never in the training or validation data.

    MAAOS_LIVE_LM=1 python run_ladder.py [--rungs zero_shot fewshot_1 ...] [--gepa-calls 100]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import dspy
from dspy.teleprompt import BootstrapFewShot, LabeledFewShot

import metric
import program

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "g0_structure"))
import score as rubric  # noqa: E402  (the T2 12-point rubric, for comparability)

OUT = HERE / "results"
RUNGS = ["zero_shot", "fewshot_1", "fewshot_3", "bootstrap", "gepa"]


def load():
    items = json.load(open(HERE / "corpus.json"))
    def mk(it):  # model_json is the demo's output field; without it DSPy drops the demo as incomplete
        return dspy.Example(description=it["description"], gold=it["model"], id=it["id"],
                            model_json=json.dumps(it["model"], separators=(",", ":"))).with_inputs("description")
    train = [it for it in items if it["split"] == "train"]
    families = sorted({it["family"] for it in train})
    by_fam = {f: [it for it in train if it["family"] == f] for f in families}
    order = ["device", "lid", "rooms", "lift", "node"]
    robin = [by_fam[f][k] for k in range(max(map(len, by_fam.values()))) for f in order if k < len(by_fam[f])]
    val = [it for it in items if it["split"] == "val"]
    true = json.load(open(HERE.parent / "g0_structure" / "coopgrid_jam_po_true.json"))
    for q in true["domain"]["parameters"]:
        q.pop("value", None)
    desc = (HERE.parent / "g0_structure" / "description.md").read_text()
    return [mk(it) for it in robin], [mk(it) for it in val], true, desc


def gepa_metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
    """Structure is scored after json_repair (so the search sees a gradient); a reply that needed
    repair keeps only 70% of it. The feedback names the syntax slip and the structural gaps."""
    reply = getattr(pred, "model_json", "") or ""
    strict, strict_fb = metric.compare(gold.gold, reply)
    repaired, repaired_fb = metric.compare(gold.gold, reply, repair=True)
    if strict_fb.startswith("The reply is not"):
        return dspy.Prediction(score=round(0.7 * repaired, 4),
                               feedback=strict_fb + " After repairing the syntax: " + repaired_fb)
    return dspy.Prediction(score=strict, feedback=strict_fb)


def boot_metric(gold, pred, trace=None):
    return metric.compare(gold.gold, getattr(pred, "model_json", "") or "")[0] >= 0.9


def _raw_reply(lm) -> str:
    """The model's own text from the last call, for replies DSPy's field parser rejected."""
    if not lm.history:
        return ""
    outs = lm.history[-1].get("outputs") or [""]
    first = outs[0]
    return first.get("text", "") if isinstance(first, dict) else str(first)


def run(prog, description, seed):
    lm = program.local_lm().copy(seed=seed)
    with dspy.context(lm=lm):
        t = time.time()
        try:
            out = prog(description=description).model_json
            err = None
        except Exception as e:  # the parser rejected the reply: score the raw text instead
            out, err = _raw_reply(lm), "parser: " + repr(e)[:200]
        return out, round(time.time() - t, 1), err


def _valid(reply: str) -> bool:
    try:
        return not metric.validate.validate(metric.extract(reply))
    except Exception:
        return False


def evaluate(name, prog, val, true, desc):
    rows = {"val": [], "test": []}
    for ex in val:
        out, secs, err = run(prog, ex.description, seed=1)
        s, fb = metric.compare(ex.gold, out)
        rows["val"].append({"id": ex.id, "score": s, "valid": _valid(out), "seconds": secs, "error": err,
                            "feedback": fb[:400], "reply": out})
        print(f"[{name}] val {ex.id} {s:.3f} {secs}s", flush=True)
    for seed in range(1, 11):
        out, secs, err = run(prog, desc, seed=seed)
        s, fb = metric.compare(true, out)
        try:
            checks, errs = rubric.score(metric.extract(out))
        except Exception:
            checks, errs = {k: False for k in rubric.CHECKS}, ["not parseable"]
        rows["test"].append({"seed": seed, "score": s, "rubric": sum(checks.values()), "checks": checks,
                             "valid": not errs, "seconds": secs, "error": err, "feedback": fb[:400], "reply": out})
        print(f"[{name}] test seed {seed} metric {s:.3f} rubric {sum(checks.values())}/12 {secs}s", flush=True)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rungs", nargs="+", default=RUNGS)
    ap.add_argument("--gepa-calls", type=int, default=100)
    a = ap.parse_args()
    if os.environ.get("MAAOS_LIVE_LM") != "1":
        sys.exit("opt-in only: set MAAOS_LIVE_LM=1")
    OUT.mkdir(exist_ok=True)
    dspy.configure(lm=program.local_lm(), adapter=dspy.ChatAdapter(use_json_adapter_fallback=False))
    train, val, true, desc = load()
    for name in a.rungs:
        if (OUT / f"{name}.json").exists():
            print(f"[{name}] already done", flush=True)
            continue
        t0 = time.time()
        prog = program.ModelStructureGenerator()
        if name == "fewshot_1":
            prog = LabeledFewShot(k=1).compile(prog, trainset=train, sample=False)
        elif name == "fewshot_3":
            prog = LabeledFewShot(k=3).compile(prog, trainset=train, sample=False)
        elif name == "bootstrap":
            prog = BootstrapFewShot(metric=boot_metric, max_bootstrapped_demos=2, max_labeled_demos=2,
                                    max_rounds=1).compile(prog, trainset=train[:15])
        elif name == "gepa":
            base = LabeledFewShot(k=3).compile(program.ModelStructureGenerator(), trainset=train, sample=False)
            reflection = program.reflection_lm()
            prog = dspy.GEPA(metric=gepa_metric, reflection_lm=reflection, max_metric_calls=a.gepa_calls,
                             track_stats=True, seed=0).compile(base, trainset=train[3:15], valset=val)
        compile_s = round(time.time() - t0, 1)
        prog.save(str(OUT / f"{name}.program.json"))
        rows = evaluate(name, prog, val, true, desc)
        summary = {
            "rung": name, "compile_seconds": compile_s,
            "val_mean": round(sum(r["score"] for r in rows["val"]) / len(rows["val"]), 4),
            "val_valid": sum(r["valid"] for r in rows["val"]),
            "test_metric_mean": round(sum(r["score"] for r in rows["test"]) / 10, 4),
            "test_rubric_mean": round(sum(r["rubric"] for r in rows["test"]) / 10, 2),
            "test_rubric_best": max(r["rubric"] for r in rows["test"]),
            "test_valid": sum(r["valid"] for r in rows["test"]),
        }
        (OUT / f"{name}.json").write_text(json.dumps({"summary": summary, **rows}, indent=1) + "\n")
        print(f"[{name}] SUMMARY {json.dumps(summary)}", flush=True)


if __name__ == "__main__":
    main()
