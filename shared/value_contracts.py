"""Structural contracts for the domain-owned VALUE types the runtime handles (R5 — report
Phase 5, closing the question R4 deferred: "which of the loop's remaining reads need a
contract method versus a structural protocol on the domain's own types").

The generic runtime never interprets a state, a call, a task, or an advisory proposal. It
does, however, HANDLE them: it keys repeated-failure bookkeeping on them, tests the goal,
labels the observation it feeds the advisory track, and records them in the trace. The
R5 probe domain (`tests/probe_counter.py`) surfaced exactly which members those handling
sites require, and the answer is small enough to be a structural protocol per type — no
`DomainServices` method was needed for any of them:

    RuntimeState       world_key()       repeated-failure key (`runtime/executive_history.py`),
                                         trace serialization (`TraceEntry.canonical`)
                       same_world(other) the shared `ExecutionResult` failure-class check
    RuntimeCall        skill             the observation label fed to the advisory track
                       cost              plan cost in `PlanFound.canonical`
                       key()             repeated-failure key
                       canonical()       trace / result / discrepancy serialization
                       (and value equality — see the class docstring)
    TaskContract       is_satisfied_by() the loop's goal test
                       canonical()       trace serialization
    AdvisoryProposal   call, coverage,   the three proposal columns the loop records on an
                       confidence        executed entry (evidence only; never decision input)

Everything else a domain type carries is opaque to the runtime by construction — the probe
tests pin that such extra content reaches the trace and the policy unchanged.

The frozen V1 types (`StateSnapshot`, `GroundedSkillCall`, `Task`, `nl.track.NLProposal`)
satisfy these protocols as they are; nothing about them changed. The protocols are
`runtime_checkable` so a composition root can assert conformance at assembly, and the
member sets are deliberately MINIMAL: adding a member here widens what every domain must
supply, so it needs a concrete runtime requirement, not a convenience.

R6 (report Phase 6 acceptance "core contracts, runtime ... pass static type checking"):
the protocols moved here from `shared/contracts/domain_types.py` (which re-exports them)
because they became the BOUNDS of the shared record types' type parameters
(`ExecutionResult[StateT, CallT]`, `PlanFound[CallT]`, `ExecutionDiscrepancy[CallT]`,
`TraceEntry[StateT, CallT, TaskT]`). Those records sit below `shared.contracts` — the
contracts package imports them — so the bounds must live in a leaf module the records can
import without a cycle. This module imports only `shared.comparison_keys` and
`shared.reports`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Self, runtime_checkable

from shared.comparison_keys import WorldKey
from shared.reports import ConfidenceReport, CoverageReport


@runtime_checkable
class RuntimeState(Protocol):
    """What the runtime requires of an authoritative state value."""

    def world_key(self) -> WorldKey:
        """Digest of the canonical world content — the state half of the repeated-failure
        key and the trace's state column. Episode bookkeeping must be excluded so two
        attempts from the same world situation share a key."""
        ...

    def same_world(self, other: Self, /) -> bool:
        """World-content equality (the basis of the typed failure-class check)."""
        ...


@runtime_checkable
class RuntimeCall(Protocol):
    """What the runtime requires of a grounded executive call value.

    Calls must also compare by VALUE (`==`): the loop matches an enacted call against its
    standing recovery advice and a discrepancy's call against the escaped one. A frozen
    dataclass provides this; a type with identity equality would silently break both."""

    @property
    def skill(self) -> Any:
        """The call's skill/action name; `str()` of it labels the advisory observation."""
        ...

    @property
    def cost(self) -> int:
        ...

    def key(self) -> str:
        """Deterministic serialization — the call half of the repeated-failure key."""
        ...

    def canonical(self) -> Dict[str, Any]:
        ...


@runtime_checkable
class TaskContract(Protocol):
    """What the runtime requires of a task value: a pure goal test over the authoritative
    state (no environment access) and a serializable form for the trace."""

    def is_satisfied_by(self, state: Any, /) -> bool:
        ...

    def canonical(self) -> Dict[str, Any]:
        ...


@runtime_checkable
class AdvisoryProposal(Protocol):
    """What the runtime records from an advisory track's proposal. The proposal type stays
    track-owned; only these three columns are read, and only for the trace."""

    @property
    def call(self) -> Optional[RuntimeCall]:
        """The proposed call (recorded and serialized through the trace's call column), or
        None when the track produced no well-formed one."""
        ...

    @property
    def coverage(self) -> Optional[CoverageReport]:
        ...

    @property
    def confidence(self) -> Optional[ConfidenceReport]:
        ...


__all__ = ["AdvisoryProposal", "RuntimeCall", "RuntimeState", "TaskContract"]
