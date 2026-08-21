"""Trace schema and executive history (SUPERVISOR_P0_P4_CONTRACT.md:70, :256).

Per the project testing rule, a trace must include: task, state snapshots, proposals, decision,
prediction, execution, discrepancies/divergence/fault history, provenance, and model version.

This module holds ONLY the frozen `TraceEntry` contract. The mutable accumulator that owns
repeated-failure bookkeeping and budget totals lives in `runtime/executive_history.py`, because
:35 and :254-255 assign both to the executive loop manager (P4), not to a typed contract.

That separation is also the guard :118 asks for: repeated-failure bookkeeping must NOT become a
hidden symbolic feasibility predicate. `tests/test_no_backend_imports.py` forbids the symbolic
side from importing `runtime`, so applicability cannot reach the history at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from shared.comparison_keys import SymbolicKey, WorldKey
from shared.discrepancy import ExecutionDiscrepancy
from shared.divergence import TrackDivergence
from shared.execution import ExecutionResult
from shared.faults import InfrastructureFault
from shared.orchestration_config import ExecutiveDecision
from shared.planner_result import PlannerResult
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import CallValidation, GroundedSkillCall
from shared.state_snapshot import StateSnapshot
from shared.task import Task
from shared.versioning import ModelVersion, Provenance


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One executive step's complete record."""
    executive_step: int
    task: Task
    pre_state: StateSnapshot
    model_version: ModelVersion
    provenance: Provenance

    # reasoning
    symbolic_result: Optional[PlannerResult] = None
    symbolic_proposal: Optional[GroundedSkillCall] = None
    nl_proposal: Optional[GroundedSkillCall] = None
    coverage: Optional[CoverageReport] = None
    confidence: Tuple[ConfidenceReport, ...] = field(default_factory=tuple)

    # decision
    decision: Optional[ExecutiveDecision] = None
    selected_call: Optional[GroundedSkillCall] = None
    #: The typed validation VERDICT on `selected_call`. Named `validation`, not `rejection`,
    #: because on the execution path it legitimately holds a `ValidatedCall` — a field called
    #: `rejection` holding an acceptance is exactly the ambiguity Decision 7 exists to remove.
    validation: Optional[CallValidation] = None

    # prediction vs execution — both Decision 13 bases, never conflated
    predicted_world_key: Optional[WorldKey] = None     # grounded deterministic world effect
    predicted_symbolic_key: Optional[SymbolicKey] = None  # ProjectionContract.monitored_key
    execution: Optional[ExecutionResult] = None
    post_state: Optional[StateSnapshot] = None

    # typed report channels — kept strictly separate
    discrepancies: Tuple[ExecutionDiscrepancy, ...] = field(default_factory=tuple)
    divergences: Tuple[TrackDivergence, ...] = field(default_factory=tuple)
    faults: Tuple[InfrastructureFault, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.executive_step < 0:
            raise ValueError("executive_step must be non-negative")
        if self.predicted_world_key is not None and not isinstance(self.predicted_world_key, WorldKey):
            raise TypeError("predicted_world_key must be a WorldKey (Decision 13.6)")
        if self.predicted_symbolic_key is not None and not isinstance(
            self.predicted_symbolic_key, SymbolicKey
        ):
            raise TypeError("predicted_symbolic_key must be a SymbolicKey (Decision 13.6)")

        # ── Lifecycle legality (Decision 2, :163) ────────────────────────────────────
        # One executive cycle either reaches the executor or does not. Representing both at once
        # was possible until now, and the suite's own "complete trace" fixture did exactly that.
        if self.execution is not None:
            if self.validation is not None and self.validation.is_pre_executor_rejection:
                raise ValueError(
                    f"{type(self.validation).__name__} is a PRE-EXECUTOR rejection: the call never "
                    f"reached the executor and consumes zero executive steps (Decision 2), so it "
                    f"cannot coexist with an ExecutionResult in the same cycle"
                )
            early = [f for f in self.faults if f.arises_before_execution]
            if early:
                raise ValueError(
                    f"fault(s) {[str(f.kind) for f in early]} arise before the executor and "
                    f"short-circuit the cycle at the point of detection (:163), so they cannot "
                    f"coexist with an ExecutionResult"
                )
        object.__setattr__(self, "confidence", tuple(self.confidence))
        object.__setattr__(self, "discrepancies", tuple(self.discrepancies))
        object.__setattr__(self, "divergences", tuple(self.divergences))
        object.__setattr__(self, "faults", tuple(self.faults))

    @property
    def executive_steps_consumed(self) -> int:
        """RECORDED structured accounting only — not always the truth about consumption.

        1 when an `ExecutionResult` was recorded (Decision 2). 0 otherwise — which covers
        genuinely-zero situations (a pre-executor rejection, a case-(b) refusal) and a case-(c)
        MID-EXECUTION fault (`shared/faults.py` three-case rule), where one executive step WAS
        consumed but no result exists and the accounting survives only in `fault.detail`.
        P4 must charge case-(c) steps from fault provenance, never from this accessor."""
        return self.execution.accounting.executive_steps if self.execution else 0

    @property
    def primitive_steps_consumed(self) -> int:
        """RECORDED primitive accounting only — a case-(c) entry reports 0 here while its fault
        detail records the primitives that really ran. Same caveat as above."""
        return self.execution.accounting.primitive_steps if self.execution else 0

    @property
    def short_circuited(self) -> bool:
        """:163 — a newly raised InfrastructureFault aborts the current cycle."""
        return bool(self.faults)

    def canonical(self) -> Dict[str, Any]:
        return {
            "executive_step": self.executive_step,
            "task": self.task.canonical(),
            "pre_state": self.pre_state.world_key(),
            "post_state": self.post_state.world_key() if self.post_state else None,
            "model_version": str(self.model_version),
            "provenance": {"source": self.provenance.source},
            "symbolic_result": self.symbolic_result.canonical() if self.symbolic_result else None,
            "symbolic_proposal": self.symbolic_proposal.canonical() if self.symbolic_proposal else None,
            "nl_proposal": self.nl_proposal.canonical() if self.nl_proposal else None,
            "coverage": self.coverage.canonical() if self.coverage else None,
            "confidence": [c.canonical() for c in self.confidence],
            "decision": str(self.decision) if self.decision else None,
            "selected_call": self.selected_call.canonical() if self.selected_call else None,
            "validation": type(self.validation).__name__ if self.validation else None,
            "predicted_world_key": self.predicted_world_key,
            "predicted_symbolic_key": self.predicted_symbolic_key,
            "execution": self.execution.canonical() if self.execution else None,
            "discrepancies": [d.canonical() for d in self.discrepancies],
            "divergences": [d.canonical() for d in self.divergences],
            "faults": [f.canonical() for f in self.faults],
        }
