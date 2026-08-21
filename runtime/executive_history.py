"""Executive history: trace accumulation, budgets, and repeated-failure bookkeeping.

Owned by the executive loop manager (SUPERVISOR_P0_P4_CONTRACT.md:35, :254-255). P0 freezes the
shape; P4 drives it.

The repeated-failure key is `(pre-attempt StateSnapshot, grounded skill)` exactly as :118
requires, using `StateSnapshot.world_key()` (episode bookkeeping excluded) and
`GroundedSkillCall.key()`. :118 warns this must not become a hidden symbolic feasibility
predicate, which is why it lives here and not in `shared/`.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from shared.execution import ExecutionOutcome
from shared.faults import InfrastructureFault
from shared.skills import GroundedSkillCall
from shared.state_snapshot import StateSnapshot
from shared.trace_schema import TraceEntry


class ExecutiveHistory:
    """Ordered trace plus repeated-failure bookkeeping (:118)."""

    def __init__(self) -> None:
        self._entries: List[TraceEntry] = []
        self._failure_counts: Dict[Tuple[str, str], int] = {}

    # ── trace ──────────────────────────────────────────────────────────────────────
    def append(self, entry: TraceEntry) -> None:
        self._entries.append(entry)
        ex = entry.execution
        if ex is not None:
            # ONE attempt, ONE escalation channel (P4 decision, reconciled in the P4
            # consistency round): a fault-carrying executed entry — case (a), or a monitor
            # fault on a completed attempt — escalates through the FAULT channel and must not
            # also accrue repeated-failure counts. Faultless failures accrue here.
            if ex.outcome is not ExecutionOutcome.SUCCESS and not entry.faults:
                key = self.failure_key(entry.pre_state, ex.call)
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1

    @property
    def entries(self) -> Tuple[TraceEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    # ── budgets ────────────────────────────────────────────────────────────────────
    # LOWER BOUNDS, not totals: both sums read the RECORDED accounting, and a case-(c)
    # mid-execution fault (`shared/faults.py` three-case rule) consumed one executive step and
    # possibly many primitives that are recorded only in `fault.detail`. The P4 loop must charge
    # case-(c) attempts from fault provenance ON TOP of these sums — budgeting from these
    # accessors alone under-charges exactly the runaway/exception attempts a budget exists for.
    @property
    def executive_steps_used(self) -> int:
        return sum(e.executive_steps_consumed for e in self._entries)

    @property
    def primitive_steps_used(self) -> int:
        return sum(e.primitive_steps_consumed for e in self._entries)

    # ── repeated-failure bookkeeping ───────────────────────────────────────────────
    @staticmethod
    def failure_key(pre_state: StateSnapshot, call: GroundedSkillCall) -> Tuple[str, str]:
        return (pre_state.world_key(), call.key())

    def failure_count(self, pre_state: StateSnapshot, call: GroundedSkillCall) -> int:
        return self._failure_counts.get(self.failure_key(pre_state, call), 0)

    def faults_since(self, executive_step: int) -> Tuple[InfrastructureFault, ...]:
        """Faults raised at or after `executive_step`.

        :163 exposes *recent* fault history to the FOLLOWING cycle. Callers must pass the cycle
        boundary: this is the ONLY accessor cycle logic MAY use — the V1 loop currently
        escalates through `halt_on_infrastructure_fault` and does not consume it (:163 is
        permissive; recorded in the P4 review). `all_faults()` exists alongside it
        for traces and post-hoc analysis; driving a cycle from that would silently re-surface stale
        faults forever.
        """
        return tuple(f for e in self._entries if e.executive_step >= executive_step for f in e.faults)

    def all_faults(self) -> Tuple[InfrastructureFault, ...]:
        """Every fault in the whole episode. For traces and post-hoc analysis, not for cycle logic."""
        return tuple(f for e in self._entries for f in e.faults)
