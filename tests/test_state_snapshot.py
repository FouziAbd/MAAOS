"""StateSnapshot normalization/serialization contract (supervisor :86-:88)."""
import unittest

from domain.box_push_v1 import BOX_HEAVY, BOX_LIGHT, initial_state
from shared.ids import AgentId, BoxId
from shared.state_snapshot import (
    AgentSnapshot,
    BoxSnapshot,
    EpisodeSnapshot,
    StateSnapshot,
    StaticWorld,
)


def _static():
    return StaticWorld(width=4, height=4, walls=((0, 0), (1, 0)), delivery_zone=((1, 1),))


def _snapshot(*, step_count=0, agent_order=("a", "b")):
    agents = {
        "a": AgentSnapshot(AgentId("agent_0"), (2, 2), 2),
        "b": AgentSnapshot(AgentId("agent_1"), (3, 3), 1),
    }
    return StateSnapshot(
        agents=tuple(agents[k] for k in agent_order),
        boxes=(BoxSnapshot(BoxId(0), (1, 2), 2, True, False),),
        static=_static(),
        episode=EpisodeSnapshot(step_count=step_count),
    )


class TestNormalization(unittest.TestCase):
    def test_agent_order_does_not_affect_canonical_form(self):
        """Construction order must not change the canonical form or the key."""
        a = _snapshot(agent_order=("a", "b"))
        b = _snapshot(agent_order=("b", "a"))
        self.assertEqual(a.world_json(), b.world_json())
        self.assertEqual(a.world_key(), b.world_key())
        self.assertTrue(a.same_world(b))

    def test_static_world_sorts_cells(self):
        s1 = StaticWorld(4, 4, walls=((1, 0), (0, 0)), delivery_zone=((1, 1),))
        s2 = StaticWorld(4, 4, walls=((0, 0), (1, 0)), delivery_zone=((1, 1),))
        self.assertEqual(s1.canonical(), s2.canonical())

    def test_serialization_is_deterministic_across_calls(self):
        s = _snapshot()
        self.assertEqual(s.world_json(), s.world_json())
        self.assertEqual(s.world_key(), s.world_key())

    def test_duplicate_ids_rejected(self):
        dup = AgentSnapshot(AgentId("agent_0"), (1, 1), 0)
        with self.assertRaises(ValueError):
            StateSnapshot(agents=(dup, dup), boxes=(), static=_static())

    def test_invalid_direction_rejected(self):
        with self.assertRaises(ValueError):
            AgentSnapshot(AgentId("agent_0"), (1, 1), 4)

    def test_non_integer_cell_rejected(self):
        with self.assertRaises(ValueError):
            AgentSnapshot(AgentId("agent_0"), (1.5, 1), 0)


class TestComparisonContract(unittest.TestCase):
    """Episode bookkeeping must be excluded from the comparison key.

    The predictor predicts a successor world, not the number of primitive steps the backend
    needed. Including step_count would make every predicted-vs-observed comparison mismatch.
    """

    def test_step_count_excluded_from_world_key(self):
        a = _snapshot(step_count=0)
        b = _snapshot(step_count=37)
        self.assertEqual(a.world_key(), b.world_key())
        self.assertTrue(a.same_world(b))

    def test_step_count_included_in_replay_key(self):
        a = _snapshot(step_count=0)
        b = _snapshot(step_count=37)
        self.assertNotEqual(a.replay_key(), b.replay_key())

    def test_world_change_is_detected(self):
        a = initial_state()
        moved = a.box(BOX_LIGHT)
        b = a.with_box(
            BoxSnapshot(moved.box_id, (1, 4), moved.required_agents, moved.is_target, True)
        )
        self.assertFalse(a.same_world(b))
        self.assertNotEqual(a.world_key(), b.world_key())


class TestRoundTrip(unittest.TestCase):
    def test_round_trip_preserves_world_and_episode(self):
        original = _snapshot(step_count=5)
        restored = StateSnapshot.from_dict(original.to_dict())
        self.assertEqual(original.world_key(), restored.world_key())
        self.assertEqual(original.replay_key(), restored.replay_key())
        self.assertEqual(original.episode.step_count, restored.episode.step_count)

    def test_round_trip_of_frozen_instance(self):
        original = initial_state()
        restored = StateSnapshot.from_dict(original.to_dict())
        self.assertEqual(original.replay_json(), restored.replay_json())

    def test_round_trip_preserves_identities(self):
        restored = StateSnapshot.from_dict(initial_state().to_dict())
        self.assertTrue(restored.has_box(BOX_LIGHT))
        self.assertEqual(restored.box(BOX_LIGHT).required_agents, 1)


class TestGoalHelpers(unittest.TestCase):
    def test_all_targets_delivered_false_initially(self):
        self.assertFalse(initial_state().all_targets_delivered)

    def test_all_targets_delivered_true_when_all_delivered(self):
        s = initial_state()
        for b in s.boxes:
            s = s.with_box(BoxSnapshot(b.box_id, b.position, b.required_agents, b.is_target, True))
        self.assertTrue(s.all_targets_delivered)

    def test_unknown_lookup_raises(self):
        with self.assertRaises(KeyError):
            initial_state().box(BoxId(99))


class TestModuleDocstringStatesTheCorrectMonitorRole(unittest.TestCase):
    """`shared/state_snapshot.py` carried a stale "the monitor does NOT compare StateSnapshots …
    it compares PROJECTED symbolic state" claim through the Decision 13 change — in the very module
    Decision 13.1 names as the canonical-state authority. Nothing caught it, because docstrings are
    not executed. Pin it: this file's description of its own role is part of the contract."""

    def _doc(self):
        import shared.state_snapshot as module
        return module.__doc__ or ""

    def test_it_does_not_claim_the_monitor_ignores_world_state(self):
        doc = self._doc()
        for retired in (
            "The monitor does NOT compare",
            "The monitor compares PROJECTED",
            "NOT the monitor's criterion",       # the retired section HEADING, too
        ):
            with self.subTest(claim=retired):
                self.assertNotIn(retired, doc)

    def test_it_names_both_comparison_bases(self):
        doc = self._doc().lower()
        for required in ("world basis", "symbolic basis", "decision 13"):
            with self.subTest(term=required):
                self.assertIn(required, doc)


class TestFieldsTheKeyAndTerminalPredicateMustHonour(unittest.TestCase):
    """Each test here changes exactly ONE field and holds everything else fixed.

    Mutation testing showed why that matters: every existing `delivered` test also MOVED the box in
    the same `BoxSnapshot`, so the position change alone accounted for the key difference and
    dropping `delivered` from `canonical()` survived the whole suite.
    """

    def _flip(self, state, box_id, **changes):
        b = state.box(box_id)
        fields = {
            "position": b.position, "required_agents": b.required_agents,
            "is_target": b.is_target, "delivered": b.delivered,
        }
        fields.update(changes)
        return state.with_box(BoxSnapshot(b.box_id, **fields))

    def test_delivered_alone_changes_the_world_key(self):
        """FAIL-2. If it did not, `FailureStateClass.UNCHANGED` would accept 'no-op' for an attempt
        that delivered the box, and repeated-failure bookkeeping would bucket the two together."""
        s = initial_state()
        moved_nothing = self._flip(s, BOX_LIGHT, delivered=True)
        self.assertEqual(moved_nothing.box(BOX_LIGHT).position, s.box(BOX_LIGHT).position)
        self.assertNotEqual(moved_nothing.world_key(), s.world_key())
        self.assertFalse(s.same_world(moved_nothing))
        self.assertNotEqual(moved_nothing, s)

    def test_is_target_alone_changes_the_world_key(self):
        s = initial_state()
        self.assertNotEqual(self._flip(s, BOX_LIGHT, is_target=False).world_key(), s.world_key())

    def test_required_agents_alone_changes_the_world_key(self):
        s = initial_state()
        self.assertNotEqual(self._flip(s, BOX_LIGHT, required_agents=2).world_key(), s.world_key())

    def test_agent_direction_alone_changes_the_world_key(self):
        """`CooperativePush` declares both agents' terminal DIRECTIONS as real world effects, so if
        `direction` ever left `world_key()` the world basis could not detect a wrong facing — and
        a turn-only failure would be misclassified `UNCHANGED`."""
        s = initial_state()
        a = s.agents[0]
        turned = type(s)(
            agents=(AgentSnapshot(a.agent_id, a.position, (a.direction + 1) % 4),) + s.agents[1:],
            boxes=s.boxes, static=s.static, episode=s.episode,
        )
        self.assertEqual(turned.agents[0].position, a.position)
        self.assertNotEqual(turned.world_key(), s.world_key())
        self.assertFalse(s.same_world(turned))

    def test_agent_position_alone_changes_the_world_key(self):
        s = initial_state()
        a = s.agents[0]
        moved = type(s)(
            agents=(AgentSnapshot(a.agent_id, (3, 3), a.direction),) + s.agents[1:],
            boxes=s.boxes, static=s.static, episode=s.episode,
        )
        self.assertEqual(moved.agents[0].direction, a.direction)
        self.assertNotEqual(moved.world_key(), s.world_key())

    def test_all_targets_delivered_is_conjunctive_not_disjunctive(self):
        """FAIL-3. Only 0-of-2 and 2-of-2 were covered, so `all(...)` -> `any(...)` survived and an
        episode would terminate after the first box."""
        s = initial_state()
        self.assertFalse(s.all_targets_delivered)
        one = self._flip(s, BOX_LIGHT, delivered=True)
        self.assertFalse(one.all_targets_delivered, "terminated with one of two targets delivered")
        both = self._flip(one, BOX_HEAVY, delivered=True)
        self.assertTrue(both.all_targets_delivered)

    def test_a_non_target_box_does_not_gate_termination(self):
        s = initial_state()
        s = self._flip(s, BOX_LIGHT, delivered=True)
        s = self._flip(s, BOX_HEAVY, is_target=False)
        self.assertTrue(s.all_targets_delivered)

    def test_duplicate_box_ids_are_refused(self):
        """WARN-3: the duplicate-AgentId branch was covered, the BoxId branch was not."""
        s = initial_state()
        with self.assertRaises(ValueError):
            type(s)(agents=s.agents, boxes=s.boxes + (s.boxes[0],), static=s.static,
                    episode=s.episode)


if __name__ == "__main__":
    unittest.main()
