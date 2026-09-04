"""Legacy orchestration surface — a compatibility shim over `runtime/policies.py` (R2).

Through R1 this module WAS the live implementation: one `decide()` free function whose body
branched on the `OrchestrationPolicy` enum. R2 (report Phase 2) extracted each branch into a
concrete policy class — `SymbolicPrimaryPolicy` / `AdvisoryTwoTrackPolicy` — dispatched by
the open name registry in `runtime/policies.py`, and `ExecutiveLoopManager` now holds a
policy OBJECT and calls it directly.

`decide()` and `CycleDecision` remain as the established public import (`tests/
test_p4_runtime.py::TestOrchestratorRouting` and any external caller): the same signature,
routing, reason strings, and the typed `PlannerFailure` refusal, now delegated through the
same registry and policy objects the loop uses — one implementation, two surfaces.

Frozen routing distinctions (unchanged, see `runtime/policies.py`):
  - `PlannerFailure` never arrives here — the loop converts it to an `InfrastructureFault`
    (`shared/planner_result.py::to_infrastructure_fault`) which short-circuits the cycle (:163).
  - `NoPlan` IS routed here: a legitimate semantic result (:128), answered with HALT.
  - The repeated-failure escape (:118, decisions §19.1 item 1) is where the two policies
    genuinely differ: SYMBOLIC_PRIMARY halts, ADVISORY_TWO_TRACK requests a proposal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.contracts import OrchestrationContext, PreliminaryContext
from shared.orchestration_config import ExecutiveDecision, OrchestrationConfig
from shared.planner_result import PlannerResult
from shared.skills import CallValidation, GroundedSkillCall

from runtime.policies import build_policy


@dataclass(frozen=True, slots=True)
class CycleDecision:
    decision: ExecutiveDecision
    call: Optional[GroundedSkillCall] = None
    reason: str = ""


def decide(
    config: OrchestrationConfig,
    planner_result: PlannerResult,
    head_validation: Optional[CallValidation],
    failure_count: int,
    standing_recovery: Optional[GroundedSkillCall] = None,
) -> CycleDecision:
    """One executive decision, exactly as before R2 — now produced by the registered policy
    object for `config.policy` and flattened back into the legacy `CycleDecision` shape.
    `state` is not part of this legacy signature and no shipped policy reads it; callers
    that need state-aware policies hold a policy object and pass a full context instead."""
    policy = build_policy(config)
    preliminary: PreliminaryContext = PreliminaryContext(
        state=None,
        planner_result=planner_result,
        head_validation=head_validation,
        failure_count=failure_count,
        standing_recovery=standing_recovery,
    )
    outcome = policy.decide(OrchestrationContext(preliminary=preliminary))
    return CycleDecision(
        outcome.decision, call=getattr(outcome, "call", None), reason=outcome.reason
    )
