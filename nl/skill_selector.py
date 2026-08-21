"""SkillSelector (contract :225) — one typed proposal per request, through the seam.

Builds its prompt fields from TYPED data only (interpreted task, semantic belief facts, the
frozen registry menu), asks the seam for one line in the frozen call format, and returns the
typed parse result. A garbage response is a `MalformedCall` for the repair module — never a
substituted default (Decision 7).
"""
from __future__ import annotations

from typing import Union

from shared.skills import REGISTRY, GroundedSkillCall, MalformedCall, SkillName

from nl.parser import parse_skill_call
from nl.seam import LMSeam, NLRequest
from nl.semantic_belief import SemanticBelief
from nl.task_interpreter import InterpretedTask

#: Frozen output format, stated once and reused by repair.
FORMAT_INSTRUCTIONS = (
    "Answer with EXACTLY ONE skill call on a single line, formatted "
    "'Skill(agent; box_k; delivery_zone)' — e.g. 'Push(agent_0; box_1; delivery_zone)' or "
    "'CooperativePush(agent_0,agent_1; box_0; delivery_zone)'. No other text."
)


def skill_menu() -> str:
    """The decision space, rendered from the frozen registry — never hand-maintained."""
    lines = []
    for name in SkillName:
        signature = REGISTRY.get(name)
        lines.append(f"{name.value}: parameters {[str(t) for t in signature.parameter_types]}")
    return "\n".join(lines)


class SkillSelector:
    def __init__(self, seam: LMSeam) -> None:
        self._seam = seam

    def build_request(self, task: InterpretedTask, belief: SemanticBelief) -> NLRequest:
        return NLRequest.of(
            "skill_selector",
            objective=task.task.description,
            goal=", ".join(sorted(str(l) for l in task.goal_literals)),
            situation=belief.rendered(),
            decision_space=skill_menu(),
            format=FORMAT_INSTRUCTIONS,
        )

    def propose(
        self, task: InterpretedTask, belief: SemanticBelief
    ) -> Union[GroundedSkillCall, MalformedCall]:
        return parse_skill_call(self._seam.complete(self.build_request(task, belief)))
