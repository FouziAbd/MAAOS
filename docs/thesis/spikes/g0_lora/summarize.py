"""Summarize Route B results (base vs LoRA) in the same columns as Route A. No model calls.

    python3 summarize.py      # prints the table and writes results/table.md
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "g0_dspy"))
import metric  # noqa: E402


def _valid(reply, repair):
    try:
        return not metric.validate.validate(metric.extract(reply, repair=repair))
    except Exception:
        return False


def main() -> None:
    lines = ["| condition | val metric | val valid | test metric | test rubric /12 (best) | test valid | "
             "val metric, repaired | val valid, repaired | test rubric, repaired (best) | test valid, repaired | sec/reply |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in sorted((HERE / "results").glob("*.json")):
        d = json.load(open(f))
        v, t = d["val"], d["test"]
        if not v or not t:
            continue
        secs = sum(r["seconds"] for r in v + t) / len(v + t)
        lines.append(
            f"| {f.stem} | {sum(r['score'] for r in v) / len(v):.2f} | {sum(_valid(r['reply'], False) for r in v)}/{len(v)} | "
            f"{sum(r['score'] for r in t) / len(t):.2f} | {sum(r['rubric'] for r in t) / len(t):.1f} ({max(r['rubric'] for r in t)}) | "
            f"{sum(r['valid'] for r in t)}/{len(t)} | {sum(r['score_repaired'] for r in v) / len(v):.2f} | "
            f"{sum(_valid(r['reply'], True) for r in v)}/{len(v)} | "
            f"{sum(r['rubric_repaired'] for r in t) / len(t):.1f} ({max(r['rubric_repaired'] for r in t)}) | "
            f"{sum(r['valid_repaired'] for r in t)}/{len(t)} | {secs:.0f} |")
    out = "\n".join(lines)
    (HERE / "results" / "table.md").write_text(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
