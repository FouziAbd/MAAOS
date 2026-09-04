"""Structural contracts for the domain-owned VALUE types the runtime handles (R5 — report
Phase 5): `RuntimeState`, `RuntimeCall`, `TaskContract`, `AdvisoryProposal`.

R6 moved the definitions to the leaf module `shared/value_contracts.py` (see its docstring
for the member table and the rationale): the protocols became the bounds of the generic
shared record types (`ExecutionResult`, `PlanFound`, `ExecutionDiscrepancy`, `TraceEntry`),
which this package imports, so they had to live below it. This module keeps the R5 import
path and the `shared.contracts` export; the classes are the same objects.
"""
from __future__ import annotations

from shared.value_contracts import AdvisoryProposal, RuntimeCall, RuntimeState, TaskContract

__all__ = ["AdvisoryProposal", "RuntimeCall", "RuntimeState", "TaskContract"]
