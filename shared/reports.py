"""`CoverageReport` and `ConfidenceReport` (SUPERVISOR_P0_P4_CONTRACT.md:74-76, :183).

The translator maps between NL and symbolic vocabulary and returns both a translated artifact and
an EXPLICIT RESIDUAL for unsupported/ambiguous/lossy information (:25). CoverageReport carries
that residual in typed form; ConfidenceReport carries per-proposal confidence.

Both feed the track comparator, which may raise `TrackDivergence` of kind COVERAGE_GAP,
TRANSLATION_RESIDUAL or CONFIDENCE_MISMATCH. Neither report is itself a divergence — they are
evidence the comparator consumes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """What the symbolic vocabulary could and could not represent."""
    covered: Tuple[str, ...] = field(default_factory=tuple)
    residual: Tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "covered", tuple(self.covered))
        object.__setattr__(self, "residual", tuple(self.residual))

    @property
    def is_complete(self) -> bool:
        return not self.residual

    @property
    def coverage_ratio(self) -> float:
        total = len(self.covered) + len(self.residual)
        return 1.0 if total == 0 else len(self.covered) / total

    def canonical(self) -> Dict[str, Any]:
        return {
            "covered": list(self.covered),
            "residual": list(self.residual),
            "is_complete": self.is_complete,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ConfidenceReport:
    """Confidence attached to a track's proposal.

    V1 uses this descriptively; it is never a probability over world dynamics (V1 is
    deterministic at the symbolic level).
    """
    source: str                       # "nl" | "symbolic"
    confidence: float
    rationale: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if self.source not in ("nl", "symbolic"):
            raise ValueError("ConfidenceReport.source must be 'nl' or 'symbolic'")

    def canonical(self) -> Dict[str, Any]:
        return {"source": self.source, "confidence": self.confidence, "rationale": self.rationale}
