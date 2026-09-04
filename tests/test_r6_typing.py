"""R6 static typing (report Phase 6 acceptance: "the core contracts, runtime, and new policies
pass static type checking").

Two layers of evidence:

1. The mypy gate itself — `shared/`, `runtime/`, `app/`, the R1-R5 conformance witnesses
   (`tests/contract_conformance.py`) and the R5 probe fixture (`tests/probe_counter.py`) type
   check with zero errors, and the gate is NON-vacuous: a deliberate violation written to a
   scratch file is reported. Skipped (not passed) when mypy is not installed; CI installs it.
2. Runtime pins that need no type checker: the shared record channels and the loop declare
   the generic parameters R6 introduced, bounded by the structural value protocols; the
   planner-result base is abstract with an abstract `canonical`; the R5 import path for the
   value protocols still yields the same objects.
"""
import importlib.util
import inspect
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

from runtime.executive_history import ExecutiveHistory                 # noqa: E402
from runtime.loop import EpisodeResult, ExecutiveLoopManager            # noqa: E402
from runtime.policies import AdvisoryTwoTrackPolicy, SymbolicPrimaryPolicy  # noqa: E402
from shared import contracts as contracts_package                        # noqa: E402
from shared import value_contracts                                       # noqa: E402
from shared.contracts import domain_types                                # noqa: E402
from shared.discrepancy import ExecutionDiscrepancy                      # noqa: E402
from shared.execution import ExecutionResult                             # noqa: E402
from shared.planner_result import NoPlan, PlanFound, PlannerFailure, PlannerResult  # noqa: E402
from shared.skills import SymbolicallyInapplicable, UngroundedCall, ValidatedCall  # noqa: E402
from shared.trace_schema import TraceEntry                               # noqa: E402
from shared.value_contracts import AdvisoryProposal, RuntimeCall, RuntimeState, TaskContract  # noqa: E402

#: The R6 static gate, exactly as CI runs it.
MYPY_TARGETS = (
    "shared", "runtime", "app", "tests/contract_conformance.py", "tests/probe_counter.py",
)
MYPY_FLAGS = ("--ignore-missing-imports", "--follow-imports=silent")

_HAS_MYPY = importlib.util.find_spec("mypy") is not None


def _mypy(*targets: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mypy", *MYPY_FLAGS, *targets],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
    )


@unittest.skipUnless(_HAS_MYPY, "mypy is not installed (the CI job installs it)")
class TestTheStaticGate(unittest.TestCase):
    def test_the_core_witnesses_and_probe_fixture_type_check(self):
        completed = _mypy(*MYPY_TARGETS)
        self.assertEqual(
            completed.returncode, 0,
            f"mypy reported errors:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn("Success: no issues found", completed.stdout)

    def test_the_gate_reports_a_violation_of_the_generic_channels(self):
        """Non-vacuity: a V1-typed record given a foreign call, and a loop handed a task that
        is not a `TaskContract`, are both reported — the generics constrain, they do not
        merely decorate."""
        violation = (
            "from shared.execution import ExecutionResult, ExecutionOutcome, StepAccounting\n"
            "from shared.skills import GroundedSkillCall\n"
            "from shared.state_snapshot import StateSnapshot\n"
            "from domain.box_push_v1 import initial_state\n"
            "from tests.probe_counter import increment\n"
            "from app.box_push_v1 import build_loop\n"
            "from shared.backend_contract import V1Environment\n"
            "\n"
            "def bad_record(state: StateSnapshot) -> ExecutionResult[StateSnapshot, GroundedSkillCall]:\n"
            "    return ExecutionResult(call=increment('c', 1), outcome=ExecutionOutcome.SUCCESS,\n"
            "                           pre_state=state, post_state=state,\n"
            "                           accounting=StepAccounting(1, 1))\n"
            "\n"
            "def bad_task(env: V1Environment) -> None:\n"
            "    build_loop(env, 'not a task')\n"
        )
        with tempfile.TemporaryDirectory() as scratch:
            path = pathlib.Path(scratch, "r6_typing_violation.py")
            path.write_text(violation, encoding="utf-8")
            completed = _mypy(str(path))
        self.assertNotEqual(completed.returncode, 0, "the gate accepted a typed violation")
        self.assertIn('Argument "call" to "ExecutionResult"', completed.stdout)
        self.assertIn('Argument 2 to "build_loop"', completed.stdout)


class TestTheGenericsAreDeclaredAndBounded(unittest.TestCase):
    """Runtime pins of the R6 type parameters — no type checker involved."""

    def _params(self, cls):
        return {p.__name__: p.__bound__ for p in cls.__type_params__}

    def test_the_shared_record_channels_are_generic_in_the_domain_owned_types(self):
        self.assertEqual(self._params(ExecutionResult),
                         {"StateT": RuntimeState, "CallT": RuntimeCall})
        self.assertEqual(self._params(PlanFound), {"CallT": RuntimeCall})
        self.assertEqual(self._params(ExecutionDiscrepancy), {"CallT": RuntimeCall})
        self.assertEqual(self._params(TraceEntry),
                         {"StateT": RuntimeState, "CallT": RuntimeCall, "TaskT": TaskContract})
        for verdict in (ValidatedCall, UngroundedCall, SymbolicallyInapplicable):
            with self.subTest(verdict=verdict.__name__):
                self.assertEqual(self._params(verdict), {"CallT": None})   # held, never read

    def test_the_runtime_is_generic_in_the_five_domain_owned_types(self):
        self.assertEqual(
            self._params(ExecutiveLoopManager),
            {"StateT": RuntimeState, "SymbolicStateT": None, "CallT": RuntimeCall,
             "TaskT": TaskContract, "ProposalT": AdvisoryProposal},
        )
        self.assertEqual(self._params(ExecutiveHistory),
                         {"StateT": RuntimeState, "CallT": RuntimeCall, "TaskT": TaskContract})
        self.assertEqual(self._params(EpisodeResult),
                         {"StateT": RuntimeState, "CallT": RuntimeCall, "TaskT": TaskContract})
        for policy in (SymbolicPrimaryPolicy, AdvisoryTwoTrackPolicy):
            with self.subTest(policy=policy.__name__):
                self.assertEqual(list(self._params(policy)), ["StateT", "CallT", "ProposalT"])

    def test_the_generic_records_stay_frozen_slotted_dataclasses(self):
        """Adding type parameters must not have cost the records their value semantics."""
        for record in (ExecutionResult, PlanFound, ExecutionDiscrepancy, TraceEntry,
                       ValidatedCall, UngroundedCall, SymbolicallyInapplicable):
            with self.subTest(record=record.__name__):
                self.assertTrue(record.__dataclass_params__.frozen)
                self.assertTrue(hasattr(record, "__slots__"))
                self.assertTrue(hasattr(record, "__class_getitem__"))    # subscriptable

    def test_planner_result_base_is_abstract_and_every_result_serializes(self):
        self.assertTrue(inspect.isabstract(PlannerResult))
        with self.assertRaises(TypeError):
            PlannerResult()
        for concrete in (PlanFound, NoPlan, PlannerFailure):
            with self.subTest(result=concrete.__name__):
                self.assertFalse(inspect.isabstract(concrete))
                self.assertIn("canonical", vars(concrete))
        self.assertEqual(NoPlan("r").canonical()["result"], "NoPlan")

    def test_the_value_protocols_keep_their_r5_import_path_and_identity(self):
        for name in ("RuntimeState", "RuntimeCall", "TaskContract", "AdvisoryProposal"):
            with self.subTest(protocol=name):
                leaf = getattr(value_contracts, name)
                self.assertIs(getattr(domain_types, name), leaf)
                self.assertIs(getattr(contracts_package, name), leaf)
                self.assertTrue(getattr(leaf, "_is_protocol", False))

    def test_the_leaf_module_imports_nothing_above_the_records(self):
        """The bounds live below the records they bound: the leaf may import only stdlib and
        the two key/report modules, never `shared.contracts`, `shared.execution`, or the
        frozen V1 value types (that would recreate the cycle the leaf exists to break)."""
        import ast
        source = pathlib.Path(value_contracts.__file__).read_text(encoding="utf-8")
        roots = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                roots |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module)
        self.assertEqual(
            {r for r in roots if r.startswith("shared")},
            {"shared.comparison_keys", "shared.reports"},
        )


if __name__ == "__main__":
    unittest.main()
