"""Reasoning-track contracts (R1 — report Phase 1 item 1, fitted to the current seams).

Two track shapes exist in V1 and they are deliberately NOT forced into one protocol:

- `SymbolicTrack` is the stateful symbolic component exactly as the runtime consumes it
  today: authoritative-state synchronization in, symbolic state out, typed execution
  results recorded. Planning, applicability, prediction, and monitoring currently reach
  the runtime as separate domain-owned services; bundling them into one injected surface
  is R4's `DomainBundle` (DEFERRED there), not this contract's job.

- `ReasoningTrack` is the observe/propose shape of the report's advisory track, fitted to
  the shipped NL track: it observes typed situations and outcomes, and proposes against a
  task. Its proposal type is track-owned (`ProposalT_co`); the runtime never unpacks it
  except through the comparator contract.

Aligning the symbolic side onto a propose() lifecycle is R3's comparison-lifecycle work;
doing it here would change behavior, which R1 forbids.
"""
from __future__ import annotations

from typing import Optional, Protocol, TypeVar, runtime_checkable

from shared.execution import ExecutionOutcome, ExecutionResult

StateT_contra = TypeVar("StateT_contra", contravariant=True)
SymbolicStateT_co = TypeVar("SymbolicStateT_co", covariant=True)
TaskT_contra = TypeVar("TaskT_contra", contravariant=True)
ProposalT_co = TypeVar("ProposalT_co", covariant=True)


@runtime_checkable
class SymbolicTrack(Protocol[StateT_contra, SymbolicStateT_co]):
    """The belief-holding symbolic seam: sync-before-use, typed outcomes recorded."""

    def sync(self, snapshot: StateT_contra, /) -> None:
        """Adopt the authoritative state. Must be called before `state` is read."""
        ...

    @property
    def state(self) -> SymbolicStateT_co:
        """The current symbolic state, derived exclusively from synced authoritative state."""
        ...

    def record_outcome(self, result: ExecutionResult, /) -> None:
        """Record one realized typed execution result. Evidence intake only — recording an
        outcome must never consult the environment."""
        ...


@runtime_checkable
class ReasoningTrack(Protocol[StateT_contra, TaskT_contra, ProposalT_co]):
    """An advisory reasoning track: observes typed situations, proposes against a task.

    A proposal is evidence for the orchestration layer; it executes nothing by itself.
    """

    def observe(
        self,
        state: StateT_contra,
        last_action_label: Optional[str] = None,
        last_outcome: Optional[ExecutionOutcome] = None,
        /,
    ) -> None:
        """Feed the track one typed situation (and, post-execution, the labeled outcome)."""
        ...

    def propose(self, task: TaskT_contra, /) -> ProposalT_co:
        """One proposal for the current situation. Malformed track output arrives typed
        INSIDE the proposal; only an escaping exception is infrastructure."""
        ...
