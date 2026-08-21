"""The orchestrator: one typed decision per situation, under a configured policy (:29, :248-249).

PURE decision logic — no environment access, no time advancement (:31), no mutation. The loop
manager supplies typed inputs and enacts whatever is decided. Policy changes DECISIONS here;
the executor's semantics are out of reach by construction (`runtime/executor.py`).

Routing (frozen distinctions):
  - `PlannerFailure` never arrives here — the loop converts it to an `InfrastructureFault`
    (`shared/planner_result.py::to_infrastructure_fault`) which short-circuits the cycle (:163).
  - `NoPlan` IS routed here: a legitimate semantic result (:128), answered with HALT — the
    symbolic abstraction says the goal is unreachable; retrying cannot change that in V1's
    deterministic model.
  - The repeated-failure escape (:118, decisions §19.1 item 1 — the demonstrated
    consuming-skill livelock) is where the two policies genuinely differ:
      * SYMBOLIC_PRIMARY: the NL track is never consulted; after `repeated_failure_threshold`
        failures of one (pre-state, call) pair the loop HALTs and surfaces the discrepancy
        history — deliberately conservative, never silently strengthening the model.
      * ADVISORY_TWO_TRACK: REQUEST_PROPOSAL — the loop consults the NL RecoveryProposer
        (deterministic re-establishment advice) and executes the recovery call through the
        SAME validation gate and executor as any other call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.planner_result import NoPlan, PlanFound, PlannerResult
from shared.skills import CallValidation, GroundedSkillCall, SymbolicallyInapplicable


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
    """One executive decision. `head_validation` is the typed verdict on the plan head (None
    when there is no plan to have a head). `standing_recovery` is advice a prior
    REQUEST_PROPOSAL produced: enacting it is still THIS function's decision — every EXECUTE
    the loop performs is orchestrator-issued (review W5), the loop only carries state."""
    if standing_recovery is not None:
        return CycleDecision(
            ExecutiveDecision.EXECUTE, call=standing_recovery,
            reason="enacting standing NL recovery advice (prior REQUEST_PROPOSAL)",
        )
    if isinstance(planner_result, NoPlan):
        return CycleDecision(
            ExecutiveDecision.HALT,
            reason=f"NoPlan is a semantic result, not a fault: {planner_result.reason}",
        )
    if not isinstance(planner_result, PlanFound):
        # must hold under -O too: PlannerFailure is converted to an InfrastructureFault by
        # the loop before orchestration (:156); it never reaches a decision
        raise TypeError(
            f"decide() received {type(planner_result).__name__}; only PlanFound/NoPlan are "
            f"decision inputs"
        )
    if not planner_result.plan:
        return CycleDecision(ExecutiveDecision.HALT, reason="empty plan: goal already satisfied")

    head = planner_result.plan[0]
    if isinstance(head_validation, SymbolicallyInapplicable):
        # belief moved since planning — a symbolic-track verdict, never a fault (Decision 7)
        return CycleDecision(
            ExecutiveDecision.REPLAN,
            reason=f"plan head inapplicable: {head_validation.reason}",
        )

    if failure_count >= config.repeated_failure_threshold:
        if config.policy is OrchestrationPolicy.ADVISORY_TWO_TRACK:
            return CycleDecision(
                ExecutiveDecision.REQUEST_PROPOSAL, call=head,
                reason=f"(pre-state, call) failed {failure_count}x — consulting the NL "
                       f"RecoveryProposer (:118 escape)",
            )
        return CycleDecision(
            ExecutiveDecision.HALT, call=head,
            reason=f"(pre-state, call) failed {failure_count}x under SYMBOLIC_PRIMARY — "
                   f"halting with the discrepancy history rather than strengthening the model",
        )

    return CycleDecision(ExecutiveDecision.EXECUTE, call=head)
