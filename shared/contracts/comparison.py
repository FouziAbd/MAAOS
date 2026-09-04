"""Comparison and recovery-provider contracts (R1 Phase 1 item 1; restructured by R3 —
report Phase 3 items 1, 3, 5).

R3 upgrades the R1 callable seam to a structured comparison surface:

- `ProposalComparator` — a generic protocol producing a `ComparisonReport` instead of a bare
  divergence tuple, so the report can inform the policy decision (Phase 3 item 7) while the
  frozen `TrackDivergence` payloads inside it keep the serialized trace format unchanged.
- `ComparisonReport`/`ComparisonFinding` — machine-actionable structure over the frozen
  channel: each finding names the compared ASPECT, carries a SEVERITY, and wraps the exact
  `TrackDivergence` evidence payload (whose kind is the classification and whose
  message/views/residual are the evidence references and human-readable summary).
- `ActionEquivalence` — the domain-owned rule deciding whether two DIFFERENT proposed
  actions are equivalent under the domain abstraction (Phase 3 item 3). The comparator asks;
  the domain answers; the generic side holds no such rule.

Frozen channel obligations carried into the contracts:

- A comparator reports evidence — the ONLY component that may raise the `TrackDivergence`
  channel. It never selects or executes an action and never classifies environment-vs-model
  issues (that is `ExecutionDiscrepancy`, owned by the monitor).
- Severity is descriptive V1 evidence (benign vs needs-attention), NOT a calibrated
  measure; raw confidence and its source stay in the underlying reports.
- A recovery provider proposes calls as ADVICE over typed discrepancy evidence. Its output
  has no execution authority: every recovery call passes through the same validation gates
  and the same executor as any other selected call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional, Protocol, Tuple, TypeVar, runtime_checkable

from shared.discrepancy import ExecutionDiscrepancy
from shared.divergence import DivergenceKind, TrackDivergence

CallT_contra = TypeVar("CallT_contra", contravariant=True)
ProposalT_contra = TypeVar("ProposalT_contra", contravariant=True)
CallT_co = TypeVar("CallT_co", covariant=True)


class ComparedAspect(StrEnum):
    """Which aspect of the two proposals a finding is about (Phase 3 item 5)."""
    PROPOSAL_FORM = "proposal_form"          # the advisory track produced no well-formed proposal
    MODEL_COVERAGE = "model_coverage"        # proposal names a skill outside the symbolic model
    TASK_TRANSLATION = "task_translation"    # task content the vocabulary cannot represent
    ACTION_CHOICE = "action_choice"          # the proposed actions themselves
    CONFIDENCE = "confidence"                # the advisory track's own stated confidence


class FindingSeverity(StrEnum):
    """Descriptive V1 severity — never a calibrated probability."""
    BENIGN = "benign"
    ATTENTION = "attention"


@dataclass(frozen=True, slots=True)
class ComparisonFinding:
    """One structured finding: aspect + severity over the frozen evidence payload. The
    wrapped `TrackDivergence` IS the evidence reference (kind = classification,
    message = human-readable summary, nl_view/symbolic_view/residual = compared views)."""
    aspect: ComparedAspect
    severity: FindingSeverity
    divergence: TrackDivergence

    @property
    def classification(self) -> DivergenceKind:
        return self.divergence.kind

    @property
    def summary(self) -> str:
        return self.divergence.message


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """The comparator's answer for one compared proposal pair. Empty findings = genuine
    agreement (the proposal was present and nothing diverged); absence of a comparison is
    represented by the CONTEXT holding no report, never by a manufactured one."""
    findings: Tuple[ComparisonFinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))

    @property
    def divergences(self) -> Tuple[TrackDivergence, ...]:
        """The frozen trace-channel payloads, in finding order."""
        return tuple(f.divergence for f in self.findings)

    @property
    def contradicted(self) -> bool:
        return any(f.classification is DivergenceKind.CONTRADICTION for f in self.findings)

    @property
    def all_benign(self) -> bool:
        return all(f.severity is FindingSeverity.BENIGN for f in self.findings)


@runtime_checkable
class ActionEquivalence(Protocol[CallT_contra]):
    """Domain-owned abstraction-equivalence rule over two DIFFERENT proposed actions."""

    def benign_equivalence(
        self, proposed: CallT_contra, selected: CallT_contra, /
    ) -> Optional[str]:
        """The domain reason the two different actions are equivalent under its
        abstraction, or None when they are not. Identity is not equivalence: callers
        handle `proposed == selected` before asking."""
        ...


@runtime_checkable
class ProposalComparator(Protocol[CallT_contra, ProposalT_contra]):
    """Compare the symbolic selection with an advisory proposal; report evidence only."""

    def compare(
        self,
        symbolic_call: Optional[CallT_contra],
        nl_proposal: Optional[ProposalT_contra],
        /,
    ) -> ComparisonReport:
        ...


@runtime_checkable
class RecoveryProvider(Protocol[CallT_co]):
    """Propose recovery calls (possibly none) over one typed execution discrepancy."""

    def __call__(self, discrepancy: ExecutionDiscrepancy, /) -> Tuple[CallT_co, ...]:
        ...
