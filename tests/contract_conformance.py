"""R1 static-conformance witnesses: the shipped components satisfy `shared.contracts`.

This module is the R1 acceptance evidence for "existing components satisfy the protocols
under static checking". Check it with:

    python -m mypy --ignore-missing-imports --follow-imports=silent tests/contract_conformance.py

Every witness is a typed identity: if a shipped component stopped satisfying its contract,
the annotated assignment/return below would fail mypy. `tests/test_r1_contracts.py` imports
this module and calls the witnesses with real instances, so the same claims also hold at
runtime (structurally, via the runtime_checkable protocols).

Deliberately NOT test_-prefixed: it is a conformance surface, not a test case module.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from shared.backend_contract import V1Environment
from shared.contracts import (
    DomainServices,
    Environment,
    Halt,
    OrchestrationContext,
    OrchestrationPolicyContract,
    PolicyDecision,
    PreliminaryContext,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
    TrackRequest,
)
from shared.discrepancy import ExecutionDiscrepancy
from shared.execution import ExecutionResult
from shared.ids import BoxId
from shared.planner_result import PlanFound
from shared.skills import GroundedSkillCall, MalformedCall, UngroundedCall
from shared.state_snapshot import StateSnapshot
from shared.symbolic_state import SymbolicState
from shared.task import Task
from shared.trace_schema import TraceEntry

from domain.box_push_v1 import TASK_DELIVER_BOTH
from nl.recovery import propose_recovery
from nl.track import MalformedProposal, NLProposal, NLTrack
from app.box_push_v1 import BoxPushDomainServices, V1Loop, build_loop
from app.comparator import DEFAULT_COMPARATOR, BoxPushActionComparator
from runtime.loop import EpisodeResult
from runtime.policies import AdvisoryTwoTrackPolicy, SymbolicPrimaryPolicy
from symbolic import ExactSymbolicBelief

# The V1 execution-outcome union `V1Environment.execute_skill` already returns.
V1ExecutionOutcome = Union[ExecutionResult, MalformedCall, UngroundedCall]

# The concrete V1 parameterizations of the generic contracts.
V1EnvironmentContract = Environment[
    StateSnapshot, GroundedSkillCall, V1ExecutionOutcome, Mapping[str, Any]
]
V1SymbolicTrackContract = SymbolicTrack[StateSnapshot, SymbolicState]
V1ReasoningTrackContract = ReasoningTrack[StateSnapshot, Task, NLProposal]
V1PolicyContract = OrchestrationPolicyContract[StateSnapshot, GroundedSkillCall, NLProposal]
V1DomainServicesContract = DomainServices[StateSnapshot, SymbolicState, GroundedSkillCall]


def environment_conforms(env: V1Environment) -> V1EnvironmentContract:
    """Anything satisfying the frozen V1Environment (e.g. BoxPushV1Adapter) satisfies the
    generic Environment contract at its V1 parameterization."""
    return env


def symbolic_track_conforms(belief: ExactSymbolicBelief) -> V1SymbolicTrackContract:
    return belief


def domain_services_conform(services: BoxPushDomainServices) -> V1DomainServicesContract:
    """R4: the BoxPush domain-services bundle satisfies the generic contract statically."""
    return services


def reasoning_track_conforms(track: NLTrack) -> V1ReasoningTrackContract:
    return track


# R3: the report-shaped comparator contract is satisfied by the scoped comparator class
# (compare_tracks survives only as a legacy divergence-tuple wrapper, no longer a witness).
comparator_conforms: ProposalComparator[GroundedSkillCall, NLProposal] = DEFAULT_COMPARATOR


def comparator_class_conforms(
    comparator: BoxPushActionComparator,
) -> ProposalComparator[GroundedSkillCall, NLProposal]:
    return comparator


recovery_conforms: RecoveryProvider[GroundedSkillCall] = propose_recovery


def symbolic_primary_policy_conforms(
    policy: SymbolicPrimaryPolicy[StateSnapshot, GroundedSkillCall, NLProposal],
) -> V1PolicyContract:
    """R2: the shipped extracted policies satisfy the R1 policy contract statically."""
    return policy


def advisory_two_track_policy_conforms(
    policy: AdvisoryTwoTrackPolicy[StateSnapshot, GroundedSkillCall, NLProposal],
) -> V1PolicyContract:
    return policy


class MinimalHaltPolicy:
    """Test-local conformance witness for the policy contract, kept from R1: it proves the
    contract is implementable without inheriting anything from the shipped R2 policies."""

    def required_inputs(
        self, context: PreliminaryContext[StateSnapshot, GroundedSkillCall]
    ) -> TrackRequest:
        return TrackRequest()

    def decide(
        self, context: OrchestrationContext[StateSnapshot, GroundedSkillCall, NLProposal]
    ) -> PolicyDecision[GroundedSkillCall]:
        return Halt(reason="conformance witness policy always halts")


def policy_conforms(policy: MinimalHaltPolicy) -> V1PolicyContract:
    return policy


# ── R6: the generic shared channels and the generic loop at the V1 parameterization ──────

def v1_loop_is_typed_at_the_v1_parameters(env: V1Environment) -> V1Loop:
    """The composition root returns the loop at the five V1 type parameters; the runtime
    class itself names none of them."""
    return build_loop(env, TASK_DELIVER_BOTH)


def v1_trace_keeps_domain_precision(
    episode: EpisodeResult[StateSnapshot, GroundedSkillCall, Task],
) -> Optional[BoxId]:
    """A V1 trace entry's call columns are `GroundedSkillCall`s — domain fields such as
    `.box` are reachable statically, nothing was widened to `Any`."""
    for entry in episode.history.entries:
        if entry.selected_call is not None:
            return entry.selected_call.box
        if entry.execution is not None:
            return entry.execution.call.box
    return None


def v1_records_are_also_generic_records(
    result: ExecutionResult[StateSnapshot, GroundedSkillCall],
    plan: PlanFound[GroundedSkillCall],
    discrepancy: ExecutionDiscrepancy[GroundedSkillCall],
    entry: TraceEntry[StateSnapshot, GroundedSkillCall, Task],
) -> tuple[
    ExecutionResult[RuntimeState, RuntimeCall],
    PlanFound[RuntimeCall],
    ExecutionDiscrepancy[RuntimeCall],
    TraceEntry[RuntimeState, RuntimeCall, TaskContract],
]:
    """The frozen records are covariant in their (read-only) parameters: what the generic
    runtime handles as protocol-typed records IS the V1 record, no adapter in between."""
    return result, plan, discrepancy, entry


def proposal_narrows_statically(proposal: NLProposal) -> Union[GroundedSkillCall, MalformedCall]:
    """R6 (report Phase 6 item 3): `NLProposal` is a discriminated union, so ONE isinstance
    check proves to mypy which payload is present — `proposal.call` below is a
    `GroundedSkillCall`, never an Optional to unwrap. The pre-R6 single class with two
    optional fields could not make this function type-check without a runtime assert."""
    if isinstance(proposal, MalformedProposal):
        return proposal.malformed
    return proposal.call
