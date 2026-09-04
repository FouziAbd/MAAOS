"""Orchestration-policy contract, contexts, and typed decision variants (R1 — report
Phase 1 items 1, 3, 4).

The report's target policy shape: a policy declares which track inputs it requires from a
`PreliminaryContext`, then decides from a complete `OrchestrationContext`. Both contexts
are immutable; decisions are typed variants in which illegal states are unrepresentable —
`Execute` cannot exist without an executable call.

Fitted to the current typed channels: the planner channel is the shared `PlannerResult`,
head verdicts are the shared `CallValidation`, comparison evidence is the structured
`ComparisonReport` over frozen `TrackDivergence` payloads (R3). Only the three domain-owned
types the report names are generic: state, call, and the advisory proposal.

Phase ownership:
- R2 (done) supplies the concrete `SymbolicPrimaryPolicy`/`AdvisoryTwoTrackPolicy` classes
  in `runtime/policies.py` and makes the loop accept a policy object;
  `runtime.orchestrator.decide` remains as a compatibility shim over the same policies.
- R3 (done) makes requested comparison evidence exist before the final decision: the loop
  acquires the policy's requested track inputs and builds the comparison BEFORE `decide()`,
  and `OrchestrationContext` carries the structured `ComparisonReport` (whose frozen
  `TrackDivergence` payloads still feed the unchanged trace channel) in place of the R1
  divergence tuple.

Decision variants carry their frozen `ExecutiveDecision` enum member so R2 can record
decisions in the existing trace schema without changing the serialized format.

A policy is a pure transformation of context into decision: no environment access, no
mutation, no time advancement. The contract's method surface makes that structural — there
is nothing here through which a policy could reach the backend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Generic, Optional, Protocol, TypeVar, Union, runtime_checkable

from shared.contracts.comparison import ComparisonReport
from shared.orchestration_config import ExecutiveDecision
from shared.planner_result import PlannerResult
from shared.skills import CallValidation

StateT = TypeVar("StateT")
CallT = TypeVar("CallT")
ProposalT = TypeVar("ProposalT")


# ── track acquisition request ─────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class TrackRequest:
    """What a policy wants acquired before it decides. V1 has one optional acquisition:
    the advisory (NL) proposal. The symbolic plan channel is always present in the
    preliminary context and needs no request."""
    nl_proposal: bool = False


# ── immutable contexts ────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PreliminaryContext(Generic[StateT, CallT]):
    """What is known BEFORE track acquisition: the synced state, the symbolic plan
    channel, the typed verdict on the plan head, the repeated-failure bookkeeping for
    that head, and any standing recovery advice awaiting enactment."""
    state: StateT
    planner_result: PlannerResult
    head_validation: Optional[CallValidation] = None
    failure_count: int = 0
    standing_recovery: Optional[CallT] = None

    def __post_init__(self) -> None:
        if self.failure_count < 0:
            raise ValueError("failure_count cannot be negative")


@dataclass(frozen=True, slots=True)
class OrchestrationContext(Generic[StateT, CallT, ProposalT]):
    """The complete decision situation: the preliminary context plus whatever the policy
    requested — the acquired advisory proposal (None when not requested or not available)
    and the structured comparison over it (None exactly when there was no proposal to
    compare; an empty report means genuine agreement)."""
    preliminary: PreliminaryContext[StateT, CallT]
    nl_proposal: Optional[ProposalT] = None
    comparison: Optional[ComparisonReport] = None


# ── typed decision variants ───────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Execute(Generic[CallT]):
    """Execute this call. Cannot exist without an executable call."""
    call: CallT
    reason: str = ""
    decision: ClassVar[ExecutiveDecision] = ExecutiveDecision.EXECUTE

    def __post_init__(self) -> None:
        if self.call is None:
            raise ValueError("Execute requires an executable call")


@dataclass(frozen=True, slots=True)
class Replan(Generic[CallT]):
    """Discard the current plan and replan from fresh belief. Charged nothing itself;
    the loop bounds free repetition."""
    reason: str
    decision: ClassVar[ExecutiveDecision] = ExecutiveDecision.REPLAN

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("Replan requires a reason")


@dataclass(frozen=True, slots=True)
class RequestProposal(Generic[CallT]):
    """Consult the recovery/advisory channel about this call. Cannot exist without the
    call the request is about."""
    call: CallT
    reason: str = ""
    decision: ClassVar[ExecutiveDecision] = ExecutiveDecision.REQUEST_PROPOSAL

    def __post_init__(self) -> None:
        if self.call is None:
            raise ValueError("RequestProposal requires the call it requests advice for")


@dataclass(frozen=True, slots=True)
class Halt(Generic[CallT]):
    """Stop the episode with a reason; optionally the call the halt is about."""
    reason: str
    call: Optional[CallT] = None
    decision: ClassVar[ExecutiveDecision] = ExecutiveDecision.HALT

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("Halt requires a reason")


PolicyDecision = Union[Execute[CallT], Replan[CallT], RequestProposal[CallT], Halt[CallT]]


# ── the policy contract ───────────────────────────────────────────────────────────────
@runtime_checkable
class OrchestrationPolicyContract(Protocol[StateT, CallT, ProposalT]):
    """A pure decision strategy: immutable context in, typed decision out."""

    def required_inputs(
        self, context: PreliminaryContext[StateT, CallT], /
    ) -> TrackRequest:
        """Declare which optional track inputs this policy needs before deciding."""
        ...

    def decide(
        self, context: OrchestrationContext[StateT, CallT, ProposalT], /
    ) -> "PolicyDecision[CallT]":
        """One typed decision for the situation. Pure: no environment access, no mutation."""
        ...
