"""RecoveryProposer (contract :228) — a typed recovery proposal from a typed discrepancy.

Deterministic V1 rule, grounded in the recorded livelock discovery (decisions §19.1 item 1):
when a symbolically applicable CONSUMING skill (`Push`/`CooperativePush`) fails in the backend,
the belief retains `in_pose` and a bare replan repeats the failed step forever; the escape is
RE-ESTABLISHMENT. So the proposer answers an `EXECUTION_FAILURE_OF_APPLICABLE_SKILL` on a
consuming skill with the corresponding `GotoPushPose` call(s). Everything else gets NO proposal
— an empty tuple, never an invented skill. Proposals are advice for the P4 orchestrator; this
module never executes anything.
"""
from __future__ import annotations

from typing import Tuple

from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.skills import GroundedSkillCall, SkillName

_CONSUMING = frozenset({SkillName.PUSH, SkillName.COOPERATIVE_PUSH})


def propose_recovery(discrepancy: ExecutionDiscrepancy) -> Tuple[GroundedSkillCall, ...]:
    if discrepancy.kind is not DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL:
        return ()
    call = discrepancy.call                 # non-Optional on ExecutionDiscrepancy
    if call.skill not in _CONSUMING:
        return ()
    return tuple(
        GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (agent,), call.box, call.zone)
        for agent in call.agents
    )
