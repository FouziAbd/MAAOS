"""Reasoning-track contracts (R1 — report Phase 1 item 1, fitted to the current seams).

Two track shapes exist in V1 and they are deliberately NOT forced into one protocol:

- `SymbolicTrack` is the stateful symbolic component exactly as the runtime consumes it:
  authoritative-state synchronization in, symbolic state out, typed execution results
  recorded. Planning, grounding, applicability, prediction, and monitoring reach the
  runtime through the separate stateless `DomainServices` bundle
  (`shared/contracts/domain.py`, R4); the runtime holds one injected instance of each.

- `ReasoningTrack` is the observe/propose shape of the report's advisory track, fitted to
  the shipped NL track: it observes typed situations and outcomes, and proposes against a
  task. Its proposal type is track-owned (`ProposalT_co`); the runtime never unpacks it
  except through the comparator contract.

The symbolic side was deliberately NOT aligned onto a propose() lifecycle: R3 compares the
call an Execute decision would enact (the loop's `_compared_call`) against the advisory
proposal, so the symbolic plan channel stays what the planner returns.
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
