"""Typed `InfrastructureFault` — channel 3 of 3 (SUPERVISOR_P0_P4_CONTRACT.md:152-163).

Technical/interface/runtime faults.

:163 — a newly raised InfrastructureFault ABORTS the normal current cycle at the point of
detection. No further skill command is issued until synchronization as required. It is logged and
may appear as recent fault history on the FOLLOWING cycle; it is NOT a third competing
current-cycle reasoning proposal.

`short_circuits_cycle` is True by construction so the loop manager cannot accidentally treat a
fault as advisory. The current runner violates this: an LLM/API exception is caught and converted
into `explore`, which is then executed against the authoritative environment
(centralized_dspy_planner.py:106-108 → the `decided.get(aid, ("explore", None))` default in box_push_centralized.py::main).
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
    NL_TRACK_FAILURE = "nl_track_failure"


#: Faults that arise BEFORE the executor is ever invoked, so they short-circuit the cycle with no
#: execution having taken place. :163 says a new fault aborts the cycle "at the point of
#: detection" — for these kinds that point is upstream of the executor, which is what lets
#: `TraceEntry` refuse to represent a cycle that both faulted pre-execution and executed.
#: `NL_TRACK_FAILURE` belongs here because the advisory consultation precedes `execute()`:
#: an exception ESCAPING `nl_track.propose()` (LM/seam/DSPy raise, missing recorded fixture)
#: faults the cycle with the world untouched and zero steps consumed. It is infrastructure
#: provenance, never comparator evidence — typed malformed LM OUTPUT stays `NLProposal.malformed`
#: → COVERAGE_GAP through the comparator, the only `TrackDivergence` constructor (H8).
#:
#: The remaining kinds (malformed backend RESULT, serialization, backend API exception,
#: executor/monitor protocol) MAY be detected during or after an attempt, so they may legally
#: coexist with an `ExecutionResult`. NOTE the asymmetry: `arises_before_execution` is
#: KIND-based, and `EXECUTOR_MONITOR_PROTOCOL_FAILURE` is also legitimately raised for
#: pre-attempt caller-protocol refusals (post-terminal execution, reset-before-use — D8).
#: The discrimination rule for "what happened to the attempt?" is therefore NOT the kind, and it
#: is NOT a two-case rule either — an earlier revision froze `result is not None` as the whole
#: answer and thereby erased the mid-execution fault class. Three cases:
#:
#:   (a) `InfrastructureFaultError.result is not None` — the attempt ran to completion and THEN
#:       faulted (e.g. post-flight substitution). One executive step; full accounting attached.
#:   (b) `result is None` and the fault is a PRE-ATTEMPT refusal (D8 post-terminal,
#:       reset-before-use) — zero executive steps, world untouched.
#:   (c) `result is None` and the fault fired MID-EXECUTION (`env.step` raised, the runaway cap,
#:       a label outside the vocabulary): the attempt reached the executor, so per Decision 2 it
#:       consumed ONE executive step, the world may already have changed, and the primitive
#:       accounting survives only in `fault.detail`. P4 must resynchronize via
#:       `export_full_state()` — never assume a faulted attempt was a no-op.
#:
#: Only the implication `result is not None ⇒ one executive step` is a safe inference. Cases (b)
#: and (c) share `result=None` and are distinguished by PROVENANCE: refusal faults are raised
#: before any skill is constructed and their messages begin with `"refused:"`; mid-execution
#: faults carry `primitive_steps_before_failure=N` in `detail` — ONE exact key, attached by every
#: case-(c) producer (the adapter's `env.step` wrap, runaway cap, alien-label guard and dispatch
#: guard). An earlier revision let the runaway cap use a second spelling that collided with the
#: `TraceEntry.primitive_steps_consumed` accessor name while meaning something different.
PRE_EXECUTION_FAULT_KINDS: frozenset = frozenset({
    FaultKind.MALFORMED_SKILL_CALL,
    FaultKind.MISSING_GROUNDING,
    FaultKind.PLANNER_COMPUTATION_FAILURE,
    FaultKind.NL_TRACK_FAILURE,
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


class InfrastructureFaultError(Exception):
    """Carries an `InfrastructureFault` ACROSS a call boundary as an exception.

    Why this exists (P1, Decision 8 / Decision 16): `V1Environment.execute_skill` returns
    `ExecutionResult | MalformedCall | UngroundedCall` — the fault channel is deliberately not in
    that union, because a fault SHORT-CIRCUITS the cycle (:163) rather than being one more result
    to weigh. Exception semantics match that exactly: post-terminal refusal (D8), a post-flight
    identity violation (Decision 16 obligation 3), or a non-terminating skill raise this, and the
    executive loop converts `.fault` into the cycle's fault record.

    `result` is optional and its absence is NOT proof that nothing happened — see the three-case
    rule on `PRE_EXECUTION_FAULT_KINDS` above: a post-execution fault attaches the consumed
    attempt's `ExecutionResult` (and `TraceEntry` legally records both, since
    `EXECUTOR_MONITOR_PROTOCOL_FAILURE` is not pre-execution); a pre-attempt refusal (D8) carries
    `result=None` with the world untouched; a MID-EXECUTION fault also carries `result=None` while
    one executive step was consumed and the world may have changed (accounting in `detail` only).
    """

    def __init__(self, fault: InfrastructureFault, result: Optional[Any] = None):
        super().__init__(f"{fault.kind}: {fault.message}")
        self.fault = fault
        self.result = result
