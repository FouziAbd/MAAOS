"""Typed `ExecutionDiscrepancy` — channel 1 of 3 (SUPERVISOR_P0_P4_CONTRACT.md:133-140).

Model/prediction versus ACTUAL EXECUTION. This channel is about the symbolic model being
optimistic or wrong relative to the authoritative backend.

It is NOT for NL-vs-symbolic disagreement (that is TrackDivergence) and NOT for interface/runtime
faults (that is InfrastructureFault). The three must never be conflated.

An execution failure of a symbolically APPLICABLE skill is the expected V1 signal (:139, :271).
It is never a reason to add a feasibility oracle to symbolic applicability.

TWO COMPARISON BASES (P0_V1_DECISIONS Decision 13)
--------------------------------------------------
A prediction can be checked in two independent ways, and V1 keeps both:

  WORLD_STATE          the symbolic skill declared a deterministic world effect (an intended box
                       or agent target position) and the predictor grounded it. Compared against
                       `StateSnapshot.world_key()`.
  SYMBOLIC_PROJECTION  the monitored subset of the symbolic projection
                       (`ProjectionContract.monitored_key`).

Earlier this type carried only the world pair, which made `STATE_EFFECT_MISMATCH` unconstructible
for a monitor comparing projections — the one discrepancy kind the projection exists to raise.
Both pairs now exist as separate, correctly named fields. A symbolic key is never written into a
field named `*_world_key`: the two are different criteria and conflating them would erase the
distinction Decision 13 draws.

Recording a pair is *evidence*, not licence: predicting a world effect is allowed (Decision 13.2),
predicting one by asking the backend whether the skill will succeed is not (Decision 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional, Tuple

from shared.comparison_keys import SymbolicKey, WorldKey
from shared.value_contracts import RuntimeCall
from shared.versioning import ModelVersion


class DiscrepancyKind(StrEnum):
    UNEXPECTED_OUTCOME = "unexpected_outcome"
    STATE_EFFECT_MISMATCH = "state_effect_mismatch"
    EXECUTION_FAILURE_OF_APPLICABLE_SKILL = "execution_failure_of_applicable_skill"
    DURATION_ANOMALY = "duration_anomaly"      # reserved for later temporal milestones


class ComparisonBasis(StrEnum):
    """What a recorded predicted/observed pair actually compares."""
    WORLD_STATE = "world_state"
    SYMBOLIC_PROJECTION = "symbolic_projection"


@dataclass(frozen=True, slots=True)
class ExecutionDiscrepancy[CallT: RuntimeCall]:
    """One discrepancy between prediction/model and authoritative execution.

    R6: generic in the domain-owned call type (bounded by `RuntimeCall` for `canonical`);
    V1 holds `ExecutionDiscrepancy[GroundedSkillCall]`.

    `STATE_EFFECT_MISMATCH` requires at least one COMPLETE comparison pair, and at least one
    recorded pair must actually differ. Both halves matter: a mismatch with no pair records no
    evidence, and a mismatch whose every pair agrees is a false report.

    Every other kind may carry pairs as optional context — including none at all, which is the
    normal case for `EXECUTION_FAILURE_OF_APPLICABLE_SKILL`, whose evidence is the authoritative
    typed `ExecutionOutcome` rather than a state comparison (Decision 13.7).
    """
    kind: DiscrepancyKind
    call: CallT
    predicted_world_key: Optional[WorldKey] = None
    observed_world_key: Optional[WorldKey] = None
    predicted_symbolic_key: Optional[SymbolicKey] = None
    observed_symbolic_key: Optional[SymbolicKey] = None
    message: str = ""
    model_version: Optional[ModelVersion] = None

    def __post_init__(self) -> None:
        # The types are enforced, not merely documented. Both keys are sha256 hex, so as plain
        # `str` a symbolic key dropped into a world field is undetectable — which is precisely the
        # confusion Decision 13 exists to prevent.
        for field_name, expected in (
            ("predicted_world_key", WorldKey), ("observed_world_key", WorldKey),
            ("predicted_symbolic_key", SymbolicKey), ("observed_symbolic_key", SymbolicKey),
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, expected):
                raise TypeError(
                    f"{field_name} must be a {expected.__name__} "
                    f"(from StateSnapshot.world_key() / ProjectionContract.monitored_key()), "
                    f"got {type(value).__name__}"
                )

        # A half pair is never evidence of anything, on any kind.
        if (self.predicted_world_key is None) != (self.observed_world_key is None):
            raise ValueError("world-state evidence requires both predicted and observed keys")
        if (self.predicted_symbolic_key is None) != (self.observed_symbolic_key is None):
            raise ValueError("symbolic evidence requires both predicted and observed keys")

        # One check, not two: an empty `comparison_bases` implies an empty `mismatched_bases`, so
        # a separate "at least one pair" guard would be unreachable — and mutation testing duly
        # showed it could be deleted without failing anything.
        if self.kind is DiscrepancyKind.STATE_EFFECT_MISMATCH and not self.mismatched_bases:
            raise ValueError(
                "a state-effect mismatch must record at least one complete comparison pair "
                "(world-state and/or symbolic projection) whose keys actually differ; got "
                f"{len(self.comparison_bases)} complete pair(s), none of them differing"
            )

    @property
    def comparison_bases(self) -> Tuple[ComparisonBasis, ...]:
        """Which bases carry a complete pair, in declaration order."""
        bases = []
        if self.predicted_world_key is not None:
            bases.append(ComparisonBasis.WORLD_STATE)
        if self.predicted_symbolic_key is not None:
            bases.append(ComparisonBasis.SYMBOLIC_PROJECTION)
        return tuple(bases)

    @property
    def mismatched_bases(self) -> Tuple[ComparisonBasis, ...]:
        """The subset of complete pairs whose keys differ."""
        bases = []
        if self.predicted_world_key is not None and (
            self.predicted_world_key != self.observed_world_key
        ):
            bases.append(ComparisonBasis.WORLD_STATE)
        if self.predicted_symbolic_key is not None and (
            self.predicted_symbolic_key != self.observed_symbolic_key
        ):
            bases.append(ComparisonBasis.SYMBOLIC_PROJECTION)
        return tuple(bases)

    def canonical(self) -> Dict[str, Any]:
        return {
            "channel": "ExecutionDiscrepancy",
            "kind": str(self.kind),
            "call": self.call.canonical(),
            "predicted_world_key": self.predicted_world_key,
            "observed_world_key": self.observed_world_key,
            "predicted_symbolic_key": self.predicted_symbolic_key,
            "observed_symbolic_key": self.observed_symbolic_key,
            "comparison_bases": [str(b) for b in self.comparison_bases],
            "mismatched_bases": [str(b) for b in self.mismatched_bases],
            "message": self.message,
            "model_version": str(self.model_version) if self.model_version else None,
        }
