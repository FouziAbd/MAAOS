"""Comparator and recovery-provider contracts (R1 — report Phase 1 item 1).

Both are callable protocols fitted to the existing function-shaped implementations
(`runtime.comparator.compare_tracks`, `nl.recovery.propose_recovery`), so the shipped
components satisfy them without modification.

Frozen channel obligations carried into the contracts:

- A comparator reports `TrackDivergence` evidence — the ONLY component that may raise that
  channel. It never selects or executes an action and never classifies environment-vs-model
  issues (that is `ExecutionDiscrepancy`, owned by the monitor).
- A recovery provider proposes calls as ADVICE over typed discrepancy evidence. Its output
  has no execution authority: every recovery call passes through the same validation gates
  and the same executor as any other selected call.

R3 owns the comparator's lifecycle/report restructuring (structured comparison report,
domain-owned equivalence, configurable thresholds); this contract pins only the current
typed seam. DEFERRED to R3 accordingly.
"""
from __future__ import annotations

from typing import Optional, Protocol, Tuple, TypeVar, runtime_checkable

from shared.discrepancy import ExecutionDiscrepancy
from shared.divergence import TrackDivergence

CallT_contra = TypeVar("CallT_contra", contravariant=True)
ProposalT_contra = TypeVar("ProposalT_contra", contravariant=True)
CallT_co = TypeVar("CallT_co", covariant=True)


@runtime_checkable
class ProposalComparator(Protocol[CallT_contra, ProposalT_contra]):
    """Compare the symbolic selection with an advisory proposal; emit divergence evidence."""

    def __call__(
        self,
        symbolic_call: Optional[CallT_contra],
        nl_proposal: Optional[ProposalT_contra],
        /,
    ) -> Tuple[TrackDivergence, ...]:
        ...


@runtime_checkable
class RecoveryProvider(Protocol[CallT_co]):
    """Propose recovery calls (possibly none) over one typed execution discrepancy."""

    def __call__(self, discrepancy: ExecutionDiscrepancy, /) -> Tuple[CallT_co, ...]:
        ...
