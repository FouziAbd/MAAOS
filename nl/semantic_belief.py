"""SemanticBeliefUpdater (contract :224) — the NL track's own belief, NL-side only.

V1 is fully observable, so the semantic belief mirrors the exact snapshot as NL facts plus a
bounded attempt history. It is a PEER of the symbolic `ExactSymbolicBelief`, never a
replacement: nothing here is readable by the symbolic track (enforced by the peer-isolation
guard in tests/test_p3_nl.py), and nothing here is dead-reckoned — every sync re-derives the
facts from the authoritative canonical snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from shared.execution import ExecutionOutcome
from shared.state_snapshot import StateSnapshot

from nl.observation_interpreter import outcome_fact, state_facts

_HISTORY_LIMIT = 8


@dataclass(frozen=True, slots=True)
class SemanticBelief:
    facts: Tuple[str, ...] = field(default_factory=tuple)
    attempt_history: Tuple[str, ...] = field(default_factory=tuple)

    def rendered(self) -> str:
        lines = list(self.facts)
        if self.attempt_history:
            lines.append("recent attempts: " + " | ".join(self.attempt_history))
        return "\n".join(lines)


def update_belief(
    belief: SemanticBelief,
    snapshot: StateSnapshot,
    last_skill: Optional[str] = None,
    last_outcome: Optional[ExecutionOutcome] = None,
) -> SemanticBelief:
    """Pure functional update: exact re-derivation + bounded outcome history."""
    history = belief.attempt_history
    fact = outcome_fact(last_skill or "", last_outcome)
    if fact is not None:
        history = (history + (fact,))[-_HISTORY_LIMIT:]
    return SemanticBelief(facts=state_facts(snapshot), attempt_history=history)
