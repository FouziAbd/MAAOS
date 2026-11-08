"""Re-score stored ladder replies, strict and after json_repair, without calling any model.

    python rescore.py        # prints the table and writes results/table.md
"""
from __future__ import annotations

import json
import pathlib
import sys

import metric

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "g0_structure"))
import score as rubric  # noqa: E402
from run_ladder import RUNGS, load  # noqa: E402


def _valid(reply, repair):
    try:
        return not metric.validate.validate(metric.extract(reply, repair=repair))
    except Exception:
        return False


def _rubric(reply, repair):
    try:
        checks, _ = rubric.score(metric.extract(reply, repair=repair))
        return sum(checks.values())
    except Exception:
        return 0


def main() -> None:
    train, val, true, _ = load()
    gold = {ex.id: ex.gold for ex in val}
    lines = ["| rung | val metric | val valid | test metric | test rubric /12 (best) | test valid | "
             "val metric, repaired | val valid, repaired | test rubric, repaired (best) | test valid, repaired |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name in RUNGS:
        f = HERE / "results" / f"{name}.json"
        if not f.exists():
            continue
        d = json.load(open(f))
        v, te = d["val"], d["test"]
        row = {}
        for rep in (False, True):
            vm = sum(metric.compare(gold[r["id"]], r["reply"], repair=rep)[0] for r in v) / len(v)
            vv = sum(_valid(r["reply"], rep) for r in v)
            tm = sum(metric.compare(true, r["reply"], repair=rep)[0] for r in te) / len(te)
            tr = [_rubric(r["reply"], rep) for r in te]
            tv = sum(_valid(r["reply"], rep) for r in te)
            row[rep] = (vm, vv, tm, sum(tr) / len(tr), max(tr), tv)
        s, r = row[False], row[True]
        lines.append(f"| {name} | {s[0]:.2f} | {s[1]}/10 | {s[2]:.2f} | {s[3]:.1f} ({s[4]}) | {s[5]}/10 | "
                     f"{r[0]:.2f} | {r[1]}/10 | {r[3]:.1f} ({r[4]}) | {r[5]}/10 |")
    out = "\n".join(lines)
    (HERE / "results" / "table.md").write_text(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
