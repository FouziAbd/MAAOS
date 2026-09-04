"""shared.contracts — the narrow typed contracts (report Phase 1, extended by R3/R4).

The R1 protocols plus the immutable contexts and typed decision variants the target
architecture composes against, consumed phase by phase: R2 policies, R3 the comparison
lifecycle, R4 the domain-services bundle and constructor injection of every variable
component into the generic runtime.

Rules embodied here:
- generic only in the domain-owned types the report names (state, call/action, execution
  result, plus the track-owned proposal and observation); every other channel stays the
  existing shared typed result type — no `Any`-primary or dict-shaped abstraction;
- no BoxPush vocabulary in any contract name, field, or parameter;
- no speculative belief/probability/temporal/concurrency surface.

Static conformance of the shipped implementations is witnessed in
`tests/contract_conformance.py` (mypy) and exercised by `tests/test_r1_contracts.py`.
"""
from shared.contracts.comparison import (
    ActionEquivalence,
    ComparedAspect,
    ComparisonFinding,
    ComparisonReport,
    FindingSeverity,
    ProposalComparator,
    RecoveryProvider,
)
from shared.contracts.domain import DomainServices, Prediction
from shared.contracts.environment import Environment
from shared.contracts.policy import (
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
from shared.contracts.tracks import ReasoningTrack, SymbolicTrack

__all__ = [
    "Environment",
    "DomainServices",
    "Prediction",
    "SymbolicTrack",
    "ReasoningTrack",
    "ActionEquivalence",
    "ComparedAspect",
    "ComparisonFinding",
    "ComparisonReport",
    "FindingSeverity",
    "ProposalComparator",
    "RecoveryProvider",
    "OrchestrationPolicyContract",
    "PreliminaryContext",
    "OrchestrationContext",
    "TrackRequest",
    "PolicyDecision",
    "Execute",
    "Replan",
    "RequestProposal",
    "Halt",
]
