"""The policy-independent executor (:31, :251).

The whole guarantee is the SIGNATURE: the executor sees an environment and one grounded call —
never the policy, the history, the beliefs, the planner result, or the comparator output. There
is nothing here a policy could change, which is what "orchestration policy changes decisions,
not executor semantics" (.claude/rules/testing.md) means structurally. The pinning test runs
identical call sequences under both policies and asserts byte-identical execution records.

The executor gates NOTHING (decisions §19.1 item 2): deciding whether a call may run is the
orchestrator's job, on the typed `CallValidation`. What arrives here is executed.
"""
from __future__ import annotations

from typing import Union

from shared.backend_contract import V1Environment
from shared.execution import ExecutionResult
from shared.skills import GroundedSkillCall, MalformedCall, UngroundedCall


def execute(
    env: V1Environment, call: GroundedSkillCall
) -> Union[ExecutionResult, MalformedCall, UngroundedCall]:
    """One executive attempt against the authoritative backend.

    Returns the environment's typed result verbatim; `InfrastructureFaultError` propagates to
    the loop, which owns the three-case accounting (`shared/faults.py`).
    """
    return env.execute_skill(call)
