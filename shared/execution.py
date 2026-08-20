"""Execution labels, typed execution outcomes, and step accounting.

P0_V1_DECISIONS Decision 3: the wrapper PRESERVES the raw backend label verbatim as provenance
and adds a separate AUTHORITATIVE typed outcome derived from world state. Timeout is represented
explicitly even when `raw_label == "pushed"`.

Why the raw label cannot be authoritative (docs/handoff/section18.md headline 0, verified):
`PushSkill` distinguishes `blocked` from `too_heavy` by reading the BELIEF label of the cell
beyond the box (skill_executor_push.py:218-221) where `_BLOCKING = ("wall", "agent")` (:36), but
the belief updater never writes "agent" — another agent's cell is deliberately recorded as
"empty" (deterministic_grid_updater.py:215-220) — while the backend DOES reject a light push
whose landing cell holds an agent (_cell_free_for_box, multi_agent_box_push_env.py:301-303).
A light box blocked by the partner is therefore ALWAYS labelled `too_heavy`.

BINDING RULE: `raw_label` is diagnostic/provenance only. It must never be consumed by the
monitor, the planner, or repeated-failure bookkeeping.

Decision 2 (step accounting): one validated grounded invocation that REACHES THE EXECUTOR
consumes exactly one executive step, success or failure. Calls rejected before executor
invocation consume zero. Primitive steps are counted separately, by the wrapper counting
`env.step()` invocations — never from `BaseSkill._steps`, which is not a primitive-step counter
(it skips early returns and evaluation iterations: skill_executor_push.py:170, :226).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, FrozenSet, Mapping, Optional

from shared.skills import GroundedSkillCall, SkillName
from shared.state_snapshot import StateSnapshot


class RawLabel(StrEnum):
    """Raw backend terminal labels that the existing code can actually produce.

    Authoritative source is CODE, not docstrings or prompts (section18.md §B).
    """
    # ExploreSkill — shared_skills.py:280, :282, :286
    FOUND_TARGET = "found_target"
    FOUND_DECOY = "found_decoy"
    EXPLORED = "explored"
    # GotoPushPoseSkill — skill_executor_push.py:146, :154, :168, :172
    IN_POSITION = "in_position"
    NONE_KNOWN = "none_known"
    BLOCKED = "blocked"
    # PushSkill — skill_executor_push.py:213, :215, :220, :221, :225, :228
    DELIVERED = "delivered"
    PUSHED = "pushed"
    TOO_HEAVY = "too_heavy"
    # CooperativePushSkill — skill_executor_push.py:294, :300, :308, :324, :330, :350
    WAITING_PARTNER = "waiting_partner"
    # WaitSkill — shared_skills.py:307
    DONE = "done"


#: NOT a RawLabel, deliberately. The runner substitutes this string when a skill is STILL RUNNING
#: at episode end (`box_push_centralized.py:468`: `sk.label or "in_progress"`). It denotes the
#: ABSENCE of a terminal label, so admitting it to `RawLabel` would let a non-terminal progress
#: state masquerade as a terminal backend outcome — and it belonged to none of the declared
#: buckets below, which is how it went unnoticed.
#:
#: Progress state and terminal execution labels are different concepts. An in-flight skill has no
#: `ExecutionResult` at all; `ExecutionResult` exists only for a COMPLETED executive attempt.
NON_TERMINAL_PROGRESS_MARKER: str = "in_progress"


#: Labels each skill can actually emit, read from code (section18.md §B).
PRODUCIBLE_RAW_LABELS: Mapping[SkillName, FrozenSet[RawLabel]] = {
    SkillName.EXPLORE: frozenset({RawLabel.FOUND_TARGET, RawLabel.FOUND_DECOY, RawLabel.EXPLORED}),
    SkillName.GOTO_PUSH_POSE: frozenset({RawLabel.IN_POSITION, RawLabel.NONE_KNOWN, RawLabel.BLOCKED}),
    SkillName.PUSH: frozenset({RawLabel.DELIVERED, RawLabel.PUSHED, RawLabel.BLOCKED, RawLabel.TOO_HEAVY}),
    SkillName.COOPERATIVE_PUSH: frozenset(
        {RawLabel.NONE_KNOWN, RawLabel.BLOCKED, RawLabel.DELIVERED, RawLabel.WAITING_PARTNER}
    ),
    SkillName.WAIT: frozenset({RawLabel.DONE}),
}

#: Resolved code-vs-doc vocabulary inconsistencies (P0 requirement).
#:
#: "moved" is advertised in docstrings and prompts (skill_executor_push.py:7;
#: box_push_centralized.py:53, :243, :288) but NO `_finish("moved")` exists in
#: CooperativePushSkill (:285-368). The documentation is wrong; the code is authoritative.
ADVERTISED_BUT_NOT_PRODUCIBLE: FrozenSet[str] = frozenset({"moved"})

#: `BaseSkill._timeout` sets label="timeout" (shared_skills.py:230-235) but every subclass
#: overwrites it before it escapes (skill_executor_push.py:172, :228, :330;
#: shared_skills.py:286). It is therefore never observable as a raw label — which is exactly
#: why Decision 3 requires an explicit typed TIMEOUT outcome.
NEVER_OBSERVABLE_RAW: FrozenSet[str] = frozenset({"timeout"})

#: Producible by shared code but unreachable in BoxPush: every box is a target
#: (box_push_env.py:104-106), so no decoy is ever placed.
UNREACHABLE_IN_BOXPUSH: FrozenSet[RawLabel] = frozenset({RawLabel.FOUND_DECOY})


class ExecutionOutcome(StrEnum):
    """Authoritative typed outcome, derived from world state — never from `raw_label`."""
    SUCCESS = "success"          # the skill's deterministic symbolic effect was realized
    PARTIAL = "partial"          # world changed, but the intended effect was not realized
    FAILURE = "failure"          # intended effect not realized
    TIMEOUT = "timeout"          # the backend budget was exhausted; explicit even if raw says "pushed"


class FailureStateClass(StrEnum):
    """The three contract failure classes (:110-114), describing a BACKEND ATTEMPT.

    TWO SENSES OF "REJECTED" — never conflate them:

      * **Pre-executor call rejection** — `shared.skills.CallValidation`
        (`MalformedCall` / `UngroundedCall` / `SymbolicallyInapplicable`). The call never reaches
        the executor, consumes ZERO executive steps, produces NO `ExecutionResult`, and leaves
        symbolic state untouched. Identify it with `CallValidation.is_pre_executor_rejection`.
      * **`BACKEND_REJECTED_BEFORE_TRANSITION`** (below) — the call DID reach the executor and
        consumed one executive step; the backend skill then declined before attempting any world
        transition (e.g. `none_known` on the first `step()`).

    The member below is named `BACKEND_` precisely so the two cannot be mistaken for one another
    at a call site. Its wire value keeps the supervisor's wording (:110-114).

    NOTE: the class is a function of (skill, label, WHEN in the attempt it fired), not of
    (skill, label) — see section18.md §C. It is therefore recorded per attempt at runtime,
    never looked up in a static table.
    """
    UNCHANGED = "unchanged"                                   # no-op
    PARTIAL_EXECUTION = "partial_execution"                   # changed state, then failed
    BACKEND_REJECTED_BEFORE_TRANSITION = "rejected_before_transition"  # no transition attempted


@dataclass(frozen=True, slots=True)
class StepAccounting:
    """Executive and primitive step costs of one attempt (Decision 2)."""
    executive_steps: int
    primitive_steps: int

    def __post_init__(self) -> None:
        if self.executive_steps not in (0, 1):
            raise ValueError("one attempt consumes 0 or 1 executive steps")
        if self.primitive_steps < 0:
            raise ValueError("primitive_steps must be non-negative")

    def canonical(self) -> Dict[str, Any]:
        return {"executive_steps": self.executive_steps, "primitive_steps": self.primitive_steps}


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """The executor's report for a call that REACHED the executor.

    A rejected call never produces an ExecutionResult — it produces a `CallValidation` rejection
    (shared.skills) and consumes zero executive steps.
    """
    call: GroundedSkillCall
    outcome: ExecutionOutcome
    pre_state: StateSnapshot
    post_state: StateSnapshot
    accounting: StepAccounting
    raw_label: Optional[RawLabel] = None          # provenance ONLY
    failure_class: Optional[FailureStateClass] = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.accounting.executive_steps != 1:
            raise ValueError(
                "an executed attempt consumes exactly one executive step (Decision 2); a "
                "PRE-EXECUTOR call rejection must not be represented as an ExecutionResult"
            )
        # The label must be one the GROUNDED SKILL can actually emit. Without this,
        # PRODUCIBLE_RAW_LABELS is a well-evidenced table that constrains nothing, and a
        # `Push` result carrying `waiting_partner` constructs silently.
        if self.raw_label is not None:
            # `RawLabel` is a StrEnum, so a bare "delivered" would satisfy the membership test
            # below by value alone. Every other typed field on the contract surface is isinstance-
            # checked; this one was not.
            if not isinstance(self.raw_label, RawLabel):
                raise TypeError(
                    f"raw_label must be a RawLabel, got {type(self.raw_label).__name__} "
                    f"({self.raw_label!r}) — a bare string bypasses the vocabulary contract"
                )
            producible = PRODUCIBLE_RAW_LABELS.get(self.call.skill, frozenset())
            if self.raw_label not in producible:
                raise ValueError(
                    f"{self.call.skill} cannot emit raw label {self.raw_label!r}; producible "
                    f"labels are {sorted(str(l) for l in producible)} (section18.md §B). A label "
                    f"from another skill indicates a mis-wired adapter, not a backend surprise."
                )
        if self.outcome is ExecutionOutcome.SUCCESS and self.failure_class is not None:
            raise ValueError("a successful outcome must not carry a failure class")
        if self.outcome is not ExecutionOutcome.SUCCESS and self.failure_class is None:
            raise ValueError("a non-successful outcome must record its failure state class")
        # The classification must match the observed states, not merely be declared. "Never assume
        # a failed skill is a no-op" is only enforceable if the claim is checked.
        changed = not self.pre_state.same_world(self.post_state)
        if self.failure_class is FailureStateClass.PARTIAL_EXECUTION and not changed:
            raise ValueError("PARTIAL_EXECUTION claimed but pre_state and post_state are identical")
        if self.failure_class in (
            FailureStateClass.UNCHANGED,
            FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION,
        ) and changed:
            raise ValueError(
                f"{self.failure_class} claimed but the world changed between pre_state and post_state"
            )

    @property
    def world_changed(self) -> bool:
        return not self.pre_state.same_world(self.post_state)

    def canonical(self) -> Dict[str, Any]:
        return {
            "call": self.call.canonical(),
            "outcome": str(self.outcome),
            "raw_label": str(self.raw_label) if self.raw_label is not None else None,
            "failure_class": str(self.failure_class) if self.failure_class is not None else None,
            "pre_state": self.pre_state.world_key(),
            "post_state": self.post_state.world_key(),
            "accounting": self.accounting.canonical(),
        }
