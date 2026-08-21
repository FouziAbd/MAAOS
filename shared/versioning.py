"""Model version / provenance / patch support (SUPERVISOR_P0_P4_CONTRACT.md:80).

Deliberately minimal: enough to stamp every IR, prediction, plan and trace entry with the
model version that produced it, and to record where a model element came from. V1 does not
learn, so patches are recorded but never applied automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True, order=True, slots=True)
class ModelVersion:
    """Monotonic symbolic-model version.

    `revision` increments whenever the frozen domain IR changes. `label` is human-facing.
    """
    revision: int
    label: str = "v1"

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("ModelVersion.revision must be non-negative")

    def next(self, label: Optional[str] = None) -> "ModelVersion":
        return ModelVersion(revision=self.revision + 1, label=label or self.label)

    def __str__(self) -> str:
        return f"{self.label}.r{self.revision}"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a model element came from, and under which model version."""
    source: str                      # e.g. "pddl/box_push_domain.pddl", "supervisor-contract"
    model_version: ModelVersion
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("Provenance.source must be non-empty")


@dataclass(frozen=True, slots=True)
class ModelPatch:
    """A proposed change to the symbolic model.

    V1 records patches; it never applies them silently. Strengthening the symbolic model in
    response to an execution failure is prohibited (P0_V1_DECISIONS Decision 6), so a patch
    that does so must be an explicit, reviewed change of the frozen domain.
    """
    target: str                      # e.g. "skill:Push", "predicate:in_pose"
    rationale: str
    from_version: ModelVersion
    to_version: ModelVersion
    applied: bool = False
    tags: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.to_version <= self.from_version:
            raise ValueError("ModelPatch.to_version must be greater than from_version")
