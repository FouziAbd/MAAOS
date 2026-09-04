"""Planner result contract (SUPERVISOR_P0_P4_CONTRACT.md:120-129).

The classical planner returns EXACTLY ONE typed result:

  - PlanFound(plan)
  - NoPlan(reason)          — a legitimate symbolic-track result, routed to the orchestrator (:128)
  - PlannerFailure(error)   — a computation/infrastructure problem; becomes an InfrastructureFault
                              and must NEVER be treated as evidence the task is unsolvable (:129)

Conflating these is explicitly prohibited. `NoPlan` and `PlannerFailure` are different types, not
different values of one field, so the distinction cannot be lost by accident.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from shared.value_contracts import RuntimeCall
from shared.versioning import ModelVersion


@dataclass(frozen=True, slots=True)
class PlannerResult(ABC):
    """Abstract base. Exactly one of the three subclasses is returned per planning call.

    Abstract so an `if/elif` dispatch cannot silently fall through to an instantiable base whose
    flags are all False — the classic `if not r.is_plan: treat as NoPlan` bug that conflates
    PlannerFailure with NoPlan.
    """

    def __new__(cls, *args, **kwargs):
        if cls is PlannerResult:
            raise TypeError(
                "PlannerResult is abstract; construct one of its concrete subclasses so the "
                "distinction it exists to preserve cannot be lost"
            )
        return object.__new__(cls)

    @property
    def is_plan(self) -> bool:
        return isinstance(self, PlanFound)

    @property
    def is_no_plan(self) -> bool:
        return isinstance(self, NoPlan)

    @property
    def is_failure(self) -> bool:
        return isinstance(self, PlannerFailure)

    @abstractmethod
    def canonical(self) -> Dict[str, Any]:
        """Every concrete result serializes (the trace records the plan channel)."""


@dataclass(frozen=True, slots=True)
class PlanFound[CallT: RuntimeCall](PlannerResult):
    """R6: generic in the domain-owned call type (bounded by `RuntimeCall` for `cost` and
    `canonical`); V1 holds `PlanFound[GroundedSkillCall]`."""
    plan: Tuple[CallT, ...]
    model_version: Optional[ModelVersion] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan", tuple(self.plan))

    @property
    def cost(self) -> int:
        return sum(c.cost for c in self.plan)

    @property
    def length(self) -> int:
        return len(self.plan)

    def canonical(self) -> Dict[str, Any]:
        return {
            "result": "PlanFound",
            "plan": [c.canonical() for c in self.plan],
            "cost": self.cost,
            "model_version": str(self.model_version) if self.model_version else None,
        }


@dataclass(frozen=True, slots=True)
class NoPlan(PlannerResult):
    """The symbolic abstraction admits no plan. A SEMANTIC result, not a fault."""
    reason: str
    model_version: Optional[ModelVersion] = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("NoPlan requires a reason")

    def canonical(self) -> Dict[str, Any]:
        return {"result": "NoPlan", "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PlannerFailure(PlannerResult):
    """The planner could not compute an answer (error/timeout). An INFRASTRUCTURE problem."""
    error: str
    timed_out: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.error:
            raise ValueError("PlannerFailure requires an error")

    def canonical(self) -> Dict[str, Any]:
        return {"result": "PlannerFailure", "error": self.error, "timed_out": self.timed_out}

    def to_infrastructure_fault(self):
        """:129 — PlannerFailure becomes an InfrastructureFault."""
        from shared.faults import FaultKind, InfrastructureFault
        return InfrastructureFault(
            kind=FaultKind.PLANNER_COMPUTATION_FAILURE,
            message=self.error,
            detail=self.detail,
        )
