"""Typed `TrackDivergence` — channel 2 of 3 (SUPERVISOR_P0_P4_CONTRACT.md:142-150).

NL/VLM track versus symbolic track disagreement or representation issues.

The track comparator emits this channel and explicitly does NOT classify environment-vs-model
prediction errors (:47) — those are ExecutionDiscrepancy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, Tuple


class DivergenceKind(StrEnum):
    CONTRADICTION = "contradiction"
    COVERAGE_GAP = "coverage_gap"
    TRANSLATION_RESIDUAL = "translation_residual"
    CONFIDENCE_MISMATCH = "confidence_mismatch"
    BENIGN_ABSTRACTION_MISMATCH = "benign_abstraction_mismatch"


@dataclass(frozen=True, slots=True)
class TrackDivergence:
    kind: DivergenceKind
    message: str = ""
    nl_view: str = ""
    symbolic_view: str = ""
    residual: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "residual", tuple(self.residual))

    @property
    def is_benign(self) -> bool:
        return self.kind is DivergenceKind.BENIGN_ABSTRACTION_MISMATCH

    def canonical(self) -> Dict[str, Any]:
        return {
            "channel": "TrackDivergence",
            "kind": str(self.kind),
            "message": self.message,
            "nl_view": self.nl_view,
            "symbolic_view": self.symbolic_view,
            "residual": list(self.residual),
        }
