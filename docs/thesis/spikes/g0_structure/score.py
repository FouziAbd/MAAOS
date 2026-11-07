"""Score generated CoopGrid-Jam-PO models (G0 spike). Name-agnostic structural rubric.

Usage: python score.py results/   -> writes results/summary.json and prints a markdown table.
The true model (coopgrid_jam_po_true.json) must score 12/12; that is checked first.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from fractions import Fraction
from typing import Any, Dict, List, Tuple

import validate

SKILLS = {"Goto": 2, "Enter": 2, "CooperateOpen": 3, "ClearJam": 3}
CHECKS = [
    "json", "schema_valid", "skill_vocabulary", "one_hidden_var", "hidden_prior_param",
    "pull_stochastic", "shake_frees_hidden", "rattle_noisy", "numbers_withheld",
    "rewards_transcribed", "corridor_refusals", "goal_both_agents",
]


def _extract(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _frac(x: Any) -> Fraction | None:
    try:
        return Fraction(str(x))
    except (ValueError, ZeroDivisionError):
        return None


def _skill(doc: Dict[str, Any], name: str) -> Dict[str, Any]:
    for s in doc["domain"].get("skills", []) or []:
        if isinstance(s, dict) and s.get("name") == name:
            return s
    return {}


def _hidden(doc: Dict[str, Any]) -> set:
    return {p["name"] for p in doc["domain"].get("predicates", []) or []
            if isinstance(p, dict) and p.get("observable", True) is False}


def _uses_hidden(cases: Any, hidden: set) -> bool:
    for c in cases or []:
        for a in (c.get("when") or []) if isinstance(c, dict) else []:
            if isinstance(a, dict) and isinstance(a.get("literal"), dict) \
                    and a["literal"].get("name") in hidden:
                return True
    return False


def _param_bernoulli(cases: Any) -> bool:
    for c in cases or []:
        d = c.get("distribution", {}) if isinstance(c, dict) else {}
        b = d.get("bernoulli") if isinstance(d, dict) else None
        if isinstance(b, dict) and isinstance(b.get("p"), dict) and "parameter" in b["p"]:
            return True
    return False


def score(doc: Any) -> Tuple[Dict[str, bool], List[str]]:
    r = {k: False for k in CHECKS}
    r["json"] = True
    errs = validate.validate(doc)
    r["schema_valid"] = not errs
    if not isinstance(doc, dict) or not isinstance(doc.get("domain"), dict) \
            or not isinstance(doc.get("problem"), dict):
        return r, errs
    try:
        have = {s["name"]: len(s.get("parameters", [])) for s in doc["domain"].get("skills", [])}
        r["skill_vocabulary"] = have == SKILLS
        hidden = _hidden(doc)
        r["one_hidden_var"] = len(hidden) == 1
        hp = doc["problem"].get("hidden_prior") or []
        r["hidden_prior_param"] = bool(hp) and all(
            isinstance(h.get("p"), dict) and "parameter" in h["p"] for h in hp)
        co = _skill(doc, "CooperateOpen")
        r["pull_stochastic"] = len(co.get("outcomes") or []) >= 2 \
            and _uses_hidden(co.get("outcome_cases"), hidden) \
            and _param_bernoulli(co.get("outcome_cases"))
        cj = _skill(doc, "ClearJam")
        frees = any(not e.get("positive", True) and e["predicate"]["name"] in hidden
                    for o in cj.get("outcomes") or [] for e in o.get("effects") or [])
        r["shake_frees_hidden"] = frees and _uses_hidden(cj.get("outcome_cases"), hidden) \
            and _param_bernoulli(cj.get("outcome_cases"))
        r["rattle_noisy"] = any(_uses_hidden(cs, hidden) and _param_bernoulli(cs)
                                for cs in (cj.get("observation_cases") or {}).values())
        blob = json.dumps(doc["domain"])
        r["numbers_withheld"] = '"value"' not in blob
        rw = doc["problem"].get("rewards") or {}
        r["rewards_transcribed"] = (
            _frac(rw.get("step")) == Fraction(-1, 50)
            and _frac((rw.get("skills") or {}).get("ClearJam")) == Fraction(-1, 20)
            and _frac(rw.get("goal")) == Fraction(2)
            and _frac(doc["problem"].get("discount")) == Fraction(19, 20))
        go = _skill(doc, "Goto")
        r["corridor_refusals"] = len(go.get("outcomes") or []) >= 2 and any(
            isinstance(a, dict) and "equals" in a
            for c in go.get("outcome_cases") or [] for a in c.get("when") or [])
        goal_args = {a for lit in doc["problem"].get("goal") or [] for a in lit.get("args", [])}
        r["goal_both_agents"] = {"A", "B"} <= goal_args
    except (KeyError, TypeError, AttributeError):
        pass
    return r, errs


def main(results_dir: str) -> None:
    true_doc = json.load(open(pathlib.Path(__file__).with_name("coopgrid_jam_po_true.json")))
    for q in true_doc["domain"]["parameters"]:   # the generator is asked to withhold values
        q.pop("value", None)
    tr, te = score(true_doc)
    assert all(tr.values()) and not te, (tr, te)
    rows = []
    for meta_path in sorted(pathlib.Path(results_dir).glob("*/*.meta.json")):
        meta = json.load(open(meta_path))
        raw = meta_path.with_name(meta_path.name.replace(".meta.json", ".txt")).read_text()
        try:
            doc = _extract(raw)
            res, errs = score(doc)
        except (ValueError, json.JSONDecodeError):
            res, errs = {k: False for k in CHECKS}, ["not parseable as JSON"]
        rows.append({"model": meta["model"], "seed": meta["seed"],
                     "seconds": meta.get("seconds"), "score": sum(res.values()),
                     "checks": res, "n_errors": len(errs), "first_errors": errs[:3]})
    out = pathlib.Path(results_dir) / "summary.json"
    out.write_text(json.dumps(rows, indent=1) + "\n")
    models = sorted({r["model"] for r in rows})
    print("| model | samples | mean score /12 | best | schema-valid | parsed JSON |")
    print("|---|---|---|---|---|---|")
    for m in models:
        rs = [r for r in rows if r["model"] == m]
        print(f"| {m} | {len(rs)} | {sum(r['score'] for r in rs) / len(rs):.1f} | "
              f"{max(r['score'] for r in rs)} | {sum(r['checks']['schema_valid'] for r in rs)} | "
              f"{sum(r['checks']['json'] for r in rs)} |")
    print()
    print("| check | " + " | ".join(models) + " |")
    print("|---|" + "---|" * len(models))
    for k in CHECKS:
        cells = [str(sum(r["checks"][k] for r in rows if r["model"] == m)) for m in models]
        print(f"| {k} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results")
