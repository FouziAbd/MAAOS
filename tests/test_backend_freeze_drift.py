"""Detect drift between the frozen V1 domain and the authoritative backend source.

Without this, `tests/test_domain_freeze.py` only compares `domain/box_push_v1.py` constants to
literals hardcoded in a test file — both authored from the same reading of the backend — so an
actual backend edit (e.g. moving `GOAL_ZONE`) would leave the suite green. That was demonstrated
by mutation testing.

This test reads the backend SOURCE TEXT rather than importing it, so it stays offline and free of
the minigrid/pettingzoo dependency, and it does not violate the no-backend-import rule: the rule
forbids `shared/` and `domain/` from importing the backend, and this is a test that reads files.
"""
import pathlib
import re
import unittest

from domain.box_push_v1 import (
    BOX_HEAVY,
    BOX_LIGHT,
    GOAL_ZONE,
    GRID_HEIGHT,
    GRID_WIDTH,
    initial_state,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BOX_PUSH_ENV = REPO_ROOT / "functional_layer/custom_env/box_push/env/box_push_env.py"
MULTI_AGENT_ENV = REPO_ROOT / "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py"
SKILL_EXECUTOR = REPO_ROOT / "functional_layer/custom_env/box_push/env/skill_executor_push.py"


class TestBackendSourceStillMatchesTheFreeze(unittest.TestCase):
    def setUp(self):
        # A missing backend file is a hard failure, not a skip: silently passing would recreate
        # exactly the blind spot this module exists to close.
        for path in (BOX_PUSH_ENV, MULTI_AGENT_ENV, SKILL_EXECUTOR):
            self.assertTrue(path.exists(), f"authoritative backend file missing: {path}")
        self.core = BOX_PUSH_ENV.read_text(encoding="utf-8")
        self.multi = MULTI_AGENT_ENV.read_text(encoding="utf-8")

    def test_goal_zone_literal_still_matches(self):
        """box_push_env.py:39 — GOAL_ZONE = [(1, y) for y in range(1, 11)]"""
        m = re.search(
            r"GOAL_ZONE.*?=\s*\[\(\s*(\d+)\s*,\s*y\s*\)\s*for\s+y\s+in\s+range\(\s*(\d+)\s*,\s*(\d+)\s*\)\]",
            self.core,
        )
        self.assertIsNotNone(m, "could not find the GOAL_ZONE literal in the backend source")
        x, start, stop = (int(g) for g in m.groups())
        self.assertEqual(tuple((x, y) for y in range(start, stop)), GOAL_ZONE)

    def test_box_definitions_still_match(self):
        """box_push_env.py:78-82 — _get_initial_object_states."""
        found = dict(
            (int(oid), (int(x), int(y), int(req)))
            for oid, x, y, req in re.findall(
                r"ObjectState\(object_id=(\d+),\s*position=\((\d+),\s*(\d+)\),"
                r"\s*is_target=True,\s*required_agents=(\d+)\)",
                self.core,
            )
        )
        self.assertEqual(len(found), 2, f"expected two frozen boxes, found {found}")
        state = initial_state()
        for box_id in (BOX_HEAVY, BOX_LIGHT):
            with self.subTest(box=box_id):
                x, y, required = found[box_id.value]
                snap = state.box(box_id)
                self.assertEqual((x, y), snap.position)
                self.assertEqual(required, snap.required_agents)

    def test_agent_start_positions_still_match(self):
        """multi_agent_box_push_env.py:90-91 — _get_agent_start_positions."""
        m = re.search(r"_get_agent_start_positions.*?return\s*\[(.*?)\]", self.multi, re.S)
        self.assertIsNotNone(m, "could not find _get_agent_start_positions in the backend source")
        starts = [
            (int(x), int(y)) for x, y in re.findall(r"\((\d+),\s*(\d+)\)", m.group(1))
        ]
        state = initial_state()
        # The backend lists more start positions than V1 uses (it supports up to four agents); the
        # frozen instance takes the first two. Assert the surplus explicitly so a future 4-agent
        # instance is not silently unpinned by a zip that stops early.
        self.assertGreaterEqual(len(starts), len(state.agents))
        for index, agent in enumerate(state.agents):
            with self.subTest(agent=agent.agent_id):
                self.assertEqual(starts[index], agent.position)

    def test_agents_still_start_facing_left(self):
        """Anchored on the PER-AGENT ASSIGNMENT. `assertIn("Directions.LEFT", self.multi)` was
        satisfied by an unrelated line (`self.core_env.agent_dir = int(Directions.LEFT)`), so
        flipping the actual per-agent facing — which is inside `world_key()` and the pinned golden
        key — survived every mutation."""
        # Line-anchored, not a substring: `assertIn` accepted any line the pinned text merely
        # PREFIXES — `... = Directions.LEFT if agent_id == "agent_0" else Directions.RIGHT`
        # satisfied both the substring and the count check while flipping agent_1's frozen
        # starting facing. The regex requires the assignment to END at LEFT (a trailing comment
        # is the only thing allowed after it).
        self.assertRegex(
            self.multi,
            r"(?m)^\s*self\.agent_dirs\[agent_id\] = Directions\.LEFT\s*(#.*)?$",
        )
        # and exactly one per-agent facing assignment of any form, so a second, conditional
        # assignment elsewhere cannot reintroduce the flip
        self.assertEqual(self.multi.count("self.agent_dirs[agent_id] = Directions."), 1)
        for agent in initial_state().agents:
            with self.subTest(agent=agent.agent_id):
                self.assertEqual(agent.direction, 2)   # constants.py:31-36 LEFT == 2

    def test_the_grid_size_still_matches_the_freeze(self):
        """`GRID_WIDTH`/`GRID_HEIGHT` were asserted only against literals in another test file —
        both authored from the same reading — so the backend default could move unnoticed."""
        state_module = (
            REPO_ROOT / "functional_layer/custom_env/cooperative_search_transport/env/state.py"
        ).read_text(encoding="utf-8")
        m = re.search(r"width:\s*int\s*=\s*(\d+)\s*\n\s*height:\s*int\s*=\s*(\d+)", state_module)
        self.assertIsNotNone(m, "could not find the EnvConfig grid defaults")
        self.assertEqual((int(m.group(1)), int(m.group(2))), (GRID_WIDTH, GRID_HEIGHT))
        # and the runner's explicit override must agree with the freeze
        runner = (
            REPO_ROOT / "functional_layer/custom_env/box_push/env/box_push_centralized.py"
        ).read_text(encoding="utf-8")
        r = re.search(r"EnvConfig\(width=(\d+),\s*height=(\d+)", runner)
        self.assertIsNotNone(r, "could not find the runner's EnvConfig")
        self.assertEqual((int(r.group(1)), int(r.group(2))), (GRID_WIDTH, GRID_HEIGHT))

    def test_grid_is_still_square_and_walled_only_at_the_border(self):
        self.assertIn("grid.wall_rect(0, 0, width, height)", self.core)
        self.assertIn("Open arena", self.core)         # no internal dividers
        self.assertEqual(GRID_WIDTH, GRID_HEIGHT)

    def test_step_counter_is_still_a_joint_primitive_counter(self):
        """The executive-step contract rests on this being per-joint-step, not per agent."""
        self.assertIn("self.core_env.world.episode.step_count += 1", self.multi)

    def test_the_backend_factory_still_lacks_a_wait_arm(self):
        """Decision 14 rests on a claim about the CURRENT backend: `make_skill` dispatches on four
        tokens and returns WaitSkill from its silent default for everything else, so `"wait"`,
        `"Push"` and `""` are observationally identical. If someone adds the missing arm, this
        fails and the P1 obligation should be re-read — not deleted."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        arms = set(re.findall(r'name\s*==\s*"([a-z_]+)"', text))
        self.assertEqual(
            arms,
            {"explore", "goto_push_pose", "push", "cooperate_push"},
            "backend dispatch arms changed; re-check P0_V1_DECISIONS Decision 14",
        )
        self.assertNotIn("wait", arms)

    def test_the_pose_cell_arithmetic_still_matches_the_declared_world_effect(self):
        """Decision 13.2/13.3: GotoPushPose's `predicted_world_effects` claim the agent ends on
        `box - direction_vector(push_dir)` facing `push_dir`. That is transcribed from these two
        lines, and it is arithmetic — a nearest-goal-cell choice, no search."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        self.assertIn("behind   = [box[0] - dx, box[1] - dy]", text)
        body = re.search(r"def _push_dir_toward_goal.*?(?=\ndef )", text, re.S)
        self.assertIsNotNone(body, "could not find _push_dir_toward_goal in the backend source")
        self.assertIn("min(GOAL_ZONE", body.group(0))
        for banned in ("bfs", "_is_free", "_cell_label", "grid", "walls", "occup"):
            with self.subTest(token=banned):
                self.assertNotIn(
                    banned, body.group(0).lower(),
                    "push_dir became feasibility-aware; a predicted world effect grounded on it "
                    "would then be a disguised oracle (Decision 13.2)",
                )

    def test_tandem_slots_are_still_two_distinct_cells(self):
        """CooperativePush's `predicted_world_effects` claim the two agents end on B-D and B-2D —
        DISTINCT cells. An earlier revision of this repository declared both on the same cell,
        which the backend can never produce. Pin the arithmetic on both sides."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        self.assertIn("a1 = (bx - dx, by - dy)", text)
        self.assertIn("a2 = (bx - 2 * dx, by - 2 * dy)", text)
        self.assertIn("(bx - 2 * dx, by - 2 * dy)", self.multi)     # _find_tandem agrees

    def test_slot_assignment_is_still_proximity_based_not_call_order(self):
        """Why the CooperativePush effect is stated as a SET: which agent takes the front slot is
        decided by the backend, not by the canonically ordered agent pair in the call.

        Scoped to `_assign_slots` and pinned on the DECISION EXPRESSION. Searching the whole file
        for `_manhattan(pos, a1)` let the tie-break be promoted to the sole criterion while the
        proximity computation lingered as a dead assignment."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        body = re.search(r"def _assign_slots.*?(?=\n    def )", text, re.S)
        self.assertIsNotNone(body, "could not find _assign_slots in the backend source")
        self.assertIn(
            "i_am_a1 = d_self < d_part or (d_self == d_part and self.agent_id < self.partner_id)",
            body.group(0),
        )
        self.assertIn("d_self = _manhattan(pos, a1)", body.group(0))

    def test_push_still_takes_its_direction_from_the_agent_facing(self):
        """`PushSkill` never calls `_push_dir_toward_goal`; it uses the agent's current facing
        (`:204-206`). The declared Push effect says so — if this changes, the declaration lies."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        push = re.search(r"class PushSkill.*?(?=\nclass )", text, re.S)
        self.assertIsNotNone(push, "could not find PushSkill in the backend source")
        self.assertNotIn("_push_dir_toward_goal", push.group(0))
        self.assertIn('d      = int(self_e.get("direction", 2))', push.group(0))

    def test_push_terminal_movement_semantics_are_unchanged(self):
        """Pins the arithmetic behind `Push.predicted_world_effects`' TERMINAL agent position.

        `PushSkill` is a loop: each iteration the agent advances to `pos + D` and the box to
        `pos + 2D`, and it finishes `delivered` when the box's landing cell is a goal cell. Those
        three facts together are what make `agent_post == box_post - D`. An earlier revision
        declared `box.position_pre` instead, which is only correct for a single-cell push — this
        test is what would have caught it."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        push = re.search(r"class PushSkill.*?(?=\nclass )", text, re.S)
        self.assertIsNotNone(push, "could not find PushSkill in the backend source")
        body = push.group(0)
        self.assertIn("self._expect_pos = (pos[0] + dx, pos[1] + dy)", body)
        self.assertIn("self._land       = (pos[0] + 2 * dx, pos[1] + 2 * dy)", body)
        self.assertIn('if _is_goal(self._land):', body)
        self.assertIn('return self._finish("delivered")', body)
        # and success is reached only after the agent actually advanced
        self.assertIn("if list(pos) == list(self._expect_pos):", body)

    def test_push_terminal_position_matches_the_declared_effect(self):
        """Executable check, not a source grep: replay the loop on the frozen instance and compare
        against `agent_post == box_post - D`."""
        from domain.box_push_v1 import BOX_LIGHT, GOAL_ZONE, initial_state
        box = initial_state().box(BOX_LIGHT).position
        d = (-1, 0)                                   # push_dir toward the x=1 goal column
        pos = (box[0] - d[0], box[1] - d[1])          # the pose cell, B - D
        goal = set(GOAL_ZONE)
        for _ in range(64):
            expect = (pos[0] + d[0], pos[1] + d[1])
            land = (pos[0] + 2 * d[0], pos[1] + 2 * d[1])
            pos, box = expect, land
            if land in goal:
                break
        else:
            self.fail("push loop did not reach the goal zone")
        self.assertEqual(pos, (box[0] - d[0], box[1] - d[1]), "agent_post != box_post - D")
        self.assertNotEqual(pos, initial_state().box(BOX_LIGHT).position)  # not box.position_pre
        # Join the simulation to the DECLARATION, otherwise this only asserts its own arithmetic.
        from shared.skills import SkillName
        from domain.box_push_v1 import DOMAIN_IR
        self.assertIn(
            "agent.position_post == box.position_post - D",
            DOMAIN_IR.skill(SkillName.PUSH).predicted_world_effects,
        )

    def test_cooperative_push_direction_still_comes_from_the_box_and_zone(self):
        """`CooperativePush.predicted_world_effects` declares `D == push_dir(box, zone)` and both
        terminal directions. That is only sound while the skill derives the direction from the box
        rather than from an agent's facing, and then turns the agents onto it."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        coop = re.search(r"class CooperativePushSkill.*?(?=\nclass |\ndef )", text, re.S)
        self.assertIsNotNone(coop, "could not find CooperativePushSkill in the backend source")
        body = coop.group(0)
        self.assertIn("push_dir = _push_dir_toward_goal(box)", body)
        self.assertIn("_dir_to_action(d, push_dir)", body)          # it TURNS the agents
        # Positive, so a whitespace reformat fails loudly instead of passing vacuously: the push
        # vector must be derived from `push_dir`, not from the agent's own facing.
        self.assertIn("DIRECTION_VECTORS[Directions(push_dir)]", body)

    def test_cooperative_push_terminal_slots_are_two_distinct_cells(self):
        """Both slots, and the joint translation that preserves them."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        self.assertIn("a1 = (bx - dx, by - dy)", text)
        self.assertIn("a2 = (bx - 2 * dx, by - 2 * dy)", text)
        self.assertIn("(bx - 2 * dx, by - 2 * dy)", self.multi)     # _find_tandem agrees
        # _resolve_pushes translates box AND both agents by +D, preserving the formation.
        self.assertIn("new_box = (bx + dx, by + dy)", self.multi)
        self.assertIn(
            "new_pos = {a1: (world.agents[a1].position[0] + dx, world.agents[a1].position[1] + dy)",
            self.multi,
        )

    def test_find_tandem_still_requires_both_agents_to_share_the_push_direction(self):
        """Why both declared terminal directions are the SAME `push_dir`."""
        m = re.search(r"def _find_tandem.*?(?=\n    def )", self.multi, re.S)
        self.assertIsNotNone(m, "could not find _find_tandem in the backend source")
        self.assertIn("int(world.agents[a2].direction) != d", m.group(0))

    def test_the_constructor_signatures_decision_16_translates_into_are_unchanged(self):
        """Decision 16 freezes an explicit per-skill construction. A backend rename or a reordered
        keyword would silently invalidate that translation table while every other pin stayed
        green, because nothing else reads these signatures."""
        text = SKILL_EXECUTOR.read_text(encoding="utf-8")
        for signature in (
            "def __init__(self, agent_id: str, box: Optional[Tuple[int, int]] = None):",
            "def __init__(self, agent_id: str, dest: Optional[Tuple[int, int]] = None):",
            "def __init__(self, agent_id: str, partner_id: str,",
        ):
            with self.subTest(signature=signature.split("(")[0]):
                self.assertIn(signature, text)
        # and the classes they belong to, so the pairing cannot drift
        for cls, keyword in (
            ("GotoPushPoseSkill", "box"), ("PushSkill", "dest"), ("CooperativePushSkill", "box"),
        ):
            body = re.search(rf"class {cls}.*?def step", text, re.S)
            with self.subTest(cls=cls):
                self.assertIsNotNone(body, f"could not find {cls}")
                self.assertIn(f"{keyword}: Optional[Tuple[int, int]] = None", body.group(0))

    def test_heavy_push_still_requires_the_tandem_rule(self):
        """CooperativePush being ONE executive skill (Decision 1) rests on the backend requiring
        two simultaneous MOVE_FORWARDs in one joint step."""
        self.assertIn("_find_tandem", self.multi)
        self.assertIn("required_agents > 1", self.multi)


if __name__ == "__main__":
    unittest.main()
