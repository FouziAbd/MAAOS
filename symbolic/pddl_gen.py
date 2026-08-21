"""Deterministic PDDL emission FROM `DomainIR` (§18 item 1: re-issue, never hand-edit).

The legacy `.pddl` artifacts diverged from the frozen model three ways (no `zone`, `explore`
still an action, identifiers that `BoxId.parse` rejects) precisely because they were
hand-maintained. This emitter makes the IR the single source: the checked-in V1 artifacts are
byte-for-byte reproducible from `DOMAIN_IR`, and a regeneration test fails the moment they
drift.

Identifier discipline: objects are the FROZEN identities (`agent_0`, `box_0`, `delivery_zone`) —
`BoxId.parse` round-trips them, so a plan file un-lifts directly through `SkillIR.unbind`.
Action names are the frozen `backend_dispatch_key`s, keeping one vocabulary across planner
files, adapter dispatch and executive calls.

Output is plain STRIPS + :typing (pyperplan-compatible). Fully sorted → deterministic bytes.
"""
from __future__ import annotations

from typing import FrozenSet, Tuple

from shared.ids import ZoneId
from shared.skill_ir import DomainIR
from shared.symbolic_state import GroundedLiteral, SymbolicState

_HEADER = (
    ";; GENERATED FROM domain/box_push_v1.py::DOMAIN_IR by symbolic/pddl_gen.py — DO NOT\n"
    ";; HAND-EDIT. Regenerate via `python -m symbolic.pddl_gen` (or the regeneration test\n"
    ";; will fail on any drift between this file and the frozen IR).\n"
)


def _fmt_params(names, types) -> str:
    return " ".join(f"?{n} - {t}" for n, t in zip(names, types))


def emit_domain(domain: DomainIR) -> str:
    """The classical domain, straight from the frozen IR."""
    lines = [
        _HEADER,
        f"(define (domain {domain.name})",
        "  (:requirements :strips :typing)",
        "  (:types " + " ".join(domain.types) + " - object)",
        "",
        "  (:predicates",
    ]
    for decl in sorted(domain.predicates, key=lambda d: str(d.name)):
        args = " ".join(
            f"?x{index} - {t}" for index, t in enumerate(decl.param_types)
        )
        lines.append(f"    ({decl.name}{(' ' + args) if args else ''})")
    lines.append("  )")
    for ir in sorted(domain.skills, key=lambda s: s.signature.backend_dispatch_key):
        name = ir.signature.backend_dispatch_key
        lines += [
            "",
            f"  (:action {name}",
            f"    :parameters ({_fmt_params(ir.parameters, ir.parameter_types)})",
        ]
        pre = " ".join(
            f"({p.name} {' '.join('?' + a for a in p.args)})" for p in ir.preconditions
        )
        lines.append(f"    :precondition (and {pre})")
        effects = []
        for e in ir.effects:
            atom = f"({e.predicate.name} {' '.join('?' + a for a in e.predicate.args)})"
            effects.append(atom if e.positive else f"(not {atom})")
        lines.append(f"    :effect (and {' '.join(effects)})")
        lines.append("  )")
    lines.append(")")
    return "\n".join(lines) + "\n"


def emit_problem(
    domain: DomainIR,
    name: str,
    state: SymbolicState,
    goal: FrozenSet[GroundedLiteral],
    agents: Tuple[str, ...],
    boxes: Tuple[str, ...],
    zone: ZoneId,
) -> str:
    """A problem instance from a symbolic state + goal, with frozen identifiers."""
    lines = [
        _HEADER,
        f"(define (problem {name})",
        f"  (:domain {domain.name})",
        "  (:objects",
        "    " + " ".join(sorted(agents)) + " - agent",
        "    " + " ".join(sorted(boxes)) + " - box",
        f"    {zone.value} - zone",
        "  )",
        "  (:init",
    ]
    for literal in sorted(state.canonical()):
        predicate, _, rest = literal.partition("(")
        args = rest.rstrip(")").split(",") if rest else []
        lines.append(
            "    (" + predicate + ("" if not args or args == [""] else " " + " ".join(args)) + ")"
        )
    lines.append("  )")
    goal_atoms = " ".join(
        "(" + l.predicate + (" " + " ".join(l.args) if l.args else "") + ")"
        for l in sorted(goal, key=lambda x: x.canonical())
    )
    lines.append(f"  (:goal (and {goal_atoms}))")
    lines.append(")")
    return "\n".join(lines) + "\n"


# ── artifact regeneration entry (§18 item 1) ──────────────────────────────────────

def v1_artifacts() -> dict:
    """The three V1 artifact contents, keyed by filename — used by `__main__` and by the
    regeneration test, so the checked-in files can never drift from the IR silently."""
    from domain.box_push_v1 import (
        AGENTS, DELIVERY_ZONE, DOMAIN_IR, MODEL_VERSION, TASK_DELIVER_BOTH, initial_state,
        project,
    )
    from shared.planner_result import PlanFound
    from symbolic.planner import Universe, plan

    state = project(initial_state())
    goal = frozenset(
        GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_BOTH.goal_delivered
    )
    universe = Universe.from_snapshot(initial_state(), DELIVERY_ZONE)
    result = plan(DOMAIN_IR, state, goal, universe, MODEL_VERSION)
    if not isinstance(result, PlanFound):     # not `assert` — must hold under -O too
        raise RuntimeError(f"frozen instance must be solvable, got {result}")
    solution_lines = [
        ";; GENERATED FROM domain/box_push_v1.py::DOMAIN_IR by symbolic/pddl_gen.py — the",
        ";; deterministic V1 planner's solution for box-push-v1-deliver-both. DO NOT HAND-EDIT.",
        f";; {result.length} steps, cost {result.cost}. Verified by effect simulation (the",
        ";; regeneration test replays it through symbolic.apply_effects to the goal). NOTE the",
        ";; plan is OPTIMISTIC by design: executed literally, its final step fails in the",
        ";; backend (stale non-exclusive in_pose) — the designed ExecutionDiscrepancy signal.",
    ]
    for call in result.plan:
        ir = DOMAIN_IR.skill(call.skill)
        binding = ir.bind(call)
        args = " ".join(binding[name] for name in ir.parameters)
        solution_lines.append(f"({ir.signature.backend_dispatch_key} {args})")
    return {
        "box_push_domain_v1.pddl": emit_domain(DOMAIN_IR),
        "box_push_problem_v1.pddl": emit_problem(
            DOMAIN_IR, "box-push-v1-deliver-both", state, goal,
            tuple(a.value for a in AGENTS),
            tuple(str(b.box_id) for b in initial_state().boxes),
            DELIVERY_ZONE,
        ),
        "box_push_problem_v1.pddl.soln": "\n".join(solution_lines) + "\n",
    }


if __name__ == "__main__":
    import pathlib as _pathlib

    target = _pathlib.Path(__file__).resolve().parents[1] / (
        "functional_layer/custom_env/box_push/pddl"
    )
    for name, content in v1_artifacts().items():
        (target / name).write_text(content, encoding="utf-8")
        print(f"wrote {target / name}")
