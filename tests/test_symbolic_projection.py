"""Symbolic projection and the monitor's comparison criterion.

This is the contract that keeps the optimism rule structurally enforceable: symbolic reasoning
consumes `SymbolicState` LITERALS, not the geometry-bearing `StateSnapshot`. A homegrown BFS over
positions cannot be written against literals, so the import guard is not the only line of defence.
"""
import ast
import inspect
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    BOX_HEAVY,
    BOX_LIGHT,
    PROJECTION,
    P_IN_POSE,
    initial_state,
    project,
)
from shared.state_snapshot import AgentSnapshot, BoxSnapshot
from shared.symbolic_state import GroundedLiteral, ProjectionContract, SymbolicState


def _delivered(state, box_id):
    b = state.box(box_id)
    return state.with_box(BoxSnapshot(b.box_id, (1, 4), b.required_agents, b.is_target, True))


class TestProjectionUsesNoGeometry(unittest.TestCase):
    """The behavioural proof that no feasibility oracle leaked into the projection."""

    def test_agent_positions_do_not_affect_the_projection(self):
        base = initial_state()
        moved = base.__class__(
            agents=tuple(
                AgentSnapshot(a.agent_id, (2, 2), 0) for a in base.agents
            ),
            boxes=base.boxes,
            static=base.static,
            episode=base.episode,
        )
        self.assertNotEqual(base.world_key(), moved.world_key())      # worlds differ...
        self.assertEqual(project(base).key(), project(moved).key())   # ...symbolically identical

    def test_box_positions_do_not_affect_the_projection(self):
        base = initial_state()
        b = base.box(BOX_LIGHT)
        shifted = base.with_box(
            BoxSnapshot(b.box_id, (3, 3), b.required_agents, b.is_target, b.delivered)
        )
        self.assertNotEqual(base.world_key(), shifted.world_key())
        self.assertEqual(project(base).key(), project(shifted).key())

    def test_delivery_status_does_affect_the_projection(self):
        """Only facts the symbolic model actually models may move the projection."""
        base = initial_state()
        self.assertNotEqual(project(base).key(), project(_delivered(base, BOX_LIGHT)).key())

    def test_projection_never_emits_in_pose(self):
        """in_pose would require the pose cell B-D, i.e. a prohibited geometry oracle."""
        for state in (initial_state(), _delivered(initial_state(), BOX_LIGHT)):
            with self.subTest():
                self.assertNotIn(
                    P_IN_POSE, {l.predicate for l in project(state).literals}
                )


class TestProjectionContract(unittest.TestCase):
    def test_in_pose_is_declared_executive_tracked_not_projectable(self):
        self.assertIn(P_IN_POSE, PROJECTION.executive_tracked)
        self.assertNotIn(P_IN_POSE, PROJECTION.projectable)
        self.assertNotIn(P_IN_POSE, PROJECTION.monitored)

    def test_projectable_and_executive_tracked_are_disjoint(self):
        self.assertEqual(PROJECTION.projectable & PROJECTION.executive_tracked, frozenset())
        with self.assertRaises(ValueError):
            ProjectionContract(projectable=frozenset({"p"}), executive_tracked=frozenset({"p"}))

    def test_every_domain_predicate_is_classified(self):
        from domain.box_push_v1 import PREDICATES
        declared = {str(p.name) for p in PREDICATES}
        self.assertEqual(declared, set(PROJECTION.declared_predicates()))

    def test_projection_emits_only_projectable_predicates(self):
        emitted = {l.predicate for l in project(initial_state()).literals}
        self.assertTrue(emitted.issubset(PROJECTION.projectable))

    def test_expected_literals_for_the_frozen_instance(self):
        literals = {l.canonical() for l in project(initial_state()).literals}
        for expected in (
            "discovered(box_0)", "discovered(box_1)",
            "pending(box_0)", "pending(box_1)",
            "heavy(box_0)", "light(box_1)",
            "different(agent_0,agent_1)", "different(agent_1,agent_0)",
        ):
            with self.subTest(literal=expected):
                self.assertIn(expected, literals)
        self.assertNotIn("delivered(box_0)", literals)


class TestMonitorCriterion(unittest.TestCase):
    """The SYMBOLIC basis of the monitor comparison (Decision 13.6).

    Not the whole criterion: the world basis compares a skill's declared deterministic world effect
    against `StateSnapshot.world_key()`. These tests pin the symbolic half only.
    """

    def test_goto_push_pose_style_move_is_not_a_symbolic_mismatch(self):
        """A successful GotoPushPose moves an agent but changes no modelled literal. Comparing
        raw worlds would raise a spurious STATE_EFFECT_MISMATCH on the happy path."""
        predicted = initial_state()                       # symbolic effect adds only in_pose
        observed = predicted.__class__(
            agents=(AgentSnapshot(AGENT_0, (9, 4), 2), predicted.agents[1]),
            boxes=predicted.boxes,
            static=predicted.static,
            episode=predicted.episode,
        )
        self.assertFalse(predicted.same_world(observed))                       # world differs
        self.assertTrue(PROJECTION.agrees(project(predicted), project(observed)))  # model agrees

    def test_a_real_effect_mismatch_is_detected(self):
        predicted = _delivered(initial_state(), BOX_LIGHT)   # model says delivered
        observed = initial_state()                           # backend says it never arrived
        self.assertFalse(PROJECTION.agrees(project(predicted), project(observed)))

    def test_difference_reports_the_mismatching_literals(self):
        predicted = project(_delivered(initial_state(), BOX_LIGHT))
        observed = project(initial_state())
        only_predicted, only_observed = predicted.difference(observed)
        self.assertIn("delivered(box_1)", only_predicted)
        self.assertIn("pending(box_1)", only_observed)


class TestSymbolicStateType(unittest.TestCase):
    def test_canonical_form_is_explicitly_sorted(self):
        """`frozenset` iteration order is stable for equal sets, so building the same state from
        two orderings proves dedup, not SERIALIZATION ordering. Assert the sort directly."""
        a = GroundedLiteral("zzz", ("x",))
        b = GroundedLiteral("aaa", ("y",))
        state = SymbolicState.of([a, b])
        self.assertEqual(state.canonical(), ("aaa(y)", "zzz(x)"))
        self.assertEqual(state.canonical(), tuple(sorted(state.canonical())))

    def test_key_is_order_independent(self):
        a = GroundedLiteral("light", ("box_1",))
        b = GroundedLiteral("pending", ("box_1",))
        self.assertEqual(SymbolicState.of([a, b]).key(), SymbolicState.of([b, a]).key())

    def test_closed_world_absent_is_false(self):
        s = SymbolicState.of([GroundedLiteral("light", ("box_1",))])
        self.assertTrue(s.holds(GroundedLiteral("light", ("box_1",))))
        self.assertFalse(s.holds(GroundedLiteral("heavy", ("box_1",))))

    def test_restriction_drops_unmonitored_predicates(self):
        s = SymbolicState.of(
            [GroundedLiteral("light", ("box_1",)), GroundedLiteral(P_IN_POSE, ("agent_0", "box_1"))]
        )
        self.assertEqual(len(PROJECTION.monitored_view(s)), 1)

    def test_literal_rejects_empty_arguments(self):
        with self.assertRaises(ValueError):
            GroundedLiteral("light", ("",))


class TestProjectionSourceReadsNoGeometry(unittest.TestCase):
    """Structural companion to the behavioural tests above.

    Mutation testing showed the behavioural proof has a blind spot: a mutant that gated a literal
    on `box.position[0] > 0` is true for every state the suite builds, so it survives. The rule the
    module docstring actually states is *`project()` must never READ a position* — so check that
    directly, on the AST.
    """

    FORBIDDEN_ATTRIBUTES = ("position", "direction", "walls", "delivery_zone", "width", "height")

    def _project_source(self):
        import domain.box_push_v1 as module
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "project":
                return node
        self.fail("could not find project() in domain.box_push_v1")

    def test_project_never_reads_a_geometric_attribute(self):
        node = self._project_source()
        used = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        for attribute in self.FORBIDDEN_ATTRIBUTES:
            with self.subTest(attribute=attribute):
                self.assertNotIn(
                    attribute, used,
                    f"project() reads `.{attribute}`; the projection feeds symbolic applicability "
                    f"and must carry no geometry (P0_V1_DECISIONS Decision 6 / 13.4)",
                )

    def test_project_reads_only_the_identity_and_status_fields(self):
        """Whitelist, so a NEW geometric field on a snapshot is caught the day it is added."""
        node = self._project_source()
        used = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        allowed = {
            "boxes", "agents", "box_id", "agent_id", "delivered", "required_agents", "value",
            "append", "of",
        }
        self.assertEqual(used - allowed, set())

    def test_project_calls_no_helper_that_could_hide_geometry(self):
        node = self._project_source()
        called = {
            n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertEqual(called - {"str", "GroundedLiteral"}, set())


if __name__ == "__main__":
    unittest.main()
