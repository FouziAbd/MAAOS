"""Typed `InfrastructureFault` — channel 3 of 3 (SUPERVISOR_P0_P4_CONTRACT.md:152-163).

Technical/interface/runtime faults.

:163 — a newly raised InfrastructureFault ABORTS the normal current cycle at the point of
detection. No further skill command is issued until synchronization as required. It is logged and
may appear as recent fault history on the FOLLOWING cycle; it is NOT a third competing
current-cycle reasoning proposal.

`short_circuits_cycle` is True by construction so the loop manager cannot accidentally treat a
fault as advisory. The current runner violates this: an LLM/API exception is caught and converted
into `explore`, which is then executed against the authoritative environment
(centralized_dspy_planner.py:106-108 → box_push_centralized.py:404).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional


class FaultKind(StrEnum):
    MALFORMED_BACKEND_RESULT = "malformed_backend_result"
    SERIALIZATION_FAILURE = "serialization_failure"
    BACKEND_API_EXCEPTION = "backend_api_exception"
    MISSING_GROUNDING = "missing_grounding"
    EXECUTOR_MONITOR_PROTOCOL_FAILURE = "executor_monitor_protocol_failure"
    PLANNER_COMPUTATION_FAILURE = "planner_computation_failure"
    MALFORMED_SKILL_CALL = "malformed_skill_call"


#: Faults that arise BEFORE the executor is ever invoked, so they short-circuit the cycle with no
#: execution having taken place. :163 says a new fault aborts the cycle "at the point of
#: detection" — for these three that point is upstream of the executor, which is what lets
#: `TraceEntry` refuse to represent a cycle that both faulted pre-execution and executed.
#:
#: The remaining kinds (malformed backend RESULT, serialization, backend API exception,
#: executor/monitor protocol) can only be detected during or after an attempt, so they may legally
#: coexist with an `ExecutionResult`.
PRE_EXECUTION_FAULT_KINDS: frozenset = frozenset({
    FaultKind.MALFORMED_SKILL_CALL,
    FaultKind.MISSING_GROUNDING,
    FaultKind.PLANNER_COMPUTATION_FAILURE,
})


@dataclass(frozen=True, slots=True)
class InfrastructureFault:
    kind: FaultKind
    message: str
    detail: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("InfrastructureFault requires a message")

    @property
    def short_circuits_cycle(self) -> bool:
        """Always True — :163 admits no exceptions."""
        return True

    @property
    def arises_before_execution(self) -> bool:
        """True when the fault is detected upstream of the executor, so no attempt occurred."""
        return self.kind in PRE_EXECUTION_FAULT_KINDS

    def canonical(self) -> Dict[str, Any]:
        return {
            "channel": "InfrastructureFault",
            "kind": str(self.kind),
            "message": self.message,
            "detail": self.detail,
            "source": self.source,
        }
