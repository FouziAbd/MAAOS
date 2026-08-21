"""P2 PDDL artifacts: regeneration equality, identifier round-trips, plan validity, and the
pyperplan cross-check (§18 item 1 / §19 D-3).

pyperplan is a LOCAL classical planner library — offline, no LM, no network. Its search order is
not guaranteed hash-stable, so the checked-in `.soln` is the DETERMINISTIC V1 planner's plan;
pyperplan is verified for existence + validity + vocabulary, never byte-equality.
"""
import pathlib
import unittest

from domain.box_push_v1 import (
    DELIVERY_ZONE,
    DOMAIN_IR,
    MODEL_VERSION,
    TASK_DELIVER_BOTH,
    initial_state,
    project,
)
from shared.ids import AgentId, BoxId
from shared.planner_result import PlanFound
from shared.skills import GroundedSkillCall, ValidatedCall
from shared.symbolic_state import GroundedLiteral
from symbolic import Universe, apply_effects, evaluate, plan
from symbolic.pddl_gen import v1_artifacts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PDDL_DIR = REPO_ROOT / "functional_layer" / "custom_env" / "box_push" / "pddl"

GOAL = frozenset(
    GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_BOTH.goal_delivered
)


def _dispatch_to_ir():
    return {ir.signature.backend_dispatch_key: ir for ir in DOMAIN_IR.skills}


def _parse_plan_line(line: str) -> GroundedSkillCall:
    """`(goto_push_pose agent_0 box_1 delivery_zone)` -> GroundedSkillCall, via the frozen
    dispatch key and `SkillIR.unbind` — the un-lift path a P2 planner integration uses."""
    tokens = line.strip().strip("()").split()
    ir = _dispatch_to_ir()[tokens[0]]
    binding = dict(zip(ir.parameters, tokens[1:]))
    return ir.unbind(binding)


def _simulate(calls) -> None:
    state = project(initial_state())
    for call in calls:
        verdict = evaluate(DOMAIN_IR, state, call)
        assert isinstance(verdict, ValidatedCall), f"{call} inapplicable mid-plan"
        state = apply_effects(state, DOMAIN_IR.skill(call.skill), call)
    for literal in GOAL:
        assert state.holds(literal), f"goal literal {literal} unsatisfied"


class TestRegeneration(unittest.TestCase):
    def test_checked_in_artifacts_equal_the_emitter_output_byte_for_byte(self):
        """§18 item 1's whole point: the IR is the source. Any drift — a hand edit, or an IR
        change without re-issue — fails here."""
        for name, content in v1_artifacts().items():
            with self.subTest(artifact=name):
                self.assertEqual(
                    (PDDL_DIR / name).read_text(encoding="utf-8"), content
                )

    def test_artifacts_carry_the_generated_banner(self):
        for name in v1_artifacts():
            with self.subTest(artifact=name):
                self.assertIn(
                    "GENERATED FROM domain/box_push_v1.py::DOMAIN_IR",
                    (PDDL_DIR / name).read_text(encoding="utf-8"),
                )

    def test_identifiers_round_trip_through_the_frozen_parsers(self):
        """The legacy artifacts' third divergence (`box0` vs `box_0`) cannot recur: every object
        in the generated problem parses through the frozen identity types."""
        problem = (PDDL_DIR / "box_push_problem_v1.pddl").read_text(encoding="utf-8")
        objects = problem[problem.index("(:objects"):problem.index("(:init")]
        for token in objects.replace("(:objects", "").split():
            if token in ("-", "agent", "box", "zone", ")"):
                continue
            with self.subTest(identifier=token):
                if token.startswith("agent"):
                    self.assertEqual(AgentId(token).value, token)
                elif token.startswith("box"):
                    self.assertEqual(str(BoxId.parse(token)), token)

    def test_action_names_are_the_frozen_dispatch_keys(self):
        domain_text = (PDDL_DIR / "box_push_domain_v1.pddl").read_text(encoding="utf-8")
        from shared.skills import REGISTRY
        symbolic_keys = {
            REGISTRY.get(name).backend_dispatch_key for name in DOMAIN_IR.action_set()
        }
        import re
        emitted = set(re.findall(r"\(:action (\w+)", domain_text))
        self.assertEqual(emitted, symbolic_keys)
        self.assertNotIn("explore", emitted)                   # Decision 5
        self.assertNotIn("wait", emitted)


class TestRecordedSolution(unittest.TestCase):
    def _solution_calls(self):
        text = (PDDL_DIR / "box_push_problem_v1.pddl.soln").read_text(encoding="utf-8")
        return [
            _parse_plan_line(line) for line in text.splitlines()
            if line.strip().startswith("(")
        ]

    def test_the_recorded_solution_is_the_deterministic_planners_plan(self):
        recorded = self._solution_calls()
        result = plan(
            DOMAIN_IR, project(initial_state()), GOAL,
            Universe.from_snapshot(initial_state(), DELIVERY_ZONE), MODEL_VERSION,
        )
        self.assertIsInstance(result, PlanFound)
        self.assertEqual([c.key() for c in recorded], [c.key() for c in result.plan])

    def test_the_recorded_solution_simulates_to_the_goal(self):
        _simulate(self._solution_calls())

    def test_the_recorded_solution_documents_its_own_optimism(self):
        """The .soln says on its face that literal execution hits the designed discrepancy —
        the acceptance suite proves that claim live."""
        text = (PDDL_DIR / "box_push_problem_v1.pddl.soln").read_text(encoding="utf-8")
        self.assertIn("OPTIMISTIC", text)
        self.assertIn("ExecutionDiscrepancy", text)


def _pyperplan_available() -> bool:
    try:
        import pyperplan  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_pyperplan_available(), "pyperplan not installed (pinned in requirements)")
class TestPyperplanCrossCheck(unittest.TestCase):
    """An independent classical planner run on the generated artifacts. Validity, not bytes."""

    def _pyperplan_plan(self):
        from pyperplan.planner import SEARCHES, search_plan
        return search_plan(
            str(PDDL_DIR / "box_push_domain_v1.pddl"),
            str(PDDL_DIR / "box_push_problem_v1.pddl"),
            SEARCHES["bfs"], None,
        )

    def test_pyperplan_finds_a_valid_plan_in_the_executive_vocabulary(self):
        ops = self._pyperplan_plan()
        self.assertIsNotNone(ops, "pyperplan found no plan on the generated artifacts")
        calls = [_parse_plan_line(op.name) for op in ops]
        for call in calls:
            self.assertIsInstance(call, GroundedSkillCall)
        _simulate(calls)

    def test_pyperplan_agrees_the_optimal_length_is_five(self):
        ops = self._pyperplan_plan()
        self.assertEqual(len(ops), 5)                          # BFS ⇒ optimal step count


if __name__ == "__main__":
    unittest.main()
