"""BoxPush V1 — the P0 domain freeze.

Every constant here is transcribed from the authoritative backend and cited. Nothing is invented.

Instance (fixed and fully deterministic — nothing is randomized; the `seed` argument is
observationally inert because no BoxPush code consumes `np_random`):
  - 12x12 grid, outer wall only, no internal dividers   — box_push_env.py:84-101
  - goal zone = column x=1, rows y=1..10 (10 cells)      — box_push_env.py:39
  - box_0 HEAVY (required_agents=2) at (6,6)             — box_push_env.py:80
  - box_1 LIGHT (required_agents=1) at (8,4)             — box_push_env.py:81
  - agent_0 at (10,10), agent_1 at (10,9), both LEFT     — multi_agent_box_push_env.py:90-91, :107-113

Symbolic model — INTENTIONALLY OPTIMISTIC (P0_V1_DECISIONS Decision 6, supervisor :51-:59):
  - `in_pose` is NON-EXCLUSIVE: GotoPushPose adds it and deletes nothing, so one agent can be in
    pose for two boxes at once. The backend gives an agent one cell. Kept deliberately.
  - `in_pose` has NO GEOMETRY: the backend navigates to the single cell B-D
    (skill_executor_push.py:150), so two agents sent to the same box target the same cell.
  - GotoPushPose has NO REACHABILITY MODEL: its only preconditions are discovered+pending, while
    the backend can return `blocked` (skill_executor_push.py:161-168).
  These produce ExecutionDiscrepancy at execution time. That is the designed V1 signal. Never add
  reachability, occupancy, BFS, collision or backend feasibility checks to PRECONDITIONS to make a
  plan executable.

  The prohibition is on applicability/planning, not on effects (Decision 13). Each skill declares
  `predicted_world_effects`: the deterministic world positions its own success semantics imply.
  Those are arithmetic (`push_dir` is a Manhattan-nearest-goal-cell choice, no search), and P2 may
  ground them for the monitor's world basis. Predicting where success puts an agent is a different
  act from deciding whether the agent can get there.

Full observability (Decision 5): every box is `discovered` from initialization, so `Explore` is
not in the symbolic action set. It remains in the executive registry as a backend/NL-track skill.

The `zone` parameter appears in every push-related signature so the call-facing, IR, planner and
backend-wrapper forms are identical (Decision 11). V1 freezes exactly one zone, so no V1 predicate
is parameterized by it — the parameter carries identity, not extra semantics.
"""
from __future__ import annotations

from typing import Tuple

from shared.ids import AgentId, BoxId, Cell, ZoneId
from shared.skill_ir import (
    TYPE_AGENT,
    TYPE_BOX,
    TYPE_ZONE,
    DomainIR,
    Effect,
    Predicate,
    PredicateDecl,
    SkillIR,
)
from shared.skills import REGISTRY, SkillName
from shared.state_snapshot import (
    AgentSnapshot,
    BoxSnapshot,
    EpisodeSnapshot,
    StateSnapshot,
    StaticWorld,
)
from shared.symbolic_state import GroundedLiteral, ProjectionContract, SymbolicState
from shared.task import Task
from shared.versioning import ModelVersion, Provenance

# ── Frozen instance constants ──────────────────────────────────────────────────────

GRID_WIDTH = 12
GRID_HEIGHT = 12

#: box_push_env.py:39 — GOAL_ZONE = [(1, y) for y in range(1, 11)]
GOAL_ZONE: Tuple[Cell, ...] = tuple((1, y) for y in range(1, 11))

DELIVERY_ZONE = ZoneId("delivery_zone")

AGENT_0 = AgentId("agent_0")
AGENT_1 = AgentId("agent_1")
AGENTS: Tuple[AgentId, ...] = (AGENT_0, AGENT_1)

BOX_HEAVY = BoxId(0)     # required_agents=2 — box_push_env.py:80
BOX_LIGHT = BoxId(1)     # required_agents=1 — box_push_env.py:81

#: constants.py:31-36 — RIGHT(0)=(+1,0) DOWN(1)=(0,+1) LEFT(2)=(-1,0) UP(3)=(0,-1)
DIR_RIGHT, DIR_DOWN, DIR_LEFT, DIR_UP = 0, 1, 2, 3

MODEL_VERSION = ModelVersion(revision=0, label="boxpush-v1")

_PROVENANCE = Provenance(
    source="pddl/box_push_domain.pddl + docs/decisions/P0_V1_DECISIONS.md",
    model_version=MODEL_VERSION,
    note="Skill-level classical abstraction; no grid, no coordinates. Intentionally optimistic.",
)


def _outer_walls() -> Tuple[Cell, ...]:
    """box_push_env.py:88-92 — outer border only; corners are listed twice there, deduped here."""
    walls = set()
    for x in range(GRID_WIDTH):
        walls.add((x, 0))
        walls.add((x, GRID_HEIGHT - 1))
    for y in range(GRID_HEIGHT):
        walls.add((0, y))
        walls.add((GRID_WIDTH - 1, y))
    return tuple(sorted(walls))


STATIC_WORLD = StaticWorld(
    width=GRID_WIDTH,
    height=GRID_HEIGHT,
    walls=_outer_walls(),
    delivery_zone=GOAL_ZONE,
)


def initial_state() -> StateSnapshot:
    """The frozen V1 initial canonical state.

    Built from the backend's *initial* world values, exactly as a P1 wrapper will build it from
    the live `core_env.world` (Decision 4). No belief, no grid, no observations.
    """
    return StateSnapshot(
        agents=(
            AgentSnapshot(AGENT_0, (10, 10), DIR_LEFT),
            AgentSnapshot(AGENT_1, (10, 9), DIR_LEFT),
        ),
        boxes=(
            BoxSnapshot(BOX_HEAVY, (6, 6), required_agents=2, is_target=True, delivered=False),
            BoxSnapshot(BOX_LIGHT, (8, 4), required_agents=1, is_target=True, delivered=False),
        ),
        static=STATIC_WORLD,
        episode=EpisodeSnapshot(),
    )


# ── Predicates ─────────────────────────────────────────────────────────────────────

P_DISCOVERED = "discovered"
P_DELIVERED = "delivered"
P_PENDING = "pending"
P_LIGHT = "light"
P_HEAVY = "heavy"
P_IN_POSE = "in_pose"
P_DIFFERENT = "different"

PREDICATES: Tuple[PredicateDecl, ...] = (
    PredicateDecl(P_DISCOVERED, ("box",), fluent=True,
                  description="Box location is known. True for all boxes at t=0 in V1 (Decision 5)."),
    PredicateDecl(P_DELIVERED, ("box",), fluent=True,
                  description="Box is on the delivery zone. The V1 goal predicate."),
    PredicateDecl(P_PENDING, ("box",), fluent=True,
                  description="Complement of delivered, kept positive so the domain stays STRIPS."),
    PredicateDecl(P_LIGHT, ("box",), fluent=False,
                  description="required_agents == 1. Static prior knowledge."),
    PredicateDecl(P_HEAVY, ("box",), fluent=False,
                  description="required_agents >= 2. Static prior knowledge."),
    PredicateDecl(P_IN_POSE, ("agent", "box"), fluent=True,
                  description="Agent is positioned to push the box. NON-EXCLUSIVE by design."),
    PredicateDecl(P_DIFFERENT, ("agent", "agent"), fluent=False,
                  description="Distinct-agent pairs; equality substitute for CooperativePush."),
)


# ── Skill IR ───────────────────────────────────────────────────────────────────────

_GOTO_PUSH_POSE = SkillIR(
    signature=REGISTRY.get(SkillName.GOTO_PUSH_POSE),
    parameters=("agent", "box", "zone"),
    parameter_types=(TYPE_AGENT, TYPE_BOX, TYPE_ZONE),
    preconditions=(
        Predicate(P_DISCOVERED, ("box",)),
        Predicate(P_PENDING, ("box",)),
    ),
    effects=(
        # No delete effect: in_pose is intentionally non-exclusive (Decision 6).
        Effect(Predicate(P_IN_POSE, ("agent", "box")), positive=True),
    ),
    provenance=_PROVENANCE,
    observations=("agent reaches the push pose or reports a backend failure",),
    outcome_label="in_pose",
    # Decision 13.2/13.3. Pure arithmetic on the box position and the zone — no walls, no
    # occupancy, no BFS. `_push_dir_toward_goal` (skill_executor_push.py:39-47) picks the nearest
    # goal cell by Manhattan distance and then an axis; `behind = box - D` (:150) is the pose cell
    # and the success branch additionally requires `direction == D` (:152-154).
    predicted_world_effects=(
        "agent.position_post == box.position_pre - direction_vector(push_dir(box, zone))",
        "agent.direction_post == push_dir(box, zone)",
    ),
)

_PUSH = SkillIR(
    signature=REGISTRY.get(SkillName.PUSH),
    parameters=("agent", "box", "zone"),
    parameter_types=(TYPE_AGENT, TYPE_BOX, TYPE_ZONE),
    preconditions=(
        Predicate(P_IN_POSE, ("agent", "box")),
        Predicate(P_LIGHT, ("box",)),
        Predicate(P_PENDING, ("box",)),
    ),
    effects=(
        Effect(Predicate(P_DELIVERED, ("box",)), positive=True),
        Effect(Predicate(P_PENDING, ("box",)), positive=False),
        Effect(Predicate(P_IN_POSE, ("agent", "box")), positive=False),
    ),
    provenance=_PROVENANCE,
    observations=("box reaches the delivery zone, or a backend failure label",),
    outcome_label="delivered",
    # Transcribed, not inferred, and stated for the TERMINAL state of the executive macro.
    #
    # Direction: `PushSkill` derives its push vector from the AGENT'S CURRENT FACING
    # (`skill_executor_push.py`, `PushSkill.step`: `d = self_e["direction"]`), never from
    # `_push_dir_toward_goal`; the env agrees (`multi_agent_box_push_env._resolve_pushes`). The two
    # coincide only because the frozen zone is column x=1, so `push_dir` is always LEFT — a P2
    # predictor keyed on `push_dir` would be wrong the first time the instance changes. The agent
    # only ever issues MOVE_FORWARD or STAY, so its direction is unchanged (implicit frame).
    #
    # Position: `PushSkill` is a LOOP, not a single push. Each iteration sets
    # `_expect_pos = pos + D` and `_land = pos + 2D`, and finishes `delivered` when `_land` is a
    # goal cell. At that terminal iteration the agent stands on `_expect_pos` and the box on
    # `_land`, hence `agent_post == box_post - D` — one cell behind the box, wherever the loop
    # ended. An earlier revision said `box.position_pre`, which is only true of a single-cell push:
    # on the frozen instance the box travels (8,4)->(1,4) while the agent ends at (2,4), not (8,4).
    # `docs/handoff/section18.md` §I records the correct pair.
    #
    # All of this is arithmetic along the push ray. Whether the ray is CLEAR is feasibility and
    # stays out of the model — that is what makes `blocked`/`too_heavy` a discrepancy, not a bug.
    predicted_world_effects=(
        "D == direction_vector(agent.direction_pre)",
        "box.position_post == first_zone_cell_along(box.position_pre, D)",
        "box.delivered_post is True",
        "agent.position_post == box.position_post - D",
    ),
)

_COOPERATIVE_PUSH = SkillIR(
    signature=REGISTRY.get(SkillName.COOPERATIVE_PUSH),
    parameters=("agent1", "agent2", "box", "zone"),
    parameter_types=(TYPE_AGENT, TYPE_AGENT, TYPE_BOX, TYPE_ZONE),
    preconditions=(
        Predicate(P_DIFFERENT, ("agent1", "agent2")),
        Predicate(P_HEAVY, ("box",)),
        Predicate(P_IN_POSE, ("agent1", "box")),
        Predicate(P_IN_POSE, ("agent2", "box")),
        Predicate(P_PENDING, ("box",)),
    ),
    effects=(
        Effect(Predicate(P_DELIVERED, ("box",)), positive=True),
        Effect(Predicate(P_PENDING, ("box",)), positive=False),
        Effect(Predicate(P_IN_POSE, ("agent1", "box")), positive=False),
        Effect(Predicate(P_IN_POSE, ("agent2", "box")), positive=False),
    ),
    provenance=_PROVENANCE,
    observations=("box reaches the delivery zone, or a backend failure label",),
    outcome_label="delivered",
    # Direction: UNLIKE `Push`, the cooperative skill does NOT read the agents' facing. It
    # computes `push_dir = _push_dir_toward_goal(box)` from the BOX and the goal zone
    # (`skill_executor_push.py`, `CooperativePushSkill.step`) and then TURNS both agents onto it
    # via `_dir_to_action(d, push_dir)`, issuing the joint move only once both face it
    # (`multi_agent_box_push_env._find_tandem` requires the same `d` for both). So both terminal
    # directions ARE the push direction, and because a turn is a real world change those effects
    # must be declared — implicit frame conditions would otherwise predict unchanged facing and
    # mismatch on every successful cooperative push that required a turn.
    #
    # Position: the two agents occupy DISTINCT cells — A1 at B-D (front, against the box) and A2 at
    # B-2D (rear), per `_assign_slots` and per `_find_tandem`
    # (`multi_agent_box_push_env.py:312-328`), which accepts only that formation.
    # `_resolve_pushes` (`multi_agent_box_push_env.py:193-209`) translates box and both agents by +D, so the formation is preserved and the
    # terminal state is `box_post - D` / `box_post - 2D`.
    #
    # Stated as a SET, deliberately, for a reason stronger than non-derivability: `_assign_slots`
    # is re-evaluated on EVERY `step()`, from live Manhattan proximity with an `agent_id`
    # tie-break, so which agent holds the front slot can flip mid-skill. Even a predictor that
    # reads agent positions (which Decision 13 clause 9 permits) cannot fix the roles from the
    # pre-state. The call's pair is canonically ordered by AgentId, which is a third, unrelated
    # order. A per-parameter positional claim would therefore hand a P2 predictor a state the
    # backend can never produce; the set form is invariant under every one of those orderings.
    predicted_world_effects=(
        "D == direction_vector(push_dir(box, zone))",
        "box.position_post == first_zone_cell_along(box.position_pre, D)",
        "box.delivered_post is True",
        "agent1.direction_post == push_dir(box, zone)",
        "agent2.direction_post == push_dir(box, zone)",
        "{agent1.position_post, agent2.position_post} == "
        "{box.position_post - D, box.position_post - 2*D}",
    ),
)

DOMAIN_IR = DomainIR(
    name="box-push-skills-v1",
    model_version=MODEL_VERSION,
    predicates=PREDICATES,
    skills=(_GOTO_PUSH_POSE, _PUSH, _COOPERATIVE_PUSH),
    provenance=_PROVENANCE,
)


# ── Representative task examples (:184, section18.md §H) ───────────────────────────

TASK_DELIVER_BOTH = Task(
    task_id="deliver_both",
    description="Push both target boxes onto the goal zone.",
    goal_delivered=(BOX_HEAVY, BOX_LIGHT),
    zone=DELIVERY_ZONE,
)

TASK_DELIVER_LIGHT = Task(
    task_id="deliver_light",
    description="Push the light box onto the goal zone.",
    goal_delivered=(BOX_LIGHT,),
    zone=DELIVERY_ZONE,
)

TASK_DELIVER_HEAVY = Task(
    task_id="deliver_heavy",
    description="Push the heavy box onto the goal zone. It needs both agents.",
    goal_delivered=(BOX_HEAVY,),
    zone=DELIVERY_ZONE,
)

TASKS: Tuple[Task, ...] = (TASK_DELIVER_BOTH, TASK_DELIVER_LIGHT, TASK_DELIVER_HEAVY)


# ── Symbolic projection (the monitor's comparison basis) ──────────────────────────

#: `in_pose` is the ONLY predicate that cannot be read from a StateSnapshot by inspection — its
#: truth would have to be DERIVED from the pose cell `B - D`. It is therefore executive-tracked and
#: excluded from the monitored SYMBOLIC subset; `PROJECTION.apply_outcome` maintains it from typed
#: execution outcomes (Decision 13.8). Exclusion here does not make GotoPushPose unmonitored: its
#: `predicted_world_effects` remain available to the monitor's world basis (Decision 13.3).
#:
#: ACTUAL V1 MONITOR COVERAGE (P0_V1_DECISIONS §14.1), stated plainly rather than implied:
#:   - `delivered`/`pending` are the only monitored literals that VARY. `light`/`heavy`/`different`
#:     are non-fluent and `discovered` is emitted unconditionally, so the symbolic basis carries
#:     one bit per box and is discriminative for Push and CooperativePush ONLY.
#:   - GotoPushPose has NO symbolic discriminative power: its sole effect `in_pose` is excluded, so
#:     success and failure project identically. Its failure is detected through the authoritative
#:     typed ExecutionOutcome — always — and additionally through the predicted pose position once
#:     P2 implements the world-effect predictor.
#:   - A Push that moved the box three cells and then failed also projects identically to a no-op.
#:     That case is caught by the outcome and by the world basis, not by the symbolic basis.
PROJECTION = ProjectionContract(
    projectable=frozenset({P_DISCOVERED, P_DELIVERED, P_PENDING, P_LIGHT, P_HEAVY, P_DIFFERENT}),
    executive_tracked=frozenset({P_IN_POSE}),
)


def project(state: StateSnapshot) -> SymbolicState:
    """StateSnapshot -> SymbolicState, using NO geometry.

    This function must never read `AgentSnapshot.position`, `AgentSnapshot.direction`,
    `BoxSnapshot.position`, `StaticWorld.walls` or `StaticWorld.delivery_zone`. Two snapshots that
    differ only in where things are must project to the same symbolic state — that property is the
    behavioural proof that no feasibility oracle leaked in, and it is pinned by
    `tests/test_symbolic_projection.py`.

    The restriction is on the PROJECTION, which feeds symbolic applicability. It is not a general
    ban on reading positions: a P2 world-effect predictor works on `StateSnapshot` directly and is
    expected to read them (Decision 13.2).
    """
    literals = []
    for b in state.boxes:
        name = str(b.box_id)
        # Full observability from initialization (Decision 5).
        literals.append(GroundedLiteral(P_DISCOVERED, (name,)))
        if b.delivered:
            literals.append(GroundedLiteral(P_DELIVERED, (name,)))
        else:
            literals.append(GroundedLiteral(P_PENDING, (name,)))
        literals.append(
            GroundedLiteral(P_HEAVY if b.required_agents > 1 else P_LIGHT, (name,))
        )
    for a in state.agents:
        for other in state.agents:
            if a.agent_id != other.agent_id:
                literals.append(
                    GroundedLiteral(P_DIFFERENT, (a.agent_id.value, other.agent_id.value))
                )
    return SymbolicState.of(literals)


# ── action equivalence (R3 — report Phase 3 item 3) ──────────────────────────────────────
class BoxPushActionEquivalence:
    """The BoxPush abstraction-equivalence rule, extracted from the runtime comparator so
    the generic side holds no agent/box/zone rule: two DIFFERENT grounded calls that share
    skill/box/zone and differ only in agent binding are symbolically equivalent, because
    `in_pose` is intentionally non-exclusive (Decision 6) — either binding satisfies the
    same optimistic preconditions. Identity is handled by the caller, not here."""

    def benign_equivalence(self, proposed, selected, /):
        if (proposed.skill, proposed.box, proposed.zone) == (
            selected.skill, selected.box, selected.zone
        ):
            return (
                "same skill/box/zone, different agent binding — symbolically "
                "equivalent under non-exclusive optimism (Decision 6)"
            )
        return None
