"""BoxPush V1 composition root (R4 — report Phase 4 items 1 and 3).

Two things live here, and only here:

1. `BoxPushDomainServices` — the BoxPush implementation of the `DomainServices` contract.
   It binds the frozen P0 domain (`domain.box_push_v1`: IR, projection, model version,
   task goal, zone) to the P2 symbolic machinery (`symbolic`: planner, applicability,
   predictor, monitor) exactly as the pre-R4 loop bound them inline, and it owns the
   grounding-before-applicability identity check (P4 decisions §19.1 item 5) that the loop
   used to perform over agents, boxes, and the task zone. Behavior is byte-for-byte the
   pre-R4 wiring; only the OWNER changed.

2. `compose` / `build_loop` — the explicit assembly of one V1 executive loop: the
   authoritative environment (constructed by the CALLER — this package never imports the
   backend), the domain services, a fresh `ExactSymbolicBelief` as the symbolic track, the
   `BoxPushActionComparator` over the domain equivalence rule, the deterministic V1
   recovery provider, and the policy. Every component is passed to `ExecutiveLoopManager`
   through its `shared.contracts` seam; overriding any one of them is a keyword argument
   here, never an edit to the loop (Phase 4 acceptance).

The universe (which identities exist) is derived from the authoritative snapshot the loop
passes with each plan request — the same `Universe.from_snapshot` the pre-R4 loop applied
to its first synced snapshot; identities never change within a BoxPush episode, so the
result is identical. That snapshot is read for identities ONLY — never for positions,
facing, walls, or any feasibility signal (Decision 6; pinned by the geometry-invariance
test in `tests/test_r4_composition.py`). An explicit `universe` override exists for the
synthetic single-agent NoPlan instance (Decision 12), replacing the pre-R4 direct
assignment of the loop's private universe field.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Type

from domain.box_push_v1 import (
    DOMAIN_IR,
    MODEL_VERSION,
    PROJECTION,
    BoxPushActionEquivalence,
    project,
)
from nl.recovery import propose_recovery
from runtime.loop import ExecutiveLoopManager
from shared.contracts import (
    DomainServices,
    OrchestrationPolicyContract,
    Prediction,
    ProposalComparator,
    RecoveryProvider,
    SymbolicTrack,
)
from shared.discrepancy import ExecutionDiscrepancy
from shared.execution import ExecutionResult
from shared.orchestration_config import OrchestrationConfig
from shared.planner_result import PlannerResult
from shared.skills import CallValidation, GroundedSkillCall, UngroundedCall
from shared.state_snapshot import StateSnapshot
from shared.symbolic_state import GroundedLiteral, SymbolicState
from shared.task import Task
from shared.versioning import ModelVersion, Provenance
from symbolic import ExactSymbolicBelief, Universe, evaluate, monitor_execution, plan
from symbolic.predictor import predict_symbolic, predict_world_candidates

from app.comparator import BoxPushActionComparator


class BoxPushDomainServices:
    """`DomainServices[StateSnapshot, SymbolicState, GroundedSkillCall]` for one task."""

    def __init__(self, task: Task, *, universe: Optional[Universe] = None) -> None:
        self.task = task
        self._goal = frozenset(
            GroundedLiteral("delivered", (str(b),)) for b in task.goal_delivered
        )
        self._universe = universe

    @property
    def model_version(self) -> ModelVersion:
        return MODEL_VERSION

    def _universe_for(self, snapshot: StateSnapshot) -> Universe:
        if self._universe is not None:
            return self._universe
        return Universe.from_snapshot(snapshot, self.task.zone)

    def plan(self, symbolic_state: SymbolicState, state: StateSnapshot, /) -> PlannerResult:
        return plan(
            DOMAIN_IR, symbolic_state, self._goal, self._universe_for(state), MODEL_VERSION
        )

    def ground(
        self, state: StateSnapshot, call: GroundedSkillCall, /
    ) -> Optional[UngroundedCall]:
        """§19.1 item 5: grounding-vs-universe BEFORE symbolic applicability. Identities are
        checked against the authoritative snapshot so a ghost call routes as the typed
        `UngroundedCall -> MISSING_GROUNDING` fault (Decision 7), never as a quiet symbolic
        verdict. Planner output is always grounded; this guards recovery/NL calls."""
        known_agents = {a.agent_id for a in state.agents}
        known_boxes = {b.box_id for b in state.boxes}
        for agent in call.agents:
            if agent not in known_agents:
                return UngroundedCall(reason=f"unknown agent {agent} in {call}", call=call)
        if call.box is not None and call.box not in known_boxes:
            return UngroundedCall(reason=f"unknown box {call.box} in {call}", call=call)
        if call.zone is not None and call.zone != self.task.zone:
            return UngroundedCall(
                reason=f"zone identity mismatch: {call.zone} is not the task zone in {call}",
                call=call,
            )
        return None

    def evaluate(
        self, symbolic_state: SymbolicState, call: GroundedSkillCall, /
    ) -> CallValidation:
        return evaluate(DOMAIN_IR, symbolic_state, call)

    def predict(
        self, symbolic_state: SymbolicState, state: StateSnapshot, call: GroundedSkillCall, /
    ) -> Prediction:
        """Decision 13.6 both-bases prediction, RECORDED for the monitor/trace."""
        predicted = predict_symbolic(DOMAIN_IR, symbolic_state, call)
        candidates = predict_world_candidates(state, call, self.task.zone)
        return Prediction(
            symbolic_key=PROJECTION.monitored_key(predicted) if predicted is not None else None,
            world_key=candidates[0].world_key() if candidates else None,
        )

    def monitor(
        self, pre_symbolic: SymbolicState, result: ExecutionResult, /
    ) -> Tuple[ExecutionDiscrepancy, ...]:
        """May raise the predictor's bare `ValueError` on a zone-identity wiring error; the
        loop owns converting that escape into the typed infrastructure fault."""
        return monitor_execution(
            DOMAIN_IR, PROJECTION, project, pre_symbolic, result,
            self.task.zone, MODEL_VERSION,
        )


@dataclass(frozen=True, slots=True)
class BoxPushComponents:
    """The injected component set for one loop, as `compose` assembles it."""
    domain: DomainServices
    symbolic_track: SymbolicTrack
    comparator: ProposalComparator
    recovery_provider: RecoveryProvider


def compose(task: Task) -> BoxPushComponents:
    """The default V1 components for `task`: domain services over the frozen model, a fresh
    exact belief, the action comparator over the domain equivalence rule with the
    documented default threshold, and the deterministic V1 recovery provider. A variant of
    any one component is passed to `build_loop` as an override, not configured here."""
    return BoxPushComponents(
        domain=BoxPushDomainServices(task),
        symbolic_track=ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project),
        comparator=BoxPushActionComparator(BoxPushActionEquivalence()),
        recovery_provider=propose_recovery,
    )


def build_loop(
    env,
    task: Task,
    config: Optional[OrchestrationConfig] = None,
    nl_track=None,
    provenance: Optional[Provenance] = None,
    policy: Optional[OrchestrationPolicyContract] = None,
    *,
    loop_class: Type[ExecutiveLoopManager] = ExecutiveLoopManager,
    domain: Optional[DomainServices] = None,
    symbolic_track: Optional[SymbolicTrack] = None,
    comparator: Optional[ProposalComparator] = None,
    recovery_provider: Optional[RecoveryProvider] = None,
) -> ExecutiveLoopManager:
    """Assemble one V1 executive loop over a caller-constructed environment.

    Positional parameters mirror the pre-R4 `ExecutiveLoopManager` signature so callers
    keep their argument order; each keyword overrides ONE composed component (an
    injected substitute needs no loop edit). `loop_class` admits the established test
    seam of subclassing the loop for fault injection.
    """
    defaults = compose(task)
    return loop_class(
        env, task, config, nl_track, provenance, policy,
        domain=domain if domain is not None else defaults.domain,
        symbolic_track=(
            symbolic_track if symbolic_track is not None else defaults.symbolic_track
        ),
        comparator=comparator if comparator is not None else defaults.comparator,
        recovery_provider=(
            recovery_provider if recovery_provider is not None
            else defaults.recovery_provider
        ),
    )


__all__ = [
    "BoxPushComponents",
    "BoxPushDomainServices",
    "build_loop",
    "compose",
]
