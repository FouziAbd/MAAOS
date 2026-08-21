"""ObservationInterpreter (contract :223) — typed observation in, deterministic NL facts out.

Consumes ONLY the channels the NL track may see (`shared/observation.py` V1_VISIBILITY:
EXACT_STATE + PUBLIC_EXECUTION_RESULT): the canonical snapshot and the typed outcome.
`raw_label`, `primitive_steps` and `notes` are diagnostic PROVENANCE under the binding rule on
`ExecutiveObservation` and are deliberately not narrated — a fact derived from provenance would
smuggle it into reasoning.
"""
from __future__ import annotations

from typing import Optional, Tuple

from shared.execution import ExecutionOutcome
from shared.state_snapshot import StateSnapshot

_DIRECTION_WORDS = {0: "right", 1: "down", 2: "left", 3: "up"}


def state_facts(snapshot: StateSnapshot) -> Tuple[str, ...]:
    """Deterministic, sorted NL rendering of the canonical snapshot."""
    facts = []
    for agent in snapshot.agents:
        facts.append(
            f"{agent.agent_id.value} is at {agent.position} facing "
            f"{_DIRECTION_WORDS[agent.direction]}"
        )
    for box in snapshot.boxes:
        weight = "needs two agents" if box.required_agents >= 2 else "one agent can push it"
        status = "already delivered" if box.delivered else "not delivered yet"
        facts.append(f"{box.box_id} is at {box.position}; {weight}; {status}")
    facts.append(
        "the delivery zone cells are "
        + ", ".join(str(c) for c in snapshot.static.delivery_zone)
    )
    return tuple(sorted(facts))


def outcome_fact(skill: str, outcome: Optional[ExecutionOutcome]) -> Optional[str]:
    if outcome is None:
        return None
    return f"the last attempt ({skill}) ended with typed outcome {outcome}"
