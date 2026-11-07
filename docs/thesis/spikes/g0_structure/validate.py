"""Standalone checker for the T1 skill-IR JSON (spike code; not the T3 implementation).

Implements the construction rules of docs/decisions/T1_PROBABILISTIC_SKILL_IR.md that a
generated document can break. `validate(doc)` returns a list of error strings (empty = valid).
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict, List, Set

WILD = "*"


def _frac(x: Any) -> Fraction:
    if not isinstance(x, str):
        raise ValueError(f"number {x!r} must be a string")
    return Fraction(x)


def validate(doc: Any) -> List[str]:  # noqa: C901 - a flat rule list reads best here
    errs: List[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("domain"), dict) \
            or not isinstance(doc.get("problem"), dict):
        return ["top level must be {\"domain\": {...}, \"problem\": {...}}"]
    d, p = doc["domain"], doc["problem"]
    types = d.get("types") or []
    if not isinstance(types, list) or not types:
        errs.append("domain.types missing")
        types = []
    consts: Dict[str, str] = {}
    for c in d.get("constants", []) or []:
        try:
            if c["type"] not in types:
                errs.append(f"constant {c['name']}: unknown type {c['type']}")
            if c["name"] in consts:
                errs.append(f"duplicate constant {c['name']}")
            consts[c["name"]] = c["type"]
        except (KeyError, TypeError):
            errs.append(f"bad constant {c!r}")
    params: Set[str] = set()
    for q in d.get("parameters", []) or []:
        try:
            if q["name"] in params:
                errs.append(f"duplicate parameter {q['name']}")
            params.add(q["name"])
            a, b = q["prior"]["beta"]
            if _frac(a) <= 0 or _frac(b) <= 0:
                errs.append(f"parameter {q['name']}: beta prior must be positive")
            if "value" in q and not 0 < _frac(q["value"]) < 1:
                errs.append(f"parameter {q['name']}: value must be strictly between 0 and 1")
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
            errs.append(f"bad parameter {q!r}: {e}")
    channels: Dict[str, List[str]] = {}
    for ch in d.get("observation_channels", []) or []:
        try:
            syms = list(ch["symbols"])
            if ch["name"] in channels:
                errs.append(f"duplicate channel {ch['name']}")
            if len(syms) < 2 or len(set(syms)) != len(syms):
                errs.append(f"channel {ch['name']}: needs two or more distinct symbols")
            channels[ch["name"]] = syms
        except (KeyError, TypeError):
            errs.append(f"bad channel {ch!r}")
    preds: Dict[str, Dict[str, Any]] = {}
    for pr in d.get("predicates", []) or []:
        try:
            if pr["name"] in preds:
                errs.append(f"duplicate predicate {pr['name']}")
            for t in pr["param_types"]:
                if t not in types:
                    errs.append(f"predicate {pr['name']}: unknown type {t}")
            preds[pr["name"]] = {"types": list(pr["param_types"]),
                                 "fluent": bool(pr.get("fluent", True)),
                                 "hidden": pr.get("observable", True) is False}
        except (KeyError, TypeError):
            errs.append(f"bad predicate {pr!r}")

    def check_args(where: str, lit: Any, ptypes: Dict[str, str], wild_ok: bool) -> str:
        if not isinstance(lit, dict) or "name" not in lit:
            errs.append(f"{where}: bad literal {lit!r}")
            return ""
        decl = preds.get(lit["name"])
        if decl is None:
            errs.append(f"{where}: undeclared predicate {lit['name']}")
            return ""
        args = list(lit.get("args", []))
        if len(args) != len(decl["types"]):
            errs.append(f"{where}: {lit['name']} arity {len(args)}, declared {len(decl['types'])}")
            return lit["name"]
        for arg, want in zip(args, decl["types"]):
            if arg == WILD:
                if not wild_ok:
                    errs.append(f"{where}: wildcard not allowed here")
                continue
            got = ptypes.get(arg) or consts.get(arg)
            if got is None:
                errs.append(f"{where}: {lit['name']} argument {arg!r} is not a parameter or constant")
            elif got != want:
                errs.append(f"{where}: {lit['name']} argument {arg!r} has type {got}, needs {want}")
        return lit["name"]

    def check_dist(where: str, dist: Any, labels: List[str]) -> None:
        if not isinstance(dist, dict) or len(dist) != 1:
            errs.append(f"{where}: bad distribution {dist!r}")
            return
        if "deterministic" in dist:
            if dist["deterministic"] not in labels:
                errs.append(f"{where}: unknown label {dist['deterministic']!r}")
            return
        bern = dist.get("bernoulli")
        if not isinstance(bern, dict):
            errs.append(f"{where}: unknown distribution form {list(dist)}")
            return
        for k in ("then", "else"):
            if bern.get(k) not in labels:
                errs.append(f"{where}: unknown label {bern.get(k)!r}")
        if bern.get("then") == bern.get("else"):
            errs.append(f"{where}: bernoulli labels must differ")
        pp = bern.get("p")
        if isinstance(pp, dict) and "parameter" in pp:
            if pp["parameter"] not in params:
                errs.append(f"{where}: undeclared parameter {pp['parameter']}")
        elif isinstance(pp, dict) and "value" in pp:
            try:
                if not 0 < _frac(pp["value"]) < 1:
                    errs.append(f"{where}: constant probability must be strictly between 0 and 1")
            except (ValueError, ZeroDivisionError):
                errs.append(f"{where}: bad constant {pp['value']!r}")
        else:
            errs.append(f"{where}: bad bernoulli p {pp!r}")

    def check_cases(where: str, cases: Any, ptypes: Dict[str, str], labels: List[str]) -> None:
        if not isinstance(cases, list) or not cases:
            errs.append(f"{where}: decision list must be a non-empty list")
            return
        for i, c in enumerate(cases):
            if not isinstance(c, dict):
                errs.append(f"{where}[{i}]: bad case")
                continue
            when = c.get("when", [])
            if i == len(cases) - 1 and when:
                errs.append(f"{where}: last case must have an empty 'when'")
            for atom in when or []:
                if isinstance(atom, dict) and "equals" in atom:
                    try:
                        par, con = atom["equals"]
                        if par not in ptypes or con not in consts:
                            errs.append(f"{where}[{i}]: bad equals {atom['equals']!r}")
                    except (TypeError, ValueError):
                        errs.append(f"{where}[{i}]: bad equals {atom!r}")
                elif isinstance(atom, dict) and "literal" in atom:
                    check_args(f"{where}[{i}]", atom["literal"], ptypes, wild_ok=False)
                else:
                    errs.append(f"{where}[{i}]: bad atom {atom!r}")
            check_dist(f"{where}[{i}]", c.get("distribution"), labels)

    skill_names: Set[str] = set()
    for s in d.get("skills", []) or []:
        if not isinstance(s, dict) or "name" not in s:
            errs.append(f"bad skill {s!r}")
            continue
        n = s["name"]
        if n in skill_names:
            errs.append(f"duplicate skill {n}")
        skill_names.add(n)
        names, ptys = list(s.get("parameters", [])), list(s.get("parameter_types", []))
        if len(names) != len(ptys) or len(set(names)) != len(names):
            errs.append(f"{n}: parameters and parameter_types must be parallel and unique")
        for t in ptys:
            if t not in types:
                errs.append(f"{n}: unknown parameter type {t}")
        ptypes = dict(zip(names, ptys))
        for lit in s.get("preconditions", []) or []:
            if preds.get(check_args(f"{n}.pre", lit, ptypes, wild_ok=False), {}).get("hidden"):
                errs.append(f"{n}: hidden predicate {lit['name']} in a precondition")
        for lit in s.get("negative_preconditions", []) or []:
            if preds.get(check_args(f"{n}.negpre", lit, ptypes, wild_ok=True), {}).get("hidden"):
                errs.append(f"{n}: hidden predicate {lit['name']} in a precondition")

        def check_effects(where: str, effects: Any) -> None:
            for e in effects or []:
                try:
                    name = check_args(where, e["predicate"], ptypes, wild_ok=not e["positive"])
                except (KeyError, TypeError):
                    errs.append(f"{where}: bad effect {e!r}")
                    continue
                if name and not preds[name]["fluent"]:
                    errs.append(f"{where}: effect on static predicate {name}")
        outcomes = s.get("outcomes") or []
        if outcomes:
            if s.get("effects"):
                errs.append(f"{n}: outcomes together with plain effects")
            labels = [o.get("label") for o in outcomes if isinstance(o, dict)]
            if len(set(labels)) != len(labels):
                errs.append(f"{n}: duplicate outcome labels")
            if s.get("outcome_label") not in labels:
                errs.append(f"{n}: outcome_label must name one of the outcomes")
            for o in outcomes:
                check_effects(f"{n}.{o.get('label')}", o.get("effects"))
            if len(outcomes) >= 2:
                if not s.get("outcome_cases"):
                    errs.append(f"{n}: two or more outcomes need outcome_cases")
                else:
                    check_cases(f"{n}.outcome_cases", s["outcome_cases"], ptypes, labels)
            elif s.get("outcome_cases"):
                errs.append(f"{n}: a single outcome takes no outcome_cases")
        else:
            check_effects(f"{n}.effects", s.get("effects"))
            if s.get("outcome_cases"):
                errs.append(f"{n}: outcome_cases without outcomes")
        obs = s.get("observation_cases") or {}
        if not isinstance(obs, dict):
            errs.append(f"{n}: observation_cases must be an object keyed by channel")
            obs = {}
        for ch, cases in obs.items():
            if ch not in channels:
                errs.append(f"{n}: undeclared channel {ch}")
                continue
            check_cases(f"{n}.obs.{ch}", cases, ptypes, channels[ch])

    objects = dict(consts)
    for o in p.get("objects", []) or []:
        try:
            objects[o["name"]] = o["type"]
        except (KeyError, TypeError):
            errs.append(f"bad problem object {o!r}")

    def check_ground(where: str, lit: Any) -> str:
        if not isinstance(lit, dict) or lit.get("name") not in preds:
            errs.append(f"{where}: bad or undeclared literal {lit!r}")
            return ""
        for a in lit.get("args", []):
            if a not in objects:
                errs.append(f"{where}: unknown object {a!r}")
        if len(lit.get("args", [])) != len(preds[lit["name"]]["types"]):
            errs.append(f"{where}: arity mismatch for {lit['name']}")
        return lit["name"]
    for lit in p.get("init", []) or []:
        if preds.get(check_ground("init", lit), {}).get("hidden"):
            errs.append(f"init: hidden literal {lit['name']}")
    seen: Set[str] = set()
    for h in p.get("hidden_prior", []) or []:
        try:
            name = check_ground("hidden_prior", h["literal"])
            key = repr(h["literal"])
            if key in seen:
                errs.append("hidden_prior: literal listed twice")
            seen.add(key)
            if name and not preds[name]["hidden"]:
                errs.append(f"hidden_prior: {name} is observable")
            pp = h["p"]
            if "parameter" in pp and pp["parameter"] not in params:
                errs.append(f"hidden_prior: undeclared parameter {pp['parameter']}")
        except (KeyError, TypeError):
            errs.append(f"bad hidden_prior entry {h!r}")
    if not p.get("goal"):
        errs.append("problem.goal missing")
    for lit in p.get("goal", []) or []:
        check_ground("goal", lit)
    try:
        r = p["rewards"]
        _frac(r["step"]); _frac(r["goal"])
        for k, v in (r.get("skills") or {}).items():
            _frac(v)
            if k not in skill_names:
                errs.append(f"rewards.skills: unknown skill {k}")
        if not 0 < _frac(p["discount"]) < 1:
            errs.append("discount must be strictly between 0 and 1")
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        errs.append(f"rewards/discount: {e!r}")
    return errs
