"""Orchestration configuration (SUPERVISOR_P0_P4_CONTRACT.md:71, :180).

The orchestrator combines the two reasoning tracks under a CONFIGURED policy (:29) and does not
directly call the environment or advance time (:31). The executive loop manager owns the runtime
cycle and the budgets (:35).

Frozen here at P0 so P4 configures rather than invents.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict


class OrchestrationPolicy(StrEnum):
    SYMBOLIC_PRIMARY = "symbolic_primary"          # :248
    ADVISORY_TWO_TRACK = "advisory_two_track"      # :249


class ExecutiveDecision(StrEnum):
    """Executive consequences the orchestrator may choose (:29)."""
    EXECUTE = "execute"
    CONTINUE = "continue"
    INTERRUPT = "interrupt"
    REPLAN = "replan"
    REQUEST_PROPOSAL = "request_proposal"
    ASK_USER = "ask_user"
    UPDATE_TASK = "update_task"
    HALT = "halt"


@dataclass(frozen=True, slots=True)
class OrchestrationConfig:
    """V1 orchestration/budget configuration.

    `executive_step_budget` is the primary episode bound (Decision 2). A primitive budget alone
    provably cannot bound the loop: a `wait`/`wait` cycle performs zero `env.step()` calls, so
    `step_count` never advances and truncation never fires
    (box_push_centralized.py:423-424 vs multi_agent_box_push_env.py:141, :170).

    `max_rejections_per_cycle` is the loop-manager guard required by Decision 2: pre-executor
    rejections are free, so a policy that repeatedly proposes inapplicable calls would otherwise
    never be charged. It is an INFRASTRUCTURE guard on the loop, never a symbolic feasibility
    predicate (:118).
    """
    policy: OrchestrationPolicy = OrchestrationPolicy.SYMBOLIC_PRIMARY
    executive_step_budget: int = 50
    primitive_step_budget: int = 600          # matches the current runner (box_push_centralized.py:328)
    max_rejections_per_cycle: int = 5
    repeated_failure_threshold: int = 3       # per (pre-state world key, grounded call) — :118
    halt_on_infrastructure_fault: bool = True  # :163

    def __post_init__(self) -> None:
        if self.executive_step_budget <= 0:
            raise ValueError("executive_step_budget must be positive")
        if self.primitive_step_budget <= 0:
            raise ValueError("primitive_step_budget must be positive")
        if self.max_rejections_per_cycle <= 0:
            raise ValueError("max_rejections_per_cycle must be positive")
        if self.repeated_failure_threshold <= 0:
            raise ValueError("repeated_failure_threshold must be positive")

    def canonical(self) -> Dict[str, Any]:
        return {
            "policy": str(self.policy),
            "executive_step_budget": self.executive_step_budget,
            "primitive_step_budget": self.primitive_step_budget,
            "max_rejections_per_cycle": self.max_rejections_per_cycle,
            "repeated_failure_threshold": self.repeated_failure_threshold,
            "halt_on_infrastructure_fault": self.halt_on_infrastructure_fault,
        }
