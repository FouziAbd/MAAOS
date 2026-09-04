"""The concrete V1 orchestration policies (R2 — report Phase 2 items 1, 2, 5).

Each strategy from the former policy branch in `runtime/orchestrator.py::decide` is now its
own `OrchestrationPolicyContract` implementation. A policy is a PURE transformation of
immutable context into a typed decision: it holds only its configuration value, receives no
environment handle through any surface, and never mutates or advances time. The loop enacts
decisions; the executor alone touches the backend.

The shared plan-head routing (standing recovery pre-empts, `NoPlan` halts, inapplicable head
replans, applicable head executes) is identical under both policies — frozen V1 behavior.
The ONLY strategic difference is the repeated-failure escape (:118, decisions §19.1 item 1):

  - `SymbolicPrimaryPolicy` HALTs with the discrepancy history — deliberately conservative,
    never silently strengthening the model — and declares NO track inputs, so the loop never
    consults the NL model on its behalf (report Phase 2 item 5: information cost).
  - `AdvisoryTwoTrackPolicy` answers REQUEST_PROPOSAL — the loop consults the NL
    RecoveryProposer and the recovery call passes through the SAME validation gate and
    executor as any other call — and declares the advisory proposal as a required input.

Dispatch is an OPEN registry mapping configuration NAMES (strings) to policy factories
(report Phase 2 item 2): the `OrchestrationPolicy` enum in the frozen `OrchestrationConfig`
stays configuration data, but it is no longer the implementation dispatch mechanism — a new
policy is a new registry entry or a directly injected object, never an enum/central edit.

Reason strings are frozen baseline surface: the R0 characterization transcripts pin the
HALTED_REPEATED_FAILURE reason verbatim (docs/refactor/baseline/demo_symbolic_primary.txt).
Do not reword them.
"""
from __future__ import annotations

from typing import Callable, Dict, Generic, TypeVar

from shared.contracts import (
    Execute,
    Halt,
    OrchestrationContext,
    OrchestrationPolicyContract,
    PolicyDecision,
    PreliminaryContext,
    Replan,
    RequestProposal,
    TrackRequest,
)
from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
from shared.planner_result import NoPlan, PlanFound
from shared.skills import GroundedSkillCall, SymbolicallyInapplicable

StateT = TypeVar("StateT")
ProposalT = TypeVar("ProposalT")


class _PlanHeadPolicy(Generic[StateT, ProposalT]):
    """The shared V1 plan-head routing. Subclasses supply only the repeated-failure escape —
    the one place the two frozen policies genuinely differ."""

    def __init__(self, *, repeated_failure_threshold: int) -> None:
        if repeated_failure_threshold <= 0:
            raise ValueError("repeated_failure_threshold must be positive")
        self.repeated_failure_threshold = repeated_failure_threshold

    def required_inputs(
        self, context: PreliminaryContext[StateT, GroundedSkillCall], /
    ) -> TrackRequest:
        raise NotImplementedError

    def _repeated_failure_escape(
        self, head: GroundedSkillCall, failure_count: int
    ) -> PolicyDecision[GroundedSkillCall]:
        raise NotImplementedError

    def decide(
        self, context: OrchestrationContext[StateT, GroundedSkillCall, ProposalT], /
    ) -> PolicyDecision[GroundedSkillCall]:
        preliminary = context.preliminary
        if preliminary.standing_recovery is not None:
            return Execute(
                call=preliminary.standing_recovery,
                reason="enacting standing NL recovery advice (prior REQUEST_PROPOSAL)",
            )
        planner_result = preliminary.planner_result
        if isinstance(planner_result, NoPlan):
            return Halt(
                reason=f"NoPlan is a semantic result, not a fault: {planner_result.reason}"
            )
        if not isinstance(planner_result, PlanFound):
            # must hold under -O too: PlannerFailure is converted to an InfrastructureFault
            # by the loop before orchestration (:156); it never reaches a decision
            raise TypeError(
                f"decide() received {type(planner_result).__name__}; only PlanFound/NoPlan "
                f"are decision inputs"
            )
        if not planner_result.plan:
            return Halt(reason="empty plan: goal already satisfied")

        head = planner_result.plan[0]
        if isinstance(preliminary.head_validation, SymbolicallyInapplicable):
            # belief moved since planning — a symbolic-track verdict, never a fault (Decision 7)
            return Replan(reason=f"plan head inapplicable: {preliminary.head_validation.reason}")

        if preliminary.failure_count >= self.repeated_failure_threshold:
            return self._repeated_failure_escape(head, preliminary.failure_count)

        return Execute(call=head)


class SymbolicPrimaryPolicy(_PlanHeadPolicy[StateT, ProposalT]):
    """:248 — the NL track is never consulted; repeated failure of one (pre-state, call)
    pair halts with the discrepancy history."""

    def required_inputs(
        self, context: PreliminaryContext[StateT, GroundedSkillCall], /
    ) -> TrackRequest:
        return TrackRequest(nl_proposal=False)

    def _repeated_failure_escape(
        self, head: GroundedSkillCall, failure_count: int
    ) -> PolicyDecision[GroundedSkillCall]:
        return Halt(
            call=head,
            reason=f"(pre-state, call) failed {failure_count}x under SYMBOLIC_PRIMARY — "
                   f"halting with the discrepancy history rather than strengthening the model",
        )


class AdvisoryTwoTrackPolicy(_PlanHeadPolicy[StateT, ProposalT]):
    """:249 — the advisory proposal is a required track input, and repeated failure escapes
    to the NL RecoveryProposer instead of halting."""

    def required_inputs(
        self, context: PreliminaryContext[StateT, GroundedSkillCall], /
    ) -> TrackRequest:
        return TrackRequest(nl_proposal=True)

    def _repeated_failure_escape(
        self, head: GroundedSkillCall, failure_count: int
    ) -> PolicyDecision[GroundedSkillCall]:
        return RequestProposal(
            call=head,
            reason=f"(pre-state, call) failed {failure_count}x — consulting the NL "
                   f"RecoveryProposer (:118 escape)",
        )


# ── the registry (application-boundary dispatch, open by construction) ─────────────────
PolicyFactory = Callable[[OrchestrationConfig], OrchestrationPolicyContract]

POLICY_FACTORIES: Dict[str, PolicyFactory] = {
    str(OrchestrationPolicy.SYMBOLIC_PRIMARY): lambda config: SymbolicPrimaryPolicy(
        repeated_failure_threshold=config.repeated_failure_threshold
    ),
    str(OrchestrationPolicy.ADVISORY_TWO_TRACK): lambda config: AdvisoryTwoTrackPolicy(
        repeated_failure_threshold=config.repeated_failure_threshold
    ),
}


def build_policy(config: OrchestrationConfig) -> OrchestrationPolicyContract:
    """Map the configuration NAME to a policy object. Names, not enum identity, are the
    dispatch key, so composition can register new strategies without central edits."""
    name = str(config.policy)
    factory = POLICY_FACTORIES.get(name)
    if factory is None:
        raise LookupError(
            f"no orchestration policy registered under {name!r}; known: "
            f"{sorted(POLICY_FACTORIES)}"
        )
    return factory(config)
