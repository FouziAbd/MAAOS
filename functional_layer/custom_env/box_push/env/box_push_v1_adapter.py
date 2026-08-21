"""P1 — the V1 environment adapter over the authoritative BoxPush backend.

Implements `shared.backend_contract.V1Environment` (structurally; this module deliberately does
not import the Protocol — the symbolic side depends on `shared`, never the reverse). The backend
is WRAPPED, not rewritten: every transition runs through `MultiAgentBoxPushEnv.step`, and every
composed skill is the existing backend implementation driven exactly the way
`box_push_centralized.py` drives it (skill.step per agent, then ONE joint env.step; a skill that
finishes still has its final STAY submitted).

Obligations implemented here, traceable to docs/decisions/P0_V1_DECISIONS.md:

  D1  `CooperativePush` is ONE executive call. The adapter owns BOTH per-agent
      `CooperativePushSkill` instances, latches the pair ordering, and does NOT latch the
      front/rear tandem roles — `_assign_slots` re-derives those every step().
  D2  `accounting.primitive_steps` counts actual `env.step()` calls made by this attempt —
      never `BaseSkill._steps`, which skips evaluation iterations. One validated call reaching
      the executor is exactly one executive step.
  D3  `raw_label` is PROVENANCE, preserved untouched from the backend skill. The typed
      `ExecutionOutcome` is derived from authoritative world state: Push/CooperativePush succeed
      iff the GROUNDED box's `delivered` flag flipped; GotoPushPose succeeds iff the agent stands
      on the grounded box's pose cell facing the push direction. The too_heavy-vs-blocked
      distinction is re-derived from `world` into `detail` (headline 0).
  D4  `export_full_state()` reads EXCLUSIVELY `core_env.world`. Never `core_env.grid`, never the
      belief layer, never observations.
  D7  Malformed and ungrounded calls are rejected BEFORE execution (zero executive steps) and are
      never re-grounded, substituted, or converted into Wait/Explore.
  D8  Execution before reset or after terminal/truncated raises `InfrastructureFaultError`.
  D14 Dispatch is EXHAUSTIVE over `SkillSignature.backend_dispatch_key` with NO fallback arm; an
      unknown token is a `MalformedCall`.
  D16 Argument translation is explicit and per-skill; `make_skill` is never called and no
      caller-supplied coordinate is ever passed through. Pre-flight resolves IDENTITY ONLY and
      never gates the attempt on feasibility. Post-flight verifies identity per skill and raises
      `EXECUTOR_MONITOR_PROTOCOL_FAILURE` (with the ExecutionResult attached) on substitution.

DECISION 16 OBLIGATION 4 — RESOLVED (recorded in P0_V1_DECISIONS.md §17): the entities/grid view
fed to the backend skills is the FULL EXACT GRID derived from `core_env.world` on every primitive
step: walls, `delivery_zone`, undelivered boxes as `target_object`, OTHER agents as `agent`; a
DELIVERED box's cell shows the underlying `delivery_zone` (delivered boxes are non-colliding
ghosts in the backend, so labelling them as boxes would wrongly block navigation). It is never
the reward-derived belief grid. Consequences, as recorded: `_resolve_box`'s belief-conditioned
fallback loses its trigger; `_bfs_avoid_boxes` navigates on exact occupancy INSIDE EXECUTION
(legal — Decision 6 governs applicability, not execution); the goto->blocked discrepancy rate
drops, and P2 must re-validate acceptance scenario #2 accordingly.

Distinct concepts kept distinct: exact world state (`export_full_state`), the rendered grid
(`core_env.grid` — never read for state), the belief layer (untouched, preserved for later
milestones), raw backend labels (provenance on the result), symbolic prediction (absent — P2).
No symbolic applicability, planning, or prediction happens here.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CUSTOM_ENV = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
_CST_ENV = os.path.join(_CUSTOM_ENV, "cooperative_search_transport", "env")
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_REPO_ROOT, _CUSTOM_ENV, _CST_ENV, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from constants import Actions, DIRECTION_VECTORS, Directions
from state import EnvConfig
from multi_agent_box_push_env import MultiAgentBoxPushEnv
from skill_executor_push import (
    CooperativePushSkill,
    GotoPushPoseSkill,
    PushSkill,
    _push_dir_toward_goal,
)
from shared_skills import ExploreSkill, WaitSkill

from domain.box_push_v1 import DELIVERY_ZONE
from shared.execution import (
    NON_TERMINAL_PROGRESS_MARKER,
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    RawLabel,
    StepAccounting,
)
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError
from shared.ids import AgentId, BoxId
from shared.skills import REGISTRY, GroundedSkillCall, MalformedCall, SkillName, UngroundedCall
from shared.state_snapshot import (
    AgentSnapshot,
    BoxSnapshot,
    EpisodeSnapshot,
    StateSnapshot,
    StaticWorld,
)

#: Absolute runaway backstop on env.step() calls per executive attempt. Every backend skill has
#: its own budget (<=150), so this is unreachable in practice; hitting it means a skill failed to
#: terminate, which is an executor protocol failure, not a domain outcome.
_HARD_CAP = 600


def _default_config() -> EnvConfig:
    """The frozen V1 instance configuration (matches the runner's, headless)."""
    return EnvConfig(
        width=12, height=12, num_agents=2, num_objects=2, num_target_objects=2,
        max_steps=600, agent_view_size=3, render_mode=None, seed=42,
    )


class BoxPushV1Adapter:
    """`V1Environment` over the authoritative BoxPush backend. See module docstring."""

    def __init__(self, config: Optional[EnvConfig] = None) -> None:
        self._config = config or _default_config()
        self._env = MultiAgentBoxPushEnv(config=self._config)
        #: Doubles as the reset-before-use latch: `world.agents` is a LIST until the first
        #: reset (multi_agent_box_push_env.py __init__ vs reset), so touching the backend before
        #: reset is undefined; every public method goes through `_require_reset`.
        self._obs: Optional[Dict[str, Any]] = None

    # ── V1Environment protocol ─────────────────────────────────────────────────────

    def reset(self, *, seed: Optional[int] = None) -> StateSnapshot:
        obs, _infos = self._env.reset(seed=seed)
        self._obs = obs
        return self.export_full_state()

    def observe(self) -> Mapping[str, Any]:
        """The public per-agent observation channel: the backend's own obs dicts, untouched.

        NOT the exact-state channel — obs comes from `core_env.grid` and carries that grid's
        known defects (a delivered box still renders TARGET_OBJECT; a traversed DeliveryTile is
        destroyed). The V1 symbolic track never reads this.
        """
        self._require_reset()
        return dict(self._obs)

    def export_full_state(self) -> StateSnapshot:
        """Canonical snapshot, built EXCLUSIVELY from `core_env.world` (D4)."""
        self._require_reset()
        world = self._env.core_env.world
        agents = tuple(
            AgentSnapshot(AgentId(aid), (int(a.position[0]), int(a.position[1])), int(a.direction))
            for aid, a in world.agents.items()
        )
        boxes = tuple(
            BoxSnapshot(
                BoxId(int(oid)), (int(o.position[0]), int(o.position[1])),
                int(o.required_agents), bool(o.is_target), bool(o.delivered),
            )
            for oid, o in world.objects.items()
        )
        static = StaticWorld(
            width=self._config.width,
            height=self._config.height,
            # The backend lists the four corner cells twice (box_push_env._build_base_grid);
            # canonical form dedupes and sorts, matching domain.box_push_v1._outer_walls.
            walls=tuple(sorted({(int(x), int(y)) for (x, y) in world.static.walls})),
            delivery_zone=tuple((int(x), int(y)) for (x, y) in world.static.delivery_zone),
        )
        episode = EpisodeSnapshot(
            step_count=int(world.episode.step_count),
            terminated=bool(world.episode.terminated),
            truncated=bool(world.episode.truncated),
        )
        return StateSnapshot(agents=agents, boxes=boxes, static=static, episode=episode)

    def is_terminal(self) -> bool:
        self._require_reset()
        episode = self._env.core_env.world.episode
        return bool(episode.terminated or episode.truncated)

    def render(self) -> Any:
        self._require_reset()
        return self._env.render()

    def close(self) -> None:
        self._env.close()

    def execute_skill(
        self, call: GroundedSkillCall
    ) -> ExecutionResult | MalformedCall | UngroundedCall:
        self._require_reset()
        if self.is_terminal():
            # D8 — refused as an InfrastructureFault; the fault channel is not in the return
            # union because a fault short-circuits the cycle rather than competing with results.
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message="refused: execution after a terminal episode (D8)",
                detail=f"terminated={self._env.core_env.world.episode.terminated} "
                       f"truncated={self._env.core_env.world.episode.truncated}",
                source="BoxPushV1Adapter.execute_skill",
            ))
        if not isinstance(call, GroundedSkillCall):
            return MalformedCall(
                reason=f"execute_skill requires a GroundedSkillCall, got {type(call).__name__}",
                raw=repr(call),
            )

        rejection = self._resolve_identities(call)
        if rejection is not None:
            return rejection            # zero executive steps; no env.step was made

        skills = self._construct_for_key(REGISTRY.get(call.skill).backend_dispatch_key, call)
        if skills is None:
            # Unreachable with the frozen registry, but the arm exists so there is NO fallback:
            # an unknown token is a MalformedCall, never a substituted default skill (D14).
            return MalformedCall(
                reason=f"no adapter construction for dispatch token "
                       f"{REGISTRY.get(call.skill).backend_dispatch_key!r}",
            )

        pre = self.export_full_state()
        primitive_steps, calls_made = self._drive(skills)
        post = self.export_full_state()
        result = self._interpret(call, pre, post, skills, primitive_steps, calls_made)
        self._post_flight(call, pre, post, result)
        return result

    # ── Pre-flight: identity resolution ONLY (Decision 16) ─────────────────────────

    def _resolve_identities(self, call: GroundedSkillCall) -> Optional[UngroundedCall]:
        """Resolve identities against authoritative `world`. NEVER a feasibility gate: no
        front-cell check, no occupancy, no reachability, no 'is the agent behind this box' test.
        An optimistic call must reach the backend and fail THERE (that failure is the designed
        V1 signal, reported as an ExecutionDiscrepancy upstream)."""
        world = self._env.core_env.world
        for agent in call.agents:
            if agent.value not in world.agents:
                return UngroundedCall(
                    reason=f"agent {agent.value!r} is not in the authoritative world", call=call
                )
        if call.box is not None and int(call.box.value) not in world.objects:
            return UngroundedCall(
                reason=f"box {str(call.box)!r} is not in the authoritative world", call=call
            )
        if call.zone is not None and call.zone != DELIVERY_ZONE:
            return UngroundedCall(
                reason=f"zone {call.zone.value!r} is not the frozen delivery zone "
                       f"{DELIVERY_ZONE.value!r}", call=call
            )
        return None

    # ── Dispatch: exhaustive, explicit, per-skill (D14 / D16) ──────────────────────

    def _construct_for_key(
        self, key: str, call: GroundedSkillCall
    ) -> Optional[Dict[str, Any]]:
        """Concrete backend skill construction per dispatch token. `make_skill` is never used:
        its single `arg` means three different things and silently falls back to
        nearest-target. Cells are derived HERE from the authoritative world, never taken from
        the caller."""
        agent_ids = [a.value for a in call.agents]
        if key == "goto_push_pose":
            return {agent_ids[0]: GotoPushPoseSkill(agent_ids[0], box=self._box_cell(call.box))}
        if key == "push":
            # dest=None is the explicit encoding of push-to-zone (Decision 11 / 16): PushSkill
            # finishes `delivered` exactly when the box's landing cell is a goal cell. The zone
            # was validated against the single frozen delivery zone in pre-flight.
            return {agent_ids[0]: PushSkill(agent_ids[0], dest=None)}
        if key == "cooperate_push":
            cell = self._box_cell(call.box)
            a0, a1 = agent_ids            # canonical pair ordering, latched here (D1)
            return {
                a0: CooperativePushSkill(a0, a1, box=cell),
                a1: CooperativePushSkill(a1, a0, box=cell),
            }
        if key == "explore":
            return {agent_ids[0]: ExploreSkill(agent_ids[0])}
        if key == "wait":
            return {agent_ids[0]: WaitSkill(agent_ids[0])}
        return None                      # no fallback arm — caller turns this into MalformedCall

    def _box_cell(self, box: BoxId) -> Tuple[int, int]:
        position = self._env.core_env.world.objects[int(box.value)].position
        return (int(position[0]), int(position[1]))

    # ── The drive loop (runner-faithful) ───────────────────────────────────────────

    def _drive(self, skills: Dict[str, Any]) -> Tuple[int, Dict[str, int]]:
        """Drive the backend skills exactly as the runner does: skill.step per agent (done
        skills and non-participants padded STAY), then ONE joint env.step. A skill finishing
        mid-iteration still has its terminal STAY submitted. Returns (env.step call count,
        skill.step call count per participant)."""
        env = self._env
        primitive_steps = 0
        calls_made = {aid: 0 for aid in skills}
        while True:
            if all(sk.is_done for sk in skills.values()):
                break
            episode = env.core_env.world.episode
            if episode.terminated or episode.truncated:
                break
            entities = {aid: self._entities_for(aid) for aid in env.agents}
            actions: Dict[str, int] = {}
            for aid in env.agents:
                sk = skills.get(aid)
                if sk is None or sk.is_done:
                    actions[aid] = int(Actions.STAY)
                elif isinstance(sk, CooperativePushSkill):
                    actions[aid] = sk.step(
                        self._obs[aid], entities[aid], entities.get(sk.partner_id, {})
                    )
                    calls_made[aid] += 1
                else:
                    actions[aid] = sk.step(self._obs[aid], entities[aid])
                    calls_made[aid] += 1
            try:
                self._obs, _rewards, terminations, truncations, _infos = env.step(actions)
            except Exception as error:
                # An exception out of the authoritative transition is an infrastructure fault
                # (:156 malformed backend result / backend exception), never a domain outcome.
                raise InfrastructureFaultError(InfrastructureFault(
                    kind=FaultKind.BACKEND_API_EXCEPTION,
                    message=f"env.step raised {type(error).__name__}: {error}",
                    detail=f"primitive_steps_before_failure={primitive_steps}",
                    source="BoxPushV1Adapter._drive",
                )) from error
            primitive_steps += 1
            if primitive_steps >= _HARD_CAP:
                raise InfrastructureFaultError(InfrastructureFault(
                    kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                    message=f"backend skill failed to terminate within {_HARD_CAP} env steps",
                    detail=f"primitive_steps_before_failure={primitive_steps}; the attempt's "
                           f"accounting is otherwise lost — P4 must resynchronize via "
                           f"export_full_state()",
                    source="BoxPushV1Adapter._drive",
                ))
            if all(terminations.values()) or all(truncations.values()):
                break
        return primitive_steps, calls_made

    # ── The exact entities view (Decision 16 obligation 4, RESOLVED) ───────────────

    def _entities_for(self, agent_id: str) -> Dict[str, Any]:
        """World-derived skill input. NEVER the belief grid. See the module docstring for the
        recorded consequences of the exact-grid resolution."""
        world = self._env.core_env.world
        width, height = self._config.width, self._config.height
        grid: List[List[str]] = [["empty"] * height for _ in range(width)]
        for (x, y) in world.static.delivery_zone:
            grid[int(x)][int(y)] = "delivery_zone"
        for (x, y) in world.static.walls:
            grid[int(x)][int(y)] = "wall"
        for obj in world.objects.values():
            if not obj.delivered:       # delivered boxes are non-colliding ghosts; their cell
                x, y = obj.position     # shows the underlying zone so navigation stays truthful
                grid[int(x)][int(y)] = "target_object"
        for other_id, other in world.agents.items():
            if other_id != agent_id:
                x, y = other.position
                grid[int(x)][int(y)] = "agent"
        me = world.agents[agent_id]
        return {
            "self": {"position": [int(me.position[0]), int(me.position[1])],
                     "direction": int(me.direction)},
            "grid": {"cells": grid},
        }

    # ── Authoritative interpretation (D3) ──────────────────────────────────────────

    def _interpret(
        self,
        call: GroundedSkillCall,
        pre: StateSnapshot,
        post: StateSnapshot,
        skills: Dict[str, Any],
        primitive_steps: int,
        calls_made: Dict[str, int],
    ) -> ExecutionResult:
        world_changed = not pre.same_world(post)
        timed_out = any(sk._steps >= sk._MAX_STEPS for sk in skills.values())
        finished_on_first_call = all(
            sk.is_done and calls_made[aid] == 1 for aid, sk in skills.items()
        )

        primary = skills[call.agents[0].value]
        try:
            raw_label = RawLabel(primary.label) if primary.label is not None else None
        except ValueError:
            # Unreachable with the frozen backend (every emitted label is enumerated), but a
            # label outside the vocabulary must surface as a TYPED fault, not a bare ValueError.
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.MALFORMED_BACKEND_RESULT,
                message=f"backend produced a label outside the frozen vocabulary: "
                        f"{primary.label!r}",
                # case (c) provenance: the attempt ran; the consumed primitives survive here
                detail=f"primitive_steps_before_failure={primitive_steps}",
                source="BoxPushV1Adapter._interpret",
            )) from None

        details = [
            "raw=" + ",".join(
                f"{aid}:{sk.label if sk.label is not None else NON_TERMINAL_PROGRESS_MARKER}"
                for aid, sk in skills.items()
            )
        ]
        if any(not sk.is_done for sk in skills.values()):
            details.append(f"attempt_state={NON_TERMINAL_PROGRESS_MARKER} (episode ended mid-skill)")
        if timed_out:
            details.append("timed_out=true (backend skill budget exhausted)")

        outcome = self._derive_outcome(
            call, pre, post, timed_out, world_changed, details, primitive_steps
        )

        failure_class: Optional[FailureStateClass] = None
        if outcome is not ExecutionOutcome.SUCCESS:
            if world_changed:
                failure_class = FailureStateClass.PARTIAL_EXECUTION
            elif finished_on_first_call:
                failure_class = FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION
            else:
                failure_class = FailureStateClass.UNCHANGED

        return ExecutionResult(
            call=call,
            outcome=outcome,
            pre_state=pre,
            post_state=post,
            accounting=StepAccounting(executive_steps=1, primitive_steps=primitive_steps),
            raw_label=raw_label,
            failure_class=failure_class,
            detail="; ".join(details),
        )

    def _derive_outcome(
        self,
        call: GroundedSkillCall,
        pre: StateSnapshot,
        post: StateSnapshot,
        timed_out: bool,
        world_changed: bool,
        details: List[str],
        primitive_steps: int,
    ) -> ExecutionOutcome:
        """The authoritative typed outcome, from world state — never from `raw_label`."""
        if call.skill is SkillName.WAIT:
            return ExecutionOutcome.SUCCESS

        if call.skill is SkillName.EXPLORE:
            # Explore has no symbolic contract (Decision 5/15) and 'discovery' has no world-state
            # counterpart under V1 full observability, so its outcome is operational: it either
            # ran to a found_* terminal within budget or exhausted the budget.
            return ExecutionOutcome.TIMEOUT if timed_out else ExecutionOutcome.SUCCESS

        if call.skill in (SkillName.PUSH, SkillName.COOPERATIVE_PUSH):
            box_pre = pre.box(call.box)
            box_post = post.box(call.box)
            if box_post.delivered and not box_pre.delivered:
                return ExecutionOutcome.SUCCESS
            if call.skill is SkillName.PUSH:
                details.append("authoritative_reason=" + self._push_failure_reason(call, post))
            if timed_out:
                return ExecutionOutcome.TIMEOUT
            return ExecutionOutcome.PARTIAL if world_changed else ExecutionOutcome.FAILURE

        if call.skill is SkillName.GOTO_PUSH_POSE:
            if self._at_pose_of(post, call.agents[0], call.box):
                return ExecutionOutcome.SUCCESS
            if timed_out:
                return ExecutionOutcome.TIMEOUT
            return ExecutionOutcome.PARTIAL if world_changed else ExecutionOutcome.FAILURE

        raise InfrastructureFaultError(InfrastructureFault(     # unreachable with frozen registry
            kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
            message=f"no outcome derivation for skill {call.skill}",
            detail=f"primitive_steps_before_failure={primitive_steps}",   # case (c) provenance
            source="BoxPushV1Adapter._derive_outcome",
        ))

    @staticmethod
    def _pose_cell(box_position: Tuple[int, int]) -> Tuple[Tuple[int, int], int]:
        """The backend's own pose geometry: `behind = B - D`, D from `_push_dir_toward_goal`.
        Execution-side interpretation, explicitly required by Decision 13 clause 5 — this is
        'what happened', never a feasibility query gating an attempt."""
        push_dir = _push_dir_toward_goal(list(box_position))
        dx, dy = DIRECTION_VECTORS[Directions(push_dir)]
        return (box_position[0] - dx, box_position[1] - dy), push_dir

    def _at_pose_of(self, state: StateSnapshot, agent: AgentId, box: BoxId) -> bool:
        box_snapshot = state.box(box)
        pose, push_dir = self._pose_cell(box_snapshot.position)
        agent_snapshot = state.agent(agent)
        return agent_snapshot.position == pose and agent_snapshot.direction == push_dir

    def _push_failure_reason(self, call: GroundedSkillCall, post: StateSnapshot) -> str:
        """Headline 0 (D3): re-derive too_heavy-vs-blocked from world, not from the label."""
        agent = post.agent(call.agents[0])
        dx, dy = DIRECTION_VECTORS[Directions(agent.direction)]
        front = (agent.position[0] + dx, agent.position[1] + dy)
        front_box = next(
            (b for b in post.boxes if not b.delivered and b.position == front), None
        )
        if front_box is None:
            return "no_pushable_box_in_front"
        identity = "" if front_box.box_id == call.box else (
            f"_front_box_is_{front_box.box_id}_not_grounded_{call.box}"
        )
        if front_box.required_agents > 1:
            return f"front_box_requires_{front_box.required_agents}_agents{identity}"
        landing = (front[0] + dx, front[1] + dy)
        if landing in post.static.walls:
            return f"landing_cell_is_wall{identity}"
        if any(a.position == landing for a in post.agents):
            return f"landing_cell_occupied_by_agent{identity}"
        if any(b.position == landing and not b.delivered for b in post.boxes):
            return f"landing_cell_occupied_by_box{identity}"
        return f"push_did_not_complete{identity}"

    # ── Post-flight: per-skill identity verification (Decision 16 obligation 3) ────

    def _post_flight(
        self,
        call: GroundedSkillCall,
        pre: StateSnapshot,
        post: StateSnapshot,
        result: ExecutionResult,
    ) -> None:
        """Substitution detection AFTER the attempt — post-hoc interpretation of what happened.

        `Push` deliberately has NO identity check: `PushSkill` takes no box argument and cannot
        re-ground, so a different box moving there is the designed non-exclusive-in_pose
        ExecutionDiscrepancy, never a fault (Decision 16). The `_resolve_box` skills are the
        ones that can substitute."""
        fault: Optional[InfrastructureFault] = None

        if call.skill is SkillName.COOPERATIVE_PUSH:
            moved = {
                b.box_id for b in post.boxes
                if b.position != pre.box(b.box_id).position
                or b.delivered != pre.box(b.box_id).delivered
            }
            if moved and call.box not in moved:
                fault = InfrastructureFault(
                    kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                    message=f"substitution: CooperativePush moved {sorted(map(str, moved))} "
                            f"while grounded {call.box} is untouched",
                    detail="the backend's _resolve_box fell back to another target",
                    source="BoxPushV1Adapter._post_flight",
                )

        elif call.skill is SkillName.GOTO_PUSH_POSE and result.raw_label is RawLabel.IN_POSITION:
            if not self._at_pose_of(post, call.agents[0], call.box):
                agent = post.agent(call.agents[0])
                for other in post.boxes:
                    if other.box_id == call.box or other.delivered:
                        continue
                    pose, _ = self._pose_cell(other.position)
                    if agent.position == pose:
                        fault = InfrastructureFault(
                            kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                            message=f"substitution: GotoPushPose claims in_position but the "
                                    f"agent stands at the pose cell of {other.box_id}, not of "
                                    f"grounded {call.box}",
                            detail="the backend's _resolve_box fell back to another target",
                            source="BoxPushV1Adapter._post_flight",
                        )
                        break

        if fault is not None:
            # The attempt DID reach the executor: one executive step is consumed and the result
            # travels with the fault (a post-execution fault legally coexists with an
            # ExecutionResult — EXECUTOR_MONITOR_PROTOCOL_FAILURE is not pre-execution).
            raise InfrastructureFaultError(fault, result=result)

    # ── Guards / diagnostics ───────────────────────────────────────────────────────

    def _require_reset(self) -> None:
        if self._obs is None:
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message="refused: reset() must be called before any other method — the "
                        "backend's world.agents changes type from list to dict during reset",
                source="BoxPushV1Adapter._require_reset",
            ))

    def world_grid_divergence(self) -> List[str]:
        """Diagnostic (item 5 of the P1 guard list): where `core_env.grid` disagrees with
        `world`. Nonempty output is EXPECTED after play (delivered boxes linger in the grid;
        traversed DeliveryTiles are destroyed) — that is exactly why nothing in this adapter
        reads the grid for state. Never used to gate anything."""
        self._require_reset()
        world = self._env.core_env.world
        grid = self._env.core_env.grid
        mismatches: List[str] = []
        for aid, agent in world.agents.items():
            cell = grid.get(int(agent.position[0]), int(agent.position[1]))
            if type(cell).__name__ != "AgentMarker":
                mismatches.append(f"{aid}: world at {tuple(agent.position)} but grid holds "
                                  f"{type(cell).__name__}")
        for oid, obj in world.objects.items():
            if obj.delivered:
                continue
            cell = grid.get(int(obj.position[0]), int(obj.position[1]))
            if type(cell).__name__ != "TargetPackage":
                mismatches.append(f"box_{oid}: world at {tuple(obj.position)} but grid holds "
                                  f"{type(cell).__name__}")
        return mismatches
