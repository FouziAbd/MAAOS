"""P1 integration tests: the V1 adapter over the REAL BoxPush backend.

Unlike the P0 contract tests, this module imports and steps the authoritative backend
(minigrid/pettingzoo stack). It is still deterministic and offline: no LM, no network, no
rendering (render_mode=None), and the backend itself is fully deterministic — the `seed` is
observationally inert (section18.md §D).

Scenario setups use direct world-state injection (`_teleport_agent` / `_move_box`), which writes
the same fields the backend's own transitions write (world + agent_positions/agent_dirs + grid),
so the env remains self-consistent. That is test scaffolding for reaching states quickly, not a
bypass of execution semantics: every asserted TRANSITION behaviour still runs through `env.step`
(the pure-view tests — entities/export — assert derived views and step nothing).
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_DIR = os.path.join(_REPO_ROOT, "functional_layer", "custom_env", "box_push", "env")
for _p in (_REPO_ROOT, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from box_push_v1_adapter import BoxPushV1Adapter, _default_config
from objects import TargetPackage
from state import EnvConfig

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    initial_state,
)
from shared.backend_contract import V1Environment
from shared.execution import (
    NON_TERMINAL_PROGRESS_MARKER,
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    RawLabel,
)
from shared.faults import FaultKind, InfrastructureFaultError
from shared.ids import AgentId, BoxId, ZoneId
from shared.skills import REGISTRY, GroundedSkillCall, MalformedCall, SkillName, UngroundedCall

GOLDEN_INITIAL_WORLD_KEY = "f7cf4105cddd127a"


def _fresh(**config_overrides) -> BoxPushV1Adapter:
    if config_overrides:
        adapter = BoxPushV1Adapter(EnvConfig(
            width=12, height=12, num_agents=2, num_objects=2, num_target_objects=2,
            agent_view_size=3, render_mode=None, seed=42,
            **config_overrides,
        ))
    else:
        adapter = BoxPushV1Adapter()
    adapter.reset()
    return adapter


def _teleport_agent(adapter, agent_id: str, position, direction: int) -> None:
    env = adapter._env
    agent = env.core_env.world.agents[agent_id]
    env.core_env.grid.set(*agent.position, None)
    agent.position = tuple(position)
    agent.direction = int(direction)
    env.agent_positions[agent_id] = tuple(position)
    env.agent_dirs[agent_id] = int(direction)
    env.agent_objects[agent_id].dir = int(direction)
    env.core_env.grid.set(*position, env.agent_objects[agent_id])
    adapter._obs = env._get_all_observations()


def _move_box(adapter, box_id: int, position, delivered: bool = False) -> None:
    env = adapter._env
    obj = env.core_env.world.objects[box_id]
    env.core_env.grid.set(*obj.position, None)
    obj.position = tuple(position)
    if delivered and not obj.delivered:
        # keep the injected state backend-producible: real delivery also bumps the counter
        env.core_env.world.episode.delivered_target_count += 1
    obj.delivered = delivered
    env.core_env.grid.set(*position, TargetPackage())
    adapter._obs = env._get_all_observations()


def _goto(agents, box):
    return GroundedSkillCall(SkillName.GOTO_PUSH_POSE, agents, box, DELIVERY_ZONE)


def _push(agents, box):
    return GroundedSkillCall(SkillName.PUSH, agents, box, DELIVERY_ZONE)


def _coop(box):
    return GroundedSkillCall(SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), box, DELIVERY_ZONE)


# ── Protocol / reset / export ──────────────────────────────────────────────────────

class TestProtocolAndExport(unittest.TestCase):
    def test_adapter_satisfies_the_frozen_protocol(self):
        self.assertIsInstance(BoxPushV1Adapter(), V1Environment)

    def test_reset_export_equals_the_frozen_initial_state(self):
        """The behavioural freeze check: the P0 domain constants were transcribed from this
        backend, and here the LIVE backend reproduces them — agents at (10,10)/(10,9) facing
        LEFT, boxes at (6,6)/(8,4), goal column, outer walls. This subsumes the source-text
        drift pins with an executing test."""
        snapshot = _fresh().export_full_state()
        self.assertEqual(snapshot, initial_state())
        self.assertEqual(snapshot.world_key()[:16], GOLDEN_INITIAL_WORLD_KEY)

    def test_reset_is_deterministic_across_adapters_and_resets(self):
        a, b = _fresh(), _fresh()
        self.assertEqual(a.export_full_state().replay_key(), b.export_full_state().replay_key())
        first = a.export_full_state().world_key()
        a.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        a.reset()
        self.assertEqual(a.export_full_state().world_key(), first)

    def test_export_is_repeatable_and_normalized(self):
        """Round-trip stability: exporting twice yields identical canonical forms, and the
        canonical form is the NORMALIZED one (sorted members, deduped walls) even though the
        backend stores walls with the four corners duplicated."""
        adapter = _fresh()
        first, second = adapter.export_full_state(), adapter.export_full_state()
        self.assertEqual(first.canonical_full(), second.canonical_full())
        self.assertEqual(first.world_json(), second.world_json())
        raw_walls = adapter._env.core_env.world.static.walls
        self.assertGreater(len(raw_walls), len(set(map(tuple, raw_walls))))  # backend duplicates
        walls = first.static.walls
        self.assertEqual(len(walls), len(set(walls)))                        # snapshot dedupes
        self.assertEqual(walls, tuple(sorted(walls)))

    def test_export_reads_world_not_grid(self):
        """D4 behaviourally: corrupt the grid; the snapshot must not notice."""
        adapter = _fresh()
        adapter._env.core_env.grid.set(8, 4, None)      # vandalize the box's grid cell
        self.assertEqual(adapter.export_full_state(), initial_state())

    def test_export_follows_world_when_the_env_side_caches_desync(self):
        """D4 sharpened: the env keeps a SECOND copy of agent positions (`agent_positions`,
        used for rendering/obs). Desync it; the export must follow `world`, not the cache —
        mutation testing showed an export built from the cache was otherwise undetectable,
        because the two stay in sync through normal play."""
        adapter = _fresh()
        adapter._env.agent_positions["agent_0"] = (5, 5)        # cache lies
        adapter._env.agent_dirs["agent_0"] = 0
        snapshot = adapter.export_full_state()
        self.assertEqual(snapshot.agent(AGENT_0).position, (10, 10))   # world's truth
        self.assertEqual(snapshot.agent(AGENT_0).direction, 2)

    def test_observe_is_the_distinct_partial_channel(self):
        adapter = _fresh()
        obs = adapter.observe()
        self.assertEqual(set(obs), {"agent_0", "agent_1"})
        for agent_obs in obs.values():
            self.assertIn("image", agent_obs)           # egocentric view, not a StateSnapshot

    def test_the_adapter_never_touches_the_belief_layer(self):
        """Exact state, belief state and rendered grid stay distinct concepts: the adapter's
        IMPORTS reach no belief/middleware module. Checked on the AST — a prose scan would trip
        on docstrings that legitimately discuss the belief grid in order to forbid it."""
        import ast
        source_path = os.path.join(_ENV_DIR, "box_push_v1_adapter.py")
        with open(source_path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("middleware_layer", "deterministic_grid_updater",
                          "belief_manager", "model_layer", "dspy"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)


# ── Dispatch (D14 / D16) ───────────────────────────────────────────────────────────

class TestDispatchIsExplicitAndExhaustive(unittest.TestCase):
    def setUp(self):
        self.adapter = _fresh()

    def test_every_registry_dispatch_key_has_a_construction(self):
        from shared_skills import ExploreSkill, WaitSkill
        from skill_executor_push import CooperativePushSkill, GotoPushPoseSkill, PushSkill
        expected = {
            "goto_push_pose": GotoPushPoseSkill,
            "push": PushSkill,
            "cooperate_push": CooperativePushSkill,
            "explore": ExploreSkill,
            "wait": WaitSkill,
        }
        self.assertEqual(set(expected), set(REGISTRY.dispatch_keys()))
        calls = {
            "goto_push_pose": _goto((AGENT_0,), BOX_LIGHT),
            "push": _push((AGENT_0,), BOX_LIGHT),
            "cooperate_push": _coop(BOX_HEAVY),
            "explore": GroundedSkillCall(SkillName.EXPLORE, (AGENT_0,)),
            "wait": GroundedSkillCall(SkillName.WAIT, (AGENT_0,)),
        }
        for key, cls in expected.items():
            with self.subTest(key=key):
                built = self.adapter._construct_for_key(key, calls[key])
                self.assertTrue(built)
                for skill in built.values():
                    self.assertIsInstance(skill, cls)

    def test_an_unknown_token_has_no_fallback(self):
        self.assertIsNone(
            self.adapter._construct_for_key("bogus", _push((AGENT_0,), BOX_LIGHT))
        )

    def test_the_adapter_never_calls_make_skill(self):
        with open(os.path.join(_ENV_DIR, "box_push_v1_adapter.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("make_skill(", source)

    def test_the_frozen_argument_translation(self):
        """Decision 16's table, literally: goto/coop get the GROUNDED box's current cell,
        derived from world; push gets dest=None (the push-to-zone encoding); nothing receives a
        caller-supplied coordinate."""
        goto = self.adapter._construct_for_key("goto_push_pose", _goto((AGENT_0,), BOX_LIGHT))
        self.assertEqual(goto["agent_0"]._box_arg, (8, 4))
        push = self.adapter._construct_for_key("push", _push((AGENT_0,), BOX_LIGHT))
        self.assertIsNone(push["agent_0"]._dest)
        coop = self.adapter._construct_for_key("cooperate_push", _coop(BOX_HEAVY))
        self.assertEqual(set(coop), {"agent_0", "agent_1"})
        for agent_id, skill in coop.items():
            self.assertEqual(skill._box_arg, (6, 6))
            self.assertNotEqual(skill.partner_id, agent_id)


# ── The exact entities view (Decision 16 obligation 4) ─────────────────────────────

class TestEntitiesViewIsWorldDerived(unittest.TestCase):
    def test_labels_come_from_world(self):
        adapter = _fresh()
        cells = adapter._entities_for("agent_0")["grid"]["cells"]
        self.assertEqual(cells[0][0], "wall")
        self.assertEqual(cells[1][4], "delivery_zone")
        self.assertEqual(cells[8][4], "target_object")   # box_1
        self.assertEqual(cells[6][6], "target_object")   # box_0
        self.assertEqual(cells[10][9], "agent")          # the OTHER agent
        self.assertEqual(cells[10][10], "empty")         # never the observer itself
        self.assertEqual(cells[5][5], "empty")
        self.assertNotIn("unknown", {c for col in cells for c in col})   # fully observed

    def test_the_view_is_not_the_belief_grid(self):
        """Headline 0's root cause was the belief writing agents as 'empty'. The exact view
        writes them as 'agent' — the choice recorded as the obligation-4 resolution."""
        adapter = _fresh()
        cells = adapter._entities_for("agent_0")["grid"]["cells"]
        self.assertEqual(cells[10][9], "agent")

    def test_a_delivered_box_cell_shows_the_underlying_zone(self):
        """Delivered boxes are non-colliding ghosts in the backend; labelling them as boxes
        would wrongly block navigation and re-offer them as push targets."""
        adapter = _fresh()
        _move_box(adapter, 1, (1, 4), delivered=True)
        cells = adapter._entities_for("agent_0")["grid"]["cells"]
        self.assertEqual(cells[1][4], "delivery_zone")

    def test_self_fields_match_world(self):
        adapter = _fresh()
        entities = adapter._entities_for("agent_1")
        self.assertEqual(entities["self"]["position"], [10, 9])
        self.assertEqual(entities["self"]["direction"], 2)


# ── Executive skills end-to-end ────────────────────────────────────────────────────

class TestSuccessfulExecution(unittest.TestCase):
    def test_goto_push_pose_succeeds_with_true_accounting(self):
        adapter = _fresh()
        pre_count = adapter.export_full_state().episode.step_count
        result = adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        self.assertIsInstance(result, ExecutionResult)
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertIs(result.raw_label, RawLabel.IN_POSITION)
        self.assertIsNone(result.failure_class)
        self.assertEqual(result.accounting.executive_steps, 1)
        # D2: primitive steps are ACTUAL env.step calls — cross-checked against the backend's
        # own joint step counter, which increments exactly once per env.step.
        post = adapter.export_full_state()
        self.assertEqual(result.accounting.primitive_steps,
                         post.episode.step_count - pre_count)
        self.assertGreater(result.accounting.primitive_steps, 0)
        # authoritative success geometry: behind the box, facing the push direction
        self.assertEqual(post.agent(AGENT_0).position, (9, 4))
        self.assertEqual(post.agent(AGENT_0).direction, 2)

    def test_push_delivers_the_grounded_box(self):
        adapter = _fresh()
        adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertIs(result.raw_label, RawLabel.DELIVERED)
        box = adapter.export_full_state().box(BOX_LIGHT)
        self.assertTrue(box.delivered)
        self.assertIn(box.position, adapter.export_full_state().static.delivery_zone)

    def test_cooperative_push_is_one_executive_invocation(self):
        """D1: ONE call, two backend instances internally, both agents moved, one executive
        step. Also the deterministic raw-vs-typed case: delivering the LAST box terminates the
        episode in the same joint step, so the skills never reach their evaluation iteration —
        raw is the non-terminal marker while the AUTHORITATIVE outcome is SUCCESS (D3)."""
        adapter = _fresh()
        adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        pre = adapter.export_full_state()
        result = adapter.execute_skill(_coop(BOX_HEAVY))
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(result.accounting.executive_steps, 1)
        self.assertTrue(adapter.export_full_state().box(BOX_HEAVY).delivered)
        self.assertTrue(adapter.is_terminal())
        # both agents participated (moved from their pre-call cells)
        post = adapter.export_full_state()
        self.assertNotEqual(post.agent(AGENT_0).position, pre.agent(AGENT_0).position)
        self.assertNotEqual(post.agent(AGENT_1).position, pre.agent(AGENT_1).position)
        # the raw-vs-typed disagreement, pinned:
        self.assertIsNone(result.raw_label)
        self.assertIn(NON_TERMINAL_PROGRESS_MARKER, result.detail)

    def test_wait_is_one_executive_and_zero_primitive_steps(self):
        adapter = _fresh()
        pre_count = adapter.export_full_state().episode.step_count
        result = adapter.execute_skill(GroundedSkillCall(SkillName.WAIT, (AGENT_0,)))
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertIs(result.raw_label, RawLabel.DONE)
        self.assertEqual(result.accounting.executive_steps, 1)
        self.assertEqual(result.accounting.primitive_steps, 0)
        self.assertEqual(adapter.export_full_state().episode.step_count, pre_count)
        self.assertTrue(result.pre_state.same_world(result.post_state))

    def test_explore_exhausts_its_budget_under_full_observability(self):
        """With the exact grid there is nothing 'unknown' to discover, so Explore scans until
        its backend budget (30) runs out — reported as an explicit typed TIMEOUT (D3), never as
        the raw label's 'explored'."""
        adapter = _fresh()
        result = adapter.execute_skill(GroundedSkillCall(SkillName.EXPLORE, (AGENT_0,)))
        self.assertIs(result.outcome, ExecutionOutcome.TIMEOUT)
        self.assertIs(result.raw_label, RawLabel.EXPLORED)
        self.assertEqual(result.accounting.primitive_steps, 30)
        self.assertIn("timed_out=true", result.detail)


class TestFailureSemantics(unittest.TestCase):
    def test_partial_execution_box_moved_then_blocked(self):
        """Push toward the top wall: the box slides (8,4)->(8,1), then the landing cell is the
        wall. World changed, intent unrealized: PARTIAL + PARTIAL_EXECUTION, with the
        authoritative reason derived from world."""
        adapter = _fresh()
        _teleport_agent(adapter, "agent_0", (8, 5), 3)          # behind box_1, facing UP
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIs(result.outcome, ExecutionOutcome.PARTIAL)
        self.assertIs(result.failure_class, FailureStateClass.PARTIAL_EXECUTION)
        self.assertIs(result.raw_label, RawLabel.BLOCKED)
        self.assertEqual(adapter.export_full_state().box(BOX_LIGHT).position, (8, 1))
        self.assertIn("authoritative_reason=landing_cell_is_wall", result.detail)
        self.assertFalse(result.pre_state.same_world(result.post_state))

    def test_backend_rejected_before_transition(self):
        """Nothing pushable in front: the skill declines on its first step(); the runner-faithful
        loop still submits the terminal STAY, so exactly ONE env.step is consumed."""
        adapter = _fresh()
        _teleport_agent(adapter, "agent_0", (5, 9), 2)          # open floor, facing LEFT
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.failure_class, FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION)
        self.assertIs(result.raw_label, RawLabel.BLOCKED)
        self.assertEqual(result.accounting.primitive_steps, 1)
        self.assertIn("authoritative_reason=no_pushable_box_in_front", result.detail)
        self.assertTrue(result.pre_state.same_world(result.post_state))

    def test_cooperative_runway_blocked_is_rejected_before_transition(self):
        adapter = _fresh()
        _move_box(adapter, 1, (7, 6))                           # box_1 onto a tandem slot
        result = adapter.execute_skill(_coop(BOX_HEAVY))
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.failure_class, FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION)
        self.assertIs(result.raw_label, RawLabel.BLOCKED)
        self.assertEqual(result.accounting.primitive_steps, 1)

    def test_goto_blocked_by_partner_on_the_pose_cell(self):
        """The designed optimistic-navigation failure (acceptance scenario #2 material): the
        pose cell is physically occupied, BFS on the exact grid finds no path, the no-progress
        bail fires. The wanderer moved, so this is PARTIAL, not a no-op."""
        adapter = _fresh()
        _teleport_agent(adapter, "agent_1", (9, 4), 2)          # partner parked ON the pose
        result = adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        self.assertIs(result.outcome, ExecutionOutcome.PARTIAL)
        self.assertIs(result.raw_label, RawLabel.BLOCKED)
        self.assertIs(result.failure_class, FailureStateClass.PARTIAL_EXECUTION)

    def test_wrong_box_push_raw_label_disagrees_with_authoritative_outcome(self):
        """THE frozen disagreement case (Decision 16 obligation 2, row 2): agent physically
        behind heavy box_0, grounded call names light box_1. The raw label says `too_heavy` —
        a claim about a box the call never named — while the authoritative record identifies
        the front box and reports the grounded box untouched. This is discrepancy territory
        for the upstream monitor, never a grounding fault."""
        adapter = _fresh()
        _teleport_agent(adapter, "agent_0", (7, 6), 2)          # behind heavy box_0, facing LEFT
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIsInstance(result, ExecutionResult)          # not a fault, not a rejection
        self.assertIs(result.raw_label, RawLabel.TOO_HEAVY)     # provenance, preserved untouched
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.failure_class, FailureStateClass.UNCHANGED)
        self.assertIn(
            "authoritative_reason=front_box_requires_2_agents_front_box_is_box_0"
            "_not_grounded_box_1",
            result.detail,
        )
        post = adapter.export_full_state()
        self.assertEqual(post.box(BOX_LIGHT).position, (8, 4))  # grounded box untouched
        self.assertEqual(post.box(BOX_LIGHT).required_agents, 1)  # and it is NOT heavy

    def test_repushing_a_delivered_box_is_never_success(self):
        """Success is the delivered-flag FLIP, not 'box position in zone' and not 'delivered is
        True' — a position-based mutant reported SUCCESS here. The delivered ghost still renders
        TARGET_OBJECT in obs, so the skill genuinely re-attempts: the agent walks onto the
        ghost's cell and ends blocked at the wall."""
        adapter = _fresh()
        adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertTrue(adapter.export_full_state().box(BOX_LIGHT).delivered)
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIsNot(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertIs(result.outcome, ExecutionOutcome.PARTIAL)     # the agent moved
        self.assertIn("authoritative_reason=no_pushable_box_in_front", result.detail)
        # the grounded box did not move again
        self.assertEqual(adapter.export_full_state().box(BOX_LIGHT).position, (1, 4))

    def test_landing_cell_occupied_by_agent_reason(self):
        """THE headline-0 geometry (partner on the landing cell), against the live backend.
        Note the raw label: with the exact entities view the beyond-cell is labeled `agent`,
        so the backend itself now says `blocked` — the belief-era `too_heavy` mislabel cannot
        arise on this path. The authoritative reason pins the true cause either way."""
        adapter = _fresh()
        _teleport_agent(adapter, "agent_0", (9, 4), 2)          # behind box_1, facing LEFT
        _teleport_agent(adapter, "agent_1", (7, 4), 2)          # ON the landing cell
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.raw_label, RawLabel.BLOCKED)
        self.assertIs(result.failure_class, FailureStateClass.UNCHANGED)
        self.assertIn("authoritative_reason=landing_cell_occupied_by_agent", result.detail)
        self.assertEqual(adapter.export_full_state().box(BOX_LIGHT).position, (8, 4))

    def test_landing_cell_occupied_by_box_reason(self):
        """Push box_1 westward into box_0: agent at (8,6) faces LEFT, box_1 in front at (7,6),
        landing cell (6,6) holds heavy box_0."""
        adapter = _fresh()
        _move_box(adapter, 1, (7, 6))
        _teleport_agent(adapter, "agent_0", (8, 6), 2)
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.raw_label, RawLabel.BLOCKED)
        self.assertIn("authoritative_reason=landing_cell_occupied_by_box", result.detail)
        self.assertEqual(adapter.export_full_state().box(BOX_LIGHT).position, (7, 6))

    def test_explicit_timeout_detection(self):
        """A real backend timeout, no monkeypatching: box_1 sits on box_0's push destination,
        so `_tandem_feasible` fails every joint push and CooperativePush burns its whole budget
        (150). The raw label is `waiting_partner` — misleading — while the wrapper detects the
        exhausted budget explicitly and reports typed TIMEOUT (D3)."""
        adapter = _fresh()
        _move_box(adapter, 1, (5, 6))                           # on box_0's destination
        result = adapter.execute_skill(_coop(BOX_HEAVY))
        self.assertIs(result.outcome, ExecutionOutcome.TIMEOUT)
        self.assertIs(result.raw_label, RawLabel.WAITING_PARTNER)
        self.assertIs(result.failure_class, FailureStateClass.PARTIAL_EXECUTION)
        self.assertEqual(result.accounting.primitive_steps, 150)
        self.assertIn("timed_out=true", result.detail)

    def test_goto_success_requires_the_facing_not_just_the_cell(self):
        """Success geometry is pose cell AND push direction (Decision 13.5). Reachable wrong-
        facing terminal state: start ON the pose cell facing RIGHT (two turns needed) with a
        1-step budget — the episode truncates after the first turn, leaving the agent at the
        pose but facing DOWN. A cell-only success test would call this a success."""
        adapter = _fresh(max_steps=1)
        _teleport_agent(adapter, "agent_0", (9, 4), 0)          # at pose, facing RIGHT
        result = adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        post = adapter.export_full_state()
        self.assertEqual(post.agent(AGENT_0).position, (9, 4))  # on the pose cell...
        self.assertNotEqual(post.agent(AGENT_0).direction, 2)   # ...but not facing LEFT
        self.assertIsNot(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertIs(result.outcome, ExecutionOutcome.PARTIAL)  # the turn changed the world

    def test_truncation_mid_skill_is_reported_not_invented(self):
        adapter = _fresh(max_steps=3)
        result = adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        self.assertEqual(result.accounting.primitive_steps, 3)
        self.assertIsNone(result.raw_label)                     # no terminal label was produced
        self.assertIn(NON_TERMINAL_PROGRESS_MARKER, result.detail)
        self.assertTrue(adapter.is_terminal())


# ── Rejections and guards ──────────────────────────────────────────────────────────

class TestRejectionsAndGuards(unittest.TestCase):
    def test_ungrounded_identities_are_rejected_before_execution(self):
        adapter = _fresh()
        cases = {
            "agent": GroundedSkillCall(
                SkillName.PUSH, (AgentId("agent_9"),), BOX_LIGHT, DELIVERY_ZONE),
            "box": GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BoxId(7), DELIVERY_ZONE),
            "zone": GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, ZoneId("mars")),
        }
        for name, call in cases.items():
            with self.subTest(identity=name):
                rejection = adapter.execute_skill(call)
                self.assertIsInstance(rejection, UngroundedCall)
                self.assertTrue(rejection.is_pre_executor_rejection)
        # zero executive steps AND zero primitive steps: nothing was executed
        self.assertEqual(adapter.export_full_state().episode.step_count, 0)
        self.assertEqual(adapter.export_full_state(), initial_state())

    def test_malformed_input_is_rejected_never_substituted(self):
        adapter = _fresh()
        for garbage in ("push", {"skill": "push"}, None, 42):
            with self.subTest(garbage=garbage):
                rejection = adapter.execute_skill(garbage)
                self.assertIsInstance(rejection, MalformedCall)
        self.assertEqual(adapter.export_full_state().episode.step_count, 0)

    def test_pre_flight_is_identity_only_never_a_feasibility_gate(self):
        """An optimistic call in an infeasible situation must REACH the backend and fail there
        — pre-flight refusing it would be the feasibility oracle Decision 6/16 forbids."""
        adapter = _fresh()                                      # agent nowhere near the box
        result = adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertIsInstance(result, ExecutionResult)          # attempted, one executive step
        self.assertEqual(result.accounting.executive_steps, 1)

    def test_reset_before_use_is_refused(self):
        adapter = BoxPushV1Adapter()
        for method in (adapter.export_full_state, adapter.observe, adapter.is_terminal,
                       lambda: adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))):
            with self.subTest(method=getattr(method, "__name__", "execute_skill")):
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    method()
                self.assertIs(ctx.exception.fault.kind,
                              FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
                self.assertIsNone(ctx.exception.result)

    def test_post_terminal_execution_is_refused_as_a_fault(self):
        adapter = _fresh(max_steps=2)
        adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))     # truncates at step 2
        self.assertTrue(adapter.is_terminal())
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(GroundedSkillCall(SkillName.WAIT, (AGENT_0,)))
        self.assertIs(ctx.exception.fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("terminal", ctx.exception.fault.message)
        self.assertIsNone(ctx.exception.result)                 # refused BEFORE execution

    def test_cooperative_substitution_is_detected_post_flight(self):
        """The COOP arm of Decision 16 obligation 3 (previously only the goto arm was covered —
        disabling the coop arm survived mutation testing). Ground CooperativePush on the
        already-delivered light box: `_resolve_box` falls back to the heavy box and the tandem
        moves IT — grounded box untouched, a different box moved, protocol fault."""
        adapter = _fresh()
        adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))     # box_1 delivered, box_0 pending
        self.assertFalse(adapter.is_terminal())
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(_coop(BOX_LIGHT))             # grounded on the DELIVERED box
        self.assertIs(ctx.exception.fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("substitution", ctx.exception.fault.message)
        self.assertIn("box_0", ctx.exception.fault.message)     # the box that actually moved
        attached = ctx.exception.result
        self.assertIsInstance(attached, ExecutionResult)
        self.assertEqual(attached.accounting.executive_steps, 1)

    def test_substitution_is_detected_post_flight_and_raised_as_a_fault(self):
        """Decision 16 obligation 3: ground GotoPushPose on the (delivered) light box; the
        backend's `_resolve_box` silently falls back to the heavy box and reports in_position at
        the WRONG pose. The adapter detects the substitution, raises the protocol fault, and
        attaches the ExecutionResult — the attempt consumed its executive step."""
        adapter = _fresh()
        _move_box(adapter, 1, (1, 4), delivered=True)
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        self.assertIs(ctx.exception.fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("substitution", ctx.exception.fault.message)
        attached = ctx.exception.result
        self.assertIsInstance(attached, ExecutionResult)
        self.assertEqual(attached.accounting.executive_steps, 1)
        self.assertIs(attached.raw_label, RawLabel.IN_POSITION)  # the backend's false claim


# ── Accounting and diagnostics ─────────────────────────────────────────────────────

class TestAccountingAndDiagnostics(unittest.TestCase):
    def test_primitive_steps_always_equal_the_backend_joint_counter_delta(self):
        """D2 across heterogeneous skills, cross-checked against the backend's own counter."""
        adapter = _fresh()
        for call in (
            GroundedSkillCall(SkillName.WAIT, (AGENT_0,)),
            _goto((AGENT_0,), BOX_LIGHT),
            _push((AGENT_0,), BOX_LIGHT),
            GroundedSkillCall(SkillName.EXPLORE, (AGENT_1,)),
        ):
            with self.subTest(skill=call.skill):
                before = adapter.export_full_state().episode.step_count
                result = adapter.execute_skill(call)
                after = adapter.export_full_state().episode.step_count
                self.assertEqual(result.accounting.primitive_steps, after - before)
                self.assertEqual(result.accounting.executive_steps, 1)

    def test_executive_steps_are_never_inferred_from_primitive_steps(self):
        adapter = _fresh()
        wait = adapter.execute_skill(GroundedSkillCall(SkillName.WAIT, (AGENT_0,)))
        goto = adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        self.assertEqual(wait.accounting.executive_steps, goto.accounting.executive_steps)
        self.assertNotEqual(wait.accounting.primitive_steps, goto.accounting.primitive_steps)

    def test_a_label_outside_the_vocabulary_becomes_a_typed_fault(self):
        """The untyped-escape hole: a backend label outside the frozen vocabulary must surface
        as InfrastructureFaultError(MALFORMED_BACKEND_RESULT), never as a bare ValueError.
        Unreachable with the frozen backend, so exercised at the interpretation seam with a
        stub skill carrying an alien label."""
        adapter = _fresh()

        class _AlienSkill:
            label = "banana"
            is_done = True
            _steps = 0
            _MAX_STEPS = 99

        pre = adapter.export_full_state()
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter._interpret(
                _push((AGENT_0,), BOX_LIGHT), pre, pre,
                {"agent_0": _AlienSkill()}, 1, {"agent_0": 1},
            )
        self.assertIs(ctx.exception.fault.kind, FaultKind.MALFORMED_BACKEND_RESULT)
        self.assertIn("banana", ctx.exception.fault.message)
        # case-(c) provenance: this producer must carry the consumed primitive count too
        self.assertIn("primitive_steps_before_failure=1", ctx.exception.fault.detail)

    def test_env_step_exception_becomes_a_typed_backend_fault(self):
        """F2 pin from the P1 consistency check: an exception out of the authoritative
        transition must surface as `InfrastructureFaultError(BACKEND_API_EXCEPTION)` carrying
        the primitive count consumed so far — never as a bare exception. Unreachable with the
        frozen backend, so injected at the env seam: the transition succeeds twice, then raises
        mid-flight (case (c) of the three-case rule: `result=None`, world already changed)."""
        adapter = _fresh()
        original_step = adapter._env.step
        successful_calls = []

        def failing_step(actions):
            if len(successful_calls) >= 2:
                raise RuntimeError("cosmic ray")
            successful_calls.append(1)
            return original_step(actions)

        adapter._env.step = failing_step
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        fault = ctx.exception.fault
        self.assertIs(fault.kind, FaultKind.BACKEND_API_EXCEPTION)
        self.assertIn("cosmic ray", fault.message)
        self.assertIn("primitive_steps_before_failure=2", fault.detail)
        self.assertIsNone(ctx.exception.result)                 # mid-execution: case (c)
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        # the two successful transitions really happened — the world is NOT untouched
        self.assertEqual(adapter.export_full_state().episode.step_count, 2)

    def test_refusal_messages_carry_the_shared_prefix(self):
        """The (b)-side of the three-case provenance rule: both refusal producers begin with
        `refused:` so P4 discriminates (b) from (c) without exact-string matching per site."""
        before_reset = BoxPushV1Adapter()
        with self.assertRaises(InfrastructureFaultError) as ctx:
            before_reset.export_full_state()
        self.assertTrue(ctx.exception.fault.message.startswith("refused:"))
        # ...and refusals never carry case-(c) provenance — asserted on BOTH producers
        self.assertNotIn("primitive_steps", ctx.exception.fault.detail)
        terminal = _fresh(max_steps=2)
        terminal.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        with self.assertRaises(InfrastructureFaultError) as ctx:
            terminal.execute_skill(GroundedSkillCall(SkillName.WAIT, (AGENT_0,)))
        self.assertTrue(ctx.exception.fault.message.startswith("refused:"))
        self.assertNotIn("primitive_steps", ctx.exception.fault.detail)

    def test_runaway_cap_fault_carries_the_single_provenance_key(self):
        """F-1 pin: the cap producer must use the SAME key as every other case-(c) producer
        (`primitive_steps_before_failure`) — an earlier revision used a second spelling that
        both collided with the `primitive_steps_consumed` accessor name and broke the exact
        string the P4 work item tells the loop to parse. The cap is unreachable with real
        backend budgets, so it is exercised by lowering the module constant."""
        import box_push_v1_adapter as adapter_module
        original_cap = adapter_module._HARD_CAP
        self.addCleanup(setattr, adapter_module, "_HARD_CAP", original_cap)
        adapter_module._HARD_CAP = 5
        adapter = _fresh()
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        fault = ctx.exception.fault
        self.assertIs(fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
        self.assertIn("failed to terminate", fault.message)
        self.assertIn("primitive_steps_before_failure=5", fault.detail)
        self.assertNotIn("primitive_steps_consumed", fault.detail)   # the retired spelling
        self.assertIsNone(ctx.exception.result)                      # case (c)

    def test_case_c_trace_accessors_report_recorded_accounting_only(self):
        """F-A pin: a case-(c) TraceEntry (mid-execution fault, no ExecutionResult) reports 0/0
        from the convenience accessors BY DESIGN — they read recorded structured accounting, and
        the consumed step/primitives survive only in `fault.detail`. P4 charges budgets from
        fault provenance on top of `ExecutiveHistory`'s sums. Frozen deliberately so a later
        silent change to either side is loud."""
        from domain.box_push_v1 import MODEL_VERSION, TASK_DELIVER_LIGHT, _PROVENANCE
        from shared.faults import InfrastructureFault
        from shared.trace_schema import TraceEntry
        entry = TraceEntry(
            executive_step=0, task=TASK_DELIVER_LIGHT, pre_state=initial_state(),
            model_version=MODEL_VERSION, provenance=_PROVENANCE,
            faults=(InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION, message="env.step raised RuntimeError",
                detail="primitive_steps_before_failure=2",
            ),),
        )
        self.assertEqual(entry.executive_steps_consumed, 0)     # recorded accounting only
        self.assertEqual(entry.primitive_steps_consumed, 0)
        self.assertTrue(entry.short_circuited)
        self.assertIn("primitive_steps_before_failure=2", entry.faults[0].detail)

    def test_world_grid_divergence_diagnostic(self):
        """The §18-item-5 guard as a DIAGNOSTIC: clean at reset; nonempty after a delivery
        (the delivered box's TargetPackage lingers in the grid while world says delivered).
        It gates nothing — which is exactly why export reads world only."""
        adapter = _fresh()
        self.assertEqual(adapter.world_grid_divergence(), [])
        adapter.execute_skill(_goto((AGENT_0,), BOX_LIGHT))
        adapter.execute_skill(_push((AGENT_0,), BOX_LIGHT))
        self.assertEqual(adapter.world_grid_divergence(), [])   # delivered boxes are skipped
        # now vandalize the grid: the diagnostic sees it, the export does not
        adapter._env.core_env.grid.set(6, 6, None)
        self.assertTrue(any("box_0" in m for m in adapter.world_grid_divergence()))
        self.assertEqual(adapter.export_full_state().box(BOX_HEAVY).position, (6, 6))


if __name__ == "__main__":
    unittest.main()
