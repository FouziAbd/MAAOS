"""The exact-projection symbolic track (DK2) — `shared.contracts.SymbolicTrack` for a fully
observable domain whose symbolic state is a pure projection of the authoritative state.

Extracted from `tests/probe_counter.py::CounterSymbolicTrack`; the same three-method shape
BoxPush's `symbolic/belief.py::ExactSymbolicBelief` exposes, minus the Decision-13.8
executive-tracked fluents BoxPush maintains from outcomes (`in_pose`). A domain that needs
outcome-maintained fluents writes its own track; every fully observable domain uses this one.

Obligations carried from the contract (`shared/contracts/tracks.py`):
- `sync` before `state`: reading an unsynced track is a programming error, raised loudly;
- `record_outcome` is evidence intake ONLY — it stores the result and never patches the
  projection (patching the projection from outcomes is how a model starts believing its own
  predictions) and never consults the environment.
"""
from __future__ import annotations

from typing import Callable, Generic, List, Optional, TypeVar

from shared.execution import ExecutionResult

StateT = TypeVar("StateT")
SymbolicStateT = TypeVar("SymbolicStateT")


class ProjectionTrack(Generic[StateT, SymbolicStateT]):
    """`state` is always `project(<last synced authoritative state>)`."""

    def __init__(self, project: Callable[[StateT], SymbolicStateT]) -> None:
        self._project = project
        self._state: Optional[SymbolicStateT] = None
        self.recorded: List[ExecutionResult] = []

    def sync(self, snapshot: StateT, /) -> None:
        self._state = self._project(snapshot)

    @property
    def state(self) -> SymbolicStateT:
        if self._state is None:
            raise RuntimeError(
                f"{type(self).__name__}.sync(state) must be called before reading .state"
            )
        return self._state

    def record_outcome(self, result: ExecutionResult, /) -> None:
        self.recorded.append(result)


__all__ = ["ProjectionTrack"]
