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

R6: the policies are generic in the domain-owned call type as well as state and proposal —
the routing reads only the typed plan channel, the head verdict, the failure count, and the
standing advice, none of which is BoxPush-specific (the R5 probe ran both policies over a
foreign call type; the annotation now says so).
"""
from __future__ import annotations

from typing import Callable, Dict

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
from shared.skills import SymbolicallyInapplicable


class _PlanHeadPolicy[StateT, CallT, ProposalT]:
    """The shared V1 plan-head routing. Subclasses supply only the repeated-failure escape —
    the one place the two frozen policies genuinely differ."""

    def __init__(self, *, repeated_failure_threshold: int) -> None:
        if repeated_failure_threshold <= 0:
            raise ValueError("repeated_failure_threshold must be positive")
        self.repeated_failure_threshold = repeated_failure_threshold

    def required_inputs(
        self, context: PreliminaryContext[StateT, CallT], /
    ) -> TrackRequest:
        raise NotImplementedError

    def _repeated_failure_escape(
        self, head: CallT, failure_count: int
    ) -> PolicyDecision[CallT]:
        raise NotImplementedError

    def decide(
        self, context: OrchestrationContext[StateT, CallT, ProposalT], /
    ) -> PolicyDecision[CallT]:
        """The frozen V1 policies decide from the PRELIMINARY situation alone: the R3
        comparison report in `context.comparison` reaches them before deciding (the R3
        lifecycle guarantee) but by frozen design does not alter V1 decisions — advisory
        evidence advises, it never selects. A non-V1 policy is free to read it."""
        return self._route(context.preliminary)

    def _route(
        self, preliminary: PreliminaryContext[StateT, CallT], /
    ) -> PolicyDecision[CallT]:
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


class SymbolicPrimaryPolicy[StateT, CallT, ProposalT](_PlanHeadPolicy[StateT, CallT, ProposalT]):
    """:248 — the NL track is never consulted; repeated failure of one (pre-state, call)
    pair halts with the discrepancy history."""

    def required_inputs(
        self, context: PreliminaryContext[StateT, CallT], /
    ) -> TrackRequest:
        return TrackRequest(nl_proposal=False)

    def _repeated_failure_escape(
        self, head: CallT, failure_count: int
    ) -> PolicyDecision[CallT]:
        return Halt(
            call=head,
            reason=f"(pre-state, call) failed {failure_count}x under SYMBOLIC_PRIMARY — "
                   f"halting with the discrepancy history rather than strengthening the model",
        )


class AdvisoryTwoTrackPolicy[StateT, CallT, ProposalT](_PlanHeadPolicy[StateT, CallT, ProposalT]):
    """:249 — the advisory proposal is a required track input on enacting cycles, and
    repeated failure escapes to the NL RecoveryProposer instead of halting."""

    def required_inputs(
        self, context: PreliminaryContext[StateT, CallT], /
    ) -> TrackRequest:
        """V1 advisory's information need: NL evidence beside every call it ENACTS —
        exactly the accepted per-execution consultation, declared instead of enum-gated.
        The routing is pure, so the policy can see its own would-be decision from the
        preliminary context and request the proposal only when that decision is Execute
        (a halt/replan/escape needs no advisory evidence in frozen V1)."""
        return TrackRequest(nl_proposal=isinstance(self._route(context), Execute))

    def _repeated_failure_escape(
        self, head: CallT, failure_count: int
    ) -> PolicyDecision[CallT]:
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
