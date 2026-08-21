"""RepairSkillCall (contract :226) — ONE typed repair attempt, then typed rejection.

Given a `MalformedCall`, ask the seam once to reformat the original raw text (the parser's
reason is included so the model knows what was wrong), and re-parse. If the repair is still
malformed, the `MalformedCall` STANDS — it is InfrastructureFault material for the P4 cycle
(`MalformedCall.to_infrastructure_fault`), never a reason to substitute a default skill.
"""
from __future__ import annotations

from typing import Union

from shared.skills import GroundedSkillCall, MalformedCall

from nl.parser import parse_skill_call
from nl.seam import LMSeam, NLRequest
from nl.skill_selector import FORMAT_INSTRUCTIONS


class RepairSkillCall:
    def __init__(self, seam: LMSeam) -> None:
        self._seam = seam

    def build_request(self, malformed: MalformedCall) -> NLRequest:
        return NLRequest.of(
            "repair_skill_call",
            raw=malformed.raw,
            problem=malformed.reason,
            format=FORMAT_INSTRUCTIONS,
        )

    def repair(self, malformed: MalformedCall) -> Union[GroundedSkillCall, MalformedCall]:
        repaired = parse_skill_call(self._seam.complete(self.build_request(malformed)))
        if isinstance(repaired, MalformedCall):
            return MalformedCall(
                reason=f"unrepairable after one attempt: {repaired.reason} "
                       f"(original problem: {malformed.reason})",
                raw=malformed.raw,
            )
        return repaired
