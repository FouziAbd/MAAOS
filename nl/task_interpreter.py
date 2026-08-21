"""TaskInterpreter (contract :222) — typed task in, typed interpretation + coverage out.

V1 input is text/typed data only. The frozen `Task` already carries the TYPED goal
(`goal_delivered`, `zone`); the NL half interprets the free-text `description` clause by
clause. Every clause the V1 vocabulary can express is listed as covered; anything else goes
into the CoverageReport RESIDUAL — explicitly, never silently dropped (:25). Deterministic,
rule-based, no LM: interpretation of the V1 task language needs no generation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Tuple

from shared.reports import CoverageReport
from shared.symbolic_state import GroundedLiteral
from shared.task import Task

#: A clause is COVERED only when it expresses V1 delivery: a delivery verb together with a
#: delivery object, and no negation. Bare keyword containment over-claimed coverage ("Paint the
#: zone red" is NOT expressible) and would have silently starved the P4 comparator of
#: COVERAGE_GAP evidence — the architecture review's W3.
#: Matching is TOKEN-BASED (word stems against whole words), never raw substring containment —
#: consistency-check P3 round 2 demonstrated `"two" in "network"` classifying "The network
#: needs repair" as covered. Stems match token PREFIXES ("deliver" -> "delivering").
_DELIVERY_VERB_STEMS = ("deliver", "push", "bring", "mov")
_DELIVERY_OBJECT_STEMS = ("box", "zone", "goal", "target")
#: Agent-count requirement clauses ("It needs both agents") ARE expressible: `heavy(box)` /
#: `required_agents` and the `CooperativePush` arity carry them. The object must be AGENT-ish;
#: bare counts ("two hours") are not requirement objects.
_REQUIREMENT_VERB_STEMS = ("need", "require")
_REQUIREMENT_OBJECT_STEMS = ("agent", "cooperat", "partner")
#: "cannot" and bare "no" are single tokens neither in the set nor ending in "n't" — round 3
#: demonstrated "You cannot push the box" classifying covered without them.
_NEGATION_TOKENS = frozenset({"not", "never", "avoid", "cannot", "no"})

#: The same ceiling has an UNDER-coverage direction: a genuine delivery clause carrying a
#: bare "no" token ("Push the box to zone no. 1") classifies residual — conservative by
#: design (a false coverage gap is visible comparator evidence; false coverage is silent).
#: RECORDED IMPRECISION CEILING (accepted V1 heuristic limit, pinned in tests): a clause whose
#: requirement verb and agent-ish object do not form a real capability statement — "The agents
#: need a break" — still classifies covered. Rule-based clause classification cannot resolve
#: that without semantics; the typed goal stays authoritative and the frozen tasks are pinned,
#: so the blast radius is comparator evidence for free-text tasks only.


def _tokens(lowered: str):
    return re.findall(r"[a-z']+", lowered)


def _has_stem(tokens, stems) -> bool:
    return any(token.startswith(stem) for stem in stems for token in tokens)


def _clause_is_covered(lowered: str) -> bool:
    tokens = _tokens(lowered)
    if any(token in _NEGATION_TOKENS or token.endswith("n't") for token in tokens):
        return False                        # ordering/negation constraints are outside V1
    if _has_stem(tokens, _DELIVERY_VERB_STEMS) and _has_stem(tokens, _DELIVERY_OBJECT_STEMS):
        return True
    return _has_stem(tokens, _REQUIREMENT_VERB_STEMS) and _has_stem(
        tokens, _REQUIREMENT_OBJECT_STEMS
    )


@dataclass(frozen=True, slots=True)
class InterpretedTask:
    task: Task
    goal_literals: FrozenSet[GroundedLiteral]
    coverage: CoverageReport


def _clauses(text: str) -> Tuple[str, ...]:
    return tuple(c.strip() for c in re.split(r"[.;]", text or "") if c.strip())


def interpret_task(task: Task) -> InterpretedTask:
    goal = frozenset(
        GroundedLiteral("delivered", (str(box),)) for box in task.goal_delivered
    )
    covered = [f"delivered({box})" for box in task.goal_delivered]
    residual = []
    for clause in _clauses(task.description):
        lowered = clause.lower()
        if _clause_is_covered(lowered):
            covered.append(clause)
        else:
            residual.append(f"clause outside the V1 vocabulary: {clause!r}")
    return InterpretedTask(
        task=task,
        goal_literals=goal,
        coverage=CoverageReport(
            covered=tuple(covered), residual=tuple(residual),
            note="typed goal is authoritative; description clauses classified against the "
                 "V1 delivery vocabulary",
        ),
    )
