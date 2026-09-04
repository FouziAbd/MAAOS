"""Generic environment contract (R1 — report Part II / Phase 1 item 1).

The domain-neutral mirror of the frozen `shared.backend_contract.V1Environment` surface:
same six methods, same lifecycle obligations, with the three domain-owned types the report
names — state, action (grounded call), execution result — plus the public observation
channel as type parameters instead of concrete V1 types. `V1Environment` remains the
authoritative V1 contract and is untouched; this protocol exists so a non-BoxPush domain
(R5 probe onward) can satisfy the same runtime seam without importing V1 vocabulary.

Everything `V1Environment`'s docstrings oblige (authoritative full state, typed execution
outcomes, no reachability/feasibility query surface) carries over unchanged: this contract
deliberately exposes NO oracle the symbolic side could consult before choosing.
"""
from __future__ import annotations

from typing import Optional, Protocol, TypeVar, runtime_checkable

StateT_co = TypeVar("StateT_co", covariant=True)
CallT_contra = TypeVar("CallT_contra", contravariant=True)
ExecutionT_co = TypeVar("ExecutionT_co", covariant=True)
ObservationT_co = TypeVar("ObservationT_co", covariant=True)


@runtime_checkable
class Environment(Protocol[StateT_co, CallT_contra, ExecutionT_co, ObservationT_co]):
    """The only environment surface the executive layer may use, domain-neutrally typed."""

    def reset(self, *, seed: Optional[int] = None) -> StateT_co:
        """Reset and return the canonical initial state. Must precede any other method."""
        ...

    def observe(self) -> ObservationT_co:
        """Public observation channel, kept separate from the authoritative full state."""
        ...

    def export_full_state(self) -> StateT_co:
        """Authoritative exact state — the sole source of canonical truth."""
        ...

    def execute_skill(self, call: CallT_contra, /) -> ExecutionT_co:
        """Execute one grounded executive call; returns the domain's typed outcome union.

        The union covers both realized execution results and typed pre-execution
        rejections; symbolic applicability verdicts are deliberately NOT part of it
        (the environment must never evaluate symbolic preconditions).
        """
        ...

    def is_terminal(self) -> bool:
        ...

    def render(self) -> object:
        """Optional visualization; never a state source."""
        ...
