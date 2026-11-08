"""Score a generated model against a gold model, with written feedback (spike code).

`compare(gold, reply_text)` -> (score in [0, 1], feedback text). 40% is validity against the T1 rules
(scaled down by the number of rule errors), 60% is name-agnostic structural agreement with the gold
model. The feedback lists the rule errors and the structural mismatches in plain words; GEPA's
reflection step reads it.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from fractions import Fraction
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "g0_structure"))
import validate  # noqa: E402


def extract(text: str, repair: bool = False) -> Any:
    """Strict by default. `repair=True` falls back to json_repair (a DSPy dependency) for syntax slips;
    it is reported as a separate score and never replaces the strict one."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    body = text[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        if not repair:
            raise
        import json_repair
        doc = json_repair.loads(body)
        if not isinstance(doc, dict):
            raise ValueError("json_repair could not recover an object")
        return doc


def _hidden(doc) -> set:
    return {p.get("name") for p in doc["domain"].get("predicates", []) or []
            if isinstance(p, dict) and p.get("observable", True) is False}


def _skills(doc) -> Dict[str, Dict[str, Any]]:
    return {s.get("name"): s for s in doc["domain"].get("skills", []) or [] if isinstance(s, dict)}


def _mentions_hidden(cases, hidden) -> bool:
    for c in cases or []:
        for a in (c.get("when") or []) if isinstance(c, dict) else []:
            if isinstance(a, dict) and isinstance(a.get("literal"), dict) and a["literal"].get("name") in hidden:
                return True
    return False


def _has_param_bernoulli(cases) -> bool:
    for c in cases or []:
        d = c.get("distribution") if isinstance(c, dict) else None
        b = d.get("bernoulli") if isinstance(d, dict) else None
        if isinstance(b, dict) and isinstance(b.get("p"), dict) and "parameter" in b["p"]:
            return True
    return False


def _has_equals(cases) -> bool:
    return any(isinstance(a, dict) and "equals" in a
               for c in cases or [] if isinstance(c, dict) for a in c.get("when") or [])


def _features(doc) -> Dict[str, Any]:
    hidden = _hidden(doc)
    f: Dict[str, Any] = {"skills": {n: len(s.get("parameters", [])) for n, s in _skills(doc).items()},
                         "n_hidden": len(hidden)}
    for n, s in _skills(doc).items():
        oc = s.get("outcome_cases")
        obs = s.get("observation_cases") or {}
        obs = obs if isinstance(obs, dict) else {}
        f[f"{n}.stochastic"] = len(s.get("outcomes") or []) >= 2
        f[f"{n}.outcome_reads_hidden"] = _mentions_hidden(oc, hidden)
        f[f"{n}.outcome_has_parameter"] = _has_param_bernoulli(oc)
        f[f"{n}.refusal_by_equals"] = _has_equals(oc)
        f[f"{n}.noisy_hidden_sensor"] = any(_mentions_hidden(c, hidden) and _has_param_bernoulli(c) for c in obs.values())
    rw = doc["problem"].get("rewards") or {}

    def fr(x):
        try:
            return Fraction(str(x))
        except (ValueError, ZeroDivisionError):
            return None
    f["rewards"] = (fr(rw.get("step")), {k: fr(v) for k, v in (rw.get("skills") or {}).items()},
                    fr(rw.get("goal")), fr(doc["problem"].get("discount")))
    f["prior_is_parameter"] = bool(doc["problem"].get("hidden_prior")) and all(
        isinstance(h, dict) and isinstance(h.get("p"), dict) and "parameter" in h["p"]
        for h in doc["problem"]["hidden_prior"])
    f["no_values"] = '"value"' not in json.dumps(doc["domain"])
    return f


_SAY = {  # (when the gold value is True, when it is False)
    "stochastic": ("needs two or more outcomes with outcome_cases (the description says it can fail or slip)",
                   "has one certain outcome; drop the extra outcomes"),
    "outcome_reads_hidden": ("needs outcome_cases that condition on the hidden variable",
                             "needs outcome_cases that do not read the hidden variable"),
    "outcome_has_parameter": ("needs a Bernoulli on a named parameter in its outcome_cases",
                              "needs no probability parameter in its outcome_cases"),
    "refusal_by_equals": ("needs an 'equals' case for the refusal the description states",
                          "needs no 'equals' case"),
    "noisy_hidden_sensor": ("needs an observation channel that reports the hidden variable through a Bernoulli on a parameter",
                            "reports no noisy observation of the hidden variable"),
}


def compare(gold: Dict[str, Any], reply: str, repair: bool = False) -> Tuple[float, str]:
    try:
        doc = extract(reply, repair=repair)
    except json.JSONDecodeError as e:
        body = reply[reply.find("{"):]
        near = body[max(0, e.pos - 100):e.pos + 40].replace("\n", " ")
        return 0.0, (f"The reply is not valid JSON ({e.msg} at char {e.pos}), near: ...{near}... "
                     "Check commas and braces; a precondition is {\"name\", \"args\"} only, while "
                     "{\"literal\": ..., \"positive\": ...} belongs only inside a case's \"when\".")
    except ValueError as e:
        return 0.0, f"The reply is not one parseable JSON object ({e}). Output only the JSON object."
    errs = validate.validate(doc)
    if not isinstance(doc, dict) or not isinstance(doc.get("domain"), dict) or not isinstance(doc.get("problem"), dict):
        return 0.05, "Top level must be {\"domain\": {...}, \"problem\": {...}}. " + "; ".join(errs[:3])
    validity = 1.0 if not errs else max(0.0, 0.5 - len(errs) / 40)
    g, p = _features(gold), _features(doc)
    notes: List[str] = []
    checks = 0
    hits = 0
    for key, gv in g.items():
        checks += 1
        pv = p.get(key)
        if key == "skills":
            ok = pv == gv
            if not ok:
                notes.append(f"skills must be exactly {gv} (name: number of parameters); got {pv}")
        elif key == "rewards":
            ok = pv == gv
            if not ok:
                notes.append("rewards/discount must transcribe the description exactly as fractions "
                             "(multiply per-agent amounts by the number of agents)")
        elif "." in key:
            name, what = key.split(".", 1)
            ok = pv == gv
            if not ok and name in p["skills"]:
                notes.append(f"{name} " + _SAY[what][0 if gv else 1])
            elif not ok and f"missing:{name}" not in notes:
                notes.append(f"missing:{name}")
        else:
            ok = pv == gv
            if not ok:
                notes.append({"n_hidden": f"declare exactly {gv} hidden predicate(s) (observable: false)",
                              "prior_is_parameter": "hidden_prior entries must use {\"parameter\": name}",
                              "no_values": "do not write probability values; only named parameters"}[key])
        hits += bool(ok)
    notes = [f"skill {n[8:]} is missing" if n.startswith("missing:") else n for n in notes]
    score = 0.4 * validity + 0.6 * hits / checks
    fb = []
    if errs:
        fb.append(f"{len(errs)} rule error(s), first ones: " + "; ".join(errs[:8]))
    if notes:
        fb.append("Structure: " + "; ".join(notes[:10]))
    return round(score, 4), " ".join(fb) or "Valid and structurally correct."
