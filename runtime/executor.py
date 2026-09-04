"""The policy-independent executor (:31, :251).

The whole guarantee is the SIGNATURE: the executor sees an environment and one grounded call —
never the policy, the history, the beliefs, the planner result, or the comparator output. There
is nothing here a policy could change, which is what "orchestration policy changes decisions,
not executor semantics" (.claude/rules/testing.md) means structurally. The pinning test runs
identical call sequences under both policies and asserts byte-identical execution records.

The executor gates NOTHING (decisions §19.1 item 2): deciding whether a call may run is the
orchestrator's job, on the typed `CallValidation`. What arrives here is executed.

R6 (report Phase 6 item 2): the executor is the runtime's single backend boundary, so it is
where an environment's return value is checked against the typed contract. A value outside
`ExecutionResult | MalformedCall | UngroundedCall` is converted into the established
`MALFORMED_BACKEND_RESULT` infrastructure fault rather than reaching the loop as an object
whose attribute reads raise bare exceptions. The attempt DID reach the executor, so per
Decision 2 one executive step is consumed; the backend reported no typed accounting, so the
fault carries the case-(c) provenance key with the only honest primitive count — the lower
bound 0 — and says so.
"""
from __future__ import annotations

from typing import Union

from shared.backend_contract import V1Environment
from shared.execution import ExecutionResult
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError
from shared.skills import GroundedSkillCall, MalformedCall, UngroundedCall


def execute(
    env: V1Environment, call: GroundedSkillCall
) -> Union[ExecutionResult, MalformedCall, UngroundedCall]:
    """One executive attempt against the authoritative backend.

    Returns the environment's typed result verbatim; `InfrastructureFaultError` propagates to
    the loop, which owns the three-case accounting (`shared/faults.py`). A return value
    outside the typed contract is raised as `MALFORMED_BACKEND_RESULT` (R6).
    """
    result = env.execute_skill(call)
    if not isinstance(result, (ExecutionResult, MalformedCall, UngroundedCall)):
        raise InfrastructureFaultError(InfrastructureFault(
            kind=FaultKind.MALFORMED_BACKEND_RESULT,
            message=f"environment returned {type(result).__name__} instead of a typed "
                    f"ExecutionResult / MalformedCall / UngroundedCall",
            detail="primitive_steps_before_failure=0; the attempt reached the executor "
                   "(one executive step, Decision 2) but the backend reported no typed "
                   "accounting, so the primitive count is unknown and 0 is its lower bound",
            source="runtime/executor.py::execute",
        ))
    return result
