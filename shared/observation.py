"""V1 observation contract (SUPERVISOR_P0_P4_CONTRACT.md:68, :285; section18.md §F).

V1 freezes WHICH channel carries WHAT, and which track may read it. The point is to stop exact
state leaking into a partial-observation consumer, and to stop belief-derived data leaking into
the symbolic track.

Four channels:

  PUBLIC_EXECUTION_RESULT — the terminal typed outcome of an executive skill. This is the
      executive's feedback channel. Both tracks may read it.
  EXACT_STATE            — the canonical StateSnapshot, normalized from authoritative world state
      (Decision 4). In V1 the symbolic track reads this and it is exact (:167). The NL track reads
      the same typed data (:169 — text/typed only), NOT the belief grid: a NL track consuming the
      belief grid would inherit the rendered-grid defects deferred by Decision 9 plus the
      transposed view convention in obs_parser.py:112-140.
  BACKEND_LOCAL_OBSERVATION — the raw 3x3 egocentric MiniGrid view
      (multi_agent_box_push_env.py:357-364). Partial and occluded. PRESERVED for later
      partial-observation milestones and NOT read by either V1 track.
  DEBUG_FULL             — primitive-step detail, rewards, raw labels. Diagnostics only; never an
      input to planning, prediction, monitoring or bookkeeping.

The reward scalar is deliberately absent from every track-visible channel: it is multiplexed and
provably corruptible as a state signal (section18.md §F).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from shared.execution import ExecutionOutcome, RawLabel
from shared.state_snapshot import StateSnapshot


class ObservationChannel(StrEnum):
    PUBLIC_EXECUTION_RESULT = "public_execution_result"
    EXACT_STATE = "exact_state"
    BACKEND_LOCAL_OBSERVATION = "backend_local_observation"
    DEBUG_FULL = "debug_full"


class Track(StrEnum):
    SYMBOLIC = "symbolic"
    NL = "nl"


#: Frozen V1 visibility matrix. A track may read exactly these channels.
V1_VISIBILITY: Mapping[Track, FrozenSet[ObservationChannel]] = {
    Track.SYMBOLIC: frozenset(
        {ObservationChannel.PUBLIC_EXECUTION_RESULT, ObservationChannel.EXACT_STATE}
    ),
    Track.NL: frozenset(
        {ObservationChannel.PUBLIC_EXECUTION_RESULT, ObservationChannel.EXACT_STATE}
    ),
}

#: Channels no V1 track may read. Preserved in the backend for later milestones (Decision 9).
V1_NOT_TRACK_VISIBLE: FrozenSet[ObservationChannel] = frozenset(
    {ObservationChannel.BACKEND_LOCAL_OBSERVATION, ObservationChannel.DEBUG_FULL}
)


def is_visible(track: Track, channel: ObservationChannel) -> bool:
    return channel in V1_VISIBILITY[track]


@dataclass(frozen=True, slots=True)
class ExecutiveObservation:
    """What the executive layer receives after one executive skill attempt.

    Deliberately does NOT carry the reward scalar, the local 3x3 view, or the belief grid.
    `raw_label` is present for provenance only and must not be consumed by the monitor, the
    planner, or repeated-failure bookkeeping (Decision 3).
    """
    outcome: ExecutionOutcome
    state: StateSnapshot
    raw_label: Optional[RawLabel] = None
    primitive_steps: int = 0
    notes: Tuple[str, ...] = field(default_factory=tuple)

    #: BINDING RULE for `notes` and `primitive_steps`, the same one `raw_label` carries: they are
    #: DIAGNOSTIC PROVENANCE. Neither may be consumed by the monitor, the planner, applicability,
    #: or repeated-failure bookkeeping — those read the typed `outcome` and the canonical state.
    #: `notes` must never carry reward values, belief-derived content, or rendered-grid content;
    #: it is free text on an object BOTH tracks may read (see `V1_VISIBILITY`), so anything
    #: smuggled through it reaches the symbolic side outside the frozen channels.

    def __post_init__(self) -> None:
        if self.primitive_steps < 0:
            raise ValueError("primitive_steps must be non-negative")
        object.__setattr__(self, "notes", tuple(self.notes))

    def canonical(self) -> Dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "state": self.state.world_key(),
            "raw_label": str(self.raw_label) if self.raw_label is not None else None,
            "primitive_steps": self.primitive_steps,
            "notes": list(self.notes),
        }
