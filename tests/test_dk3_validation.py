"""DK3 — `validate-domain` and the `maaos` CLI.

What this module pins:

  1. The frozen domain passes: `validate_named("box_push", REGISTRY)` has no FAIL, every
     catalogued check appears, the SKIPPED set is exactly the optional advisory checks, and
     the report renders without any runtime-internal text.
  2. Deliberately broken packages — built from the DK2 kit domain by swapping ONE component —
     yield exactly their check codes as FAIL (the whole FAIL set is pinned, so a cascade
     cannot appear or vanish unnoticed), with an author-facing headline (contract member,
     file, no "Traceback", no runtime path) and the raw evidence under details; every
     catalogue code still appears in every report (blocked checks are SKIPPED, never absent).
  3. Registry resolution: DK001 quotes the exact two lines to add; DK002 for a non-package
     value and for a key/name mismatch.
  4. The layout checks (DK080/DK081/DK082) on probe trees, and — the parity proof — the
     validator's mirror of the guard: its constants EQUAL the guard's, and on a table of
     probe trees `check_layout` fails exactly when `tests/test_no_backend_imports.py`'s
     scanners would (including `__init__.py` importing a backend, a never-exempt root in
     `environment.py` with a door line, guard-only roots, and a commented-out door line).
  5. The CLI: `list-domains`, exit codes 0/1/2, `--budget` reaching the episodes, no dynamic
     import in `maaos/`, subprocess smoke through `python -m maaos`.

Offline and deterministic.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.domain_package import DomainExamples, DomainPackage               # noqa: E402
from app.validation import (                                             # noqa: E402
    BACKEND_ROOTS,
    CATALOGUE,
    CLI_CODES,
    DYNAMIC_ROOTS,
    NEVER_EXEMPT_ROOTS,
    Finding,
    Status,
    ValidationReport,
    check_layout,
    check_lazy_backend,
    lookup,
    registry_line,
    validate_domain,
    validate_named,
)
from domains.registry import REGISTRY                                    # noqa: E402
from kit import DefaultProposalComparator, DerivedDomainServices, ProjectionTrack  # noqa: E402
from maaos.cli import main                                               # noqa: E402
from shared.planner_result import NoPlan, PlanFound                      # noqa: E402
from shared.reports import ConfidenceReport, CoverageReport              # noqa: E402
from shared.skills import SymbolicallyInapplicable                       # noqa: E402
from shared.versioning import ModelVersion                               # noqa: E402
from tests import probe_counter as probe                                 # noqa: E402
from tests.test_dk2_kit import (                                         # noqa: E402
    COUNTER,
    INITIAL,
    KEnv,
    KModel,
    apply_world,
    halt,
    inc,
    kit_package,
)
from tests.test_no_backend_imports import (                              # noqa: E402
    DOMAIN_ENVIRONMENT_MODULES,
    FORBIDDEN_DYNAMIC,
    FORBIDDEN_PREFIXES,
    NEVER_EXEMPT_ROOTS as GUARD_NEVER_EXEMPT,
    backend_violations,
    domain_role_violations,
    imported_modules,
)

ALL_CODES = {code for code, _ in CATALOGUE}
LIBRARY_CODES = ALL_CODES - CLI_CODES
_INTERNAL = re.compile(r"Traceback|File \"|\b(runtime|app|shared|kit)/\w+\.py|ExecutiveLoopManager")


def _codes(report: ValidationReport, status: Status) -> set[str]:
    return {f.code for f in report.findings if f.status is status}


def _assert_author_facing(test: unittest.TestCase, finding: Finding) -> None:
    test.assertIs(finding.status, Status.FAIL)
    test.assertTrue(finding.message)
    test.assertNotRegex(finding.message, _INTERNAL)


def _assert_complete(test: unittest.TestCase, report: ValidationReport, codes=LIBRARY_CODES) -> None:
    """Every catalogue code appears (blocked checks are SKIPPED, never absent)."""
    test.assertEqual({f.code for f in report.findings}, codes, report.render())


# ═══ 1. the frozen domain passes ═══════════════════════════════════════════════════════

class TestBoxPushValidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = validate_named("box_push", REGISTRY)

    def test_no_fail_no_warn_and_only_the_optional_checks_skip(self):
        self.assertTrue(self.report.ok, self.report.render())
        self.assertEqual(_codes(self.report, Status.FAIL), set())
        self.assertEqual(_codes(self.report, Status.WARN), set())
        self.assertEqual(_codes(self.report, Status.SKIPPED), {"DK017", "DK071"})

    def test_every_catalogued_check_appears_in_catalogue_order(self):
        _assert_complete(self, self.report, ALL_CODES)
        codes = [f.code for f in self.report.findings]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(codes.count("DK070"), 2)

    def test_the_report_renders_without_runtime_internals(self):
        text = self.report.render()
        self.assertIn("validate-domain box_push", text)
        self.assertIn("Result: 28 PASS, 0 WARN, 0 FAIL, 2 SKIPPED", text)
        self.assertNotRegex(text, _INTERNAL)

    def test_both_bounded_episodes_ran_and_reached_the_accepted_outcomes(self):
        episodes = [f for f in self.report.findings if f.code == "DK070"]
        self.assertEqual([f.status for f in episodes], [Status.PASS, Status.PASS])
        self.assertIn("halted_repeated_failure", episodes[0].details)
        self.assertIn("a typed halt is a valid outcome", episodes[0].details)
        self.assertIn("goal_reached", episodes[1].details)

    def test_the_door_is_enumerated_and_the_package_imports_lazily(self):
        self.assertIs(self.report.by_code("DK081").status, Status.PASS)
        self.assertIs(self.report.by_code("DK082").status, Status.PASS)


# ═══ 2. broken packages name their check, in the author's terms ════════════════════════

def _services(model, world=apply_world):
    return lambda task: DerivedDomainServices(model, apply_world=world)


class TestBrokenPackagesAreReportedByCode(unittest.TestCase):
    def _run(self, package: DomainPackage) -> ValidationReport:
        report = validate_domain(package, executive_budget=20)
        _assert_complete(self, report)
        return report

    def _fails(self, package: DomainPackage, expected: set[str]) -> ValidationReport:
        report = self._run(package)
        self.assertEqual(_codes(report, Status.FAIL), expected, report.render())
        for code in expected:
            _assert_author_facing(self, report.by_code(code))
        return report

    def test_the_kit_domain_passes_as_a_control_with_exact_sets(self):
        report = self._run(kit_package())
        self.assertTrue(report.ok, report.render())
        self.assertEqual(_codes(report, Status.WARN), {"DK043", "DK052"})   # no examples declared
        self.assertEqual(_codes(report, Status.SKIPPED), {"DK017", "DK071"})
        self.assertIn("examples=DomainExamples(", report.by_code("DK043").message)

    def test_services_missing_a_member_blocks_the_dependents_as_skipped(self):
        class NoPredict:
            def __init__(self, inner):
                self._inner = inner
                for name in ("plan", "ground", "evaluate", "monitor"):
                    setattr(self, name, getattr(inner, name))

            @property
            def model_version(self):
                return self._inner.model_version

        base = kit_package()
        broken = dataclasses.replace(base, services=lambda task: NoPredict(base.services(task)))
        report = self._fails(broken, {"DK010"})
        finding = report.by_code("DK010")
        self.assertIn("predict", finding.message)
        self.assertIn("define them on the class", finding.message)
        self.assertIn("fix DK010 first", report.by_code("DK070").message)
        self.assertIs(report.by_code("DK040").status, Status.SKIPPED)

    def test_observe_that_aliases_the_state(self):
        class Aliasing(KEnv):
            def observe(self):
                return self._require()       # returns the authoritative object itself

        broken = dataclasses.replace(kit_package(), environment=lambda: Aliasing(INITIAL))
        report = self._fails(broken, {"DK031"})
        self.assertIn("copy", report.by_code("DK031").message)

    def test_no_refusal_before_reset(self):
        class Lenient(KEnv):
            def execute_skill(self, call, /):
                if self._state is None:
                    self._state = self._reset(None)
                return super().execute_skill(call)

        broken = dataclasses.replace(kit_package(), environment=lambda: Lenient(INITIAL))
        report = self._fails(broken, {"DK032"})
        self.assertIn("refused:", report.by_code("DK032").message)

    def test_a_monitor_that_raises_faults_the_episode_and_names_the_component(self):
        class BrokenModel(KModel):
            def project(self, state, /):
                if state.value > 0:          # fine on the initial state, breaks after a step
                    raise KeyError("author bug in project()")
                return super().project(state)

        broken = dataclasses.replace(kit_package(), services=_services(BrokenModel(COUNTER)))
        report = self._fails(broken, {"DK070"})
        failed = report.by_code("DK070")
        self.assertIn("FAULTED", failed.message)
        self.assertIn("author bug in project()", failed.message)
        self.assertIn("BrokenModel", failed.message)

    def test_a_property_where_a_method_is_expected_is_caught_statically(self):
        class Vanishing(ProjectionTrack):
            @property
            def record_outcome(self):
                raise AttributeError("record_outcome")

        model = KModel(COUNTER)
        broken = dataclasses.replace(kit_package(), symbolic_track=lambda: Vanishing(model.project))
        report = self._fails(broken, {"DK011"})
        self.assertIn("record_outcome must be a METHOD", report.by_code("DK011").message)

    def test_a_member_that_raises_attribute_error_at_runtime_is_named_with_its_protocol(self):
        class Forgetful(ProjectionTrack):
            def record_outcome(self, result, /):
                raise AttributeError("record_outcome")     # e.g. a missing internal attribute

        model = KModel(COUNTER)
        broken = dataclasses.replace(kit_package(), symbolic_track=lambda: Forgetful(model.project))
        report = self._fails(broken, {"DK070"})
        self.assertIn("record_outcome is a SymbolicTrack member", report.by_code("DK070").message)

    def test_plan_returning_the_wrong_type(self):
        class BadPlan(KModel):
            def plan(self, sym, identities, /):
                return [inc(COUNTER)]        # a bare list, not a PlannerResult

        report = self._fails(dataclasses.replace(kit_package(), services=_services(BadPlan(COUNTER))),
                             {"DK040"})
        self.assertIn("PlanFound / NoPlan / PlannerFailure", report.by_code("DK040").message)
        self.assertIn("list", report.by_code("DK040").details)
        self.assertIs(report.by_code("DK041").status, Status.SKIPPED)

    def test_noplan_on_the_initial_state_is_a_warn_not_a_fail(self):
        class Stuck(KModel):
            def plan(self, sym, identities, /):
                return NoPlan(reason="nothing applies", model_version=self.model_version)

        report = self._run(dataclasses.replace(kit_package(), services=_services(Stuck(COUNTER))))
        self.assertIn("DK041", _codes(report, Status.WARN))
        self.assertIn("nothing applies", report.by_code("DK041").message)

    def test_a_head_the_model_calls_inapplicable(self):
        class Contradictory(KModel):
            def applicable(self, sym, call, /):
                return SymbolicallyInapplicable(reason="never", call=call)

        report = self._fails(dataclasses.replace(kit_package(), services=_services(Contradictory(COUNTER))),
                             {"DK051"})
        self.assertIn("fix DK051 first", report.by_code("DK070").message)
        self.assertIn("plan() and applicable() disagree", report.by_code("DK051").message)

    def test_model_versions_must_agree(self):
        other = ModelVersion(revision=9, label="other")

        class Mismatched(KModel):
            def plan(self, sym, identities, /):
                result = super().plan(sym, identities)
                return dataclasses.replace(result, model_version=other) if isinstance(result, PlanFound) else result

        report = self._fails(dataclasses.replace(kit_package(), services=_services(Mismatched(COUNTER))),
                             {"DK090"})
        self.assertIn("same ModelVersion", report.by_code("DK090").message)

    def test_a_field_shadowing_a_contract_method_is_dk016_not_a_runtime_type_error(self):
        @dataclasses.dataclass(frozen=True, slots=True)
        class Shadowing:
            op: str
            counter_id: str
            key: str = "k"                    # shadows Call.key() — the runtime calls it

            @property
            def skill(self):
                return self.op

            @property
            def cost(self):
                return 1

            def canonical(self):
                return {"op": self.op, "counter": self.counter_id}

            def identities(self):
                return frozenset({self.counter_id})

        class ShadowPlan(KModel):
            def plan(self, sym, identities, /):
                return PlanFound(plan=(Shadowing("Increment", COUNTER),), model_version=self.model_version)

        report = self._fails(dataclasses.replace(kit_package(), services=_services(ShadowPlan(COUNTER))),
                             {"DK016"})
        self.assertIn("key must be a METHOD", report.by_code("DK016").message)
        self.assertIs(report.by_code("DK070").status, Status.SKIPPED)

    def test_a_call_type_with_identity_equality_is_dk018(self):
        class Unequal:
            def __init__(self, inner):
                self._inner = inner
            skill = property(lambda self: self._inner.skill)
            cost = property(lambda self: self._inner.cost)
            key = lambda self: self._inner.key()               # noqa: E731
            canonical = lambda self: self._inner.canonical()   # noqa: E731
            identities = lambda self: self._inner.identities() # noqa: E731

        class Wrapping(KModel):
            def plan(self, sym, identities, /):
                result = super().plan(sym, identities)
                return PlanFound(plan=tuple(Unequal(c) for c in result.plan), model_version=result.model_version)

        report = self._fails(dataclasses.replace(kit_package(), services=_services(Wrapping(COUNTER))),
                             {"DK018"})
        self.assertIn("frozen dataclass", report.by_code("DK018").message)
        self.assertIs(report.by_code("DK041").status, Status.SKIPPED)

    def test_a_wrong_ungrounded_example(self):
        broken = dataclasses.replace(kit_package(), examples=DomainExamples(ungrounded_call=inc(COUNTER)))
        report = self._fails(broken, {"DK043"})
        self.assertIn("examples.ungrounded_call", report.by_code("DK043").message)

    def test_inapplicable_examples(self):
        good = dataclasses.replace(kit_package(), examples=DomainExamples(inapplicable_call=halt(COUNTER)))
        self.assertIs(self._run(good).by_code("DK052").status, Status.PASS)
        wrong = dataclasses.replace(kit_package(), examples=DomainExamples(inapplicable_call=inc(COUNTER)))
        report = self._fails(wrong, {"DK052"})
        self.assertIn("SymbolicallyInapplicable", report.by_code("DK052").message)

    def test_no_recovery_provider_is_a_warn_with_guidance_under_advisory_only(self):
        report = self._run(dataclasses.replace(kit_package(), recovery_provider=None))
        self.assertTrue(report.ok)
        episodes = [f for f in report.findings if f.code == "DK070"]
        self.assertEqual([f.status for f in episodes], [Status.PASS, Status.WARN])
        self.assertIn("recovery_provider", episodes[1].message)

    def test_a_declared_reasoning_track_runs_the_advisory_episode(self):
        class KitEcho(probe.FakeReasoningTrack):
            def propose(self, task, /):
                p = super().propose(task)
                call = None if p.call is None else (
                    inc(p.call.counter_id, p.call.amount) if p.call.op is probe.CounterOp.INCREMENT
                    else halt(p.call.counter_id))
                return dataclasses.replace(p, call=call)

        declared = dataclasses.replace(kit_package(), reasoning_track=KitEcho)
        report = self._run(declared)
        self.assertTrue(report.ok, report.render())
        self.assertIs(report.by_code("DK017").status, Status.PASS)
        self.assertIs(report.by_code("DK071").status, Status.PASS)
        self.assertIn("with the reasoning track", report.by_code("DK071").details)
        # a comparator missing `compare` with a track declared is DK012
        class NoCompare:
            pass
        broken = dataclasses.replace(declared, comparator=NoCompare)
        report = self._fails(broken, {"DK012"})
        self.assertIn("compare", report.by_code("DK012").message)

    def test_an_exception_inside_one_check_does_not_hide_the_others(self):
        class Exploding(KEnv):
            def reset(self, *, seed=None):
                raise RuntimeError("reset exploded")

        report = self._run(dataclasses.replace(kit_package(), environment=lambda: Exploding(INITIAL)))
        finding = report.by_code("DK030")
        _assert_author_facing(self, finding)
        self.assertIn("reset exploded", finding.details)
        self.assertIs(report.by_code("DK010").status, Status.PASS)
        self.assertIs(report.by_code("DK040").status, Status.SKIPPED)


# ═══ 3. registry resolution ═════════════════════════════════════════════════════════════

class TestRegistryLookup(unittest.TestCase):
    def test_unregistered_name_quotes_the_exact_lines(self):
        package, findings = lookup("warehouse", REGISTRY)
        self.assertIsNone(package)
        (finding,) = findings
        self.assertEqual((finding.code, finding.status), ("DK001", Status.FAIL))
        import_line, entry = registry_line("warehouse")
        self.assertIn(import_line, finding.message)
        self.assertIn(entry.strip(), finding.message)
        self.assertIn("domains/registry.py", finding.message)
        self.assertIn("create-domain warehouse", finding.message)

    def test_a_non_package_value_is_dk002(self):
        package, findings = lookup("x", {"x": object()})      # type: ignore[dict-item]
        self.assertIsNone(package)
        self.assertEqual([(f.code, f.status) for f in findings], [("DK001", Status.PASS), ("DK002", Status.FAIL)])

    def test_a_key_name_mismatch_is_dk002(self):
        package, findings = lookup("other", {"other": kit_package()})
        self.assertIsNotNone(package)
        self.assertEqual([(f.code, f.status) for f in findings], [("DK001", Status.PASS), ("DK002", Status.FAIL)])
        self.assertIn("kit_built", findings[1].message)

    def test_validate_named_stops_at_the_registry_when_unregistered(self):
        report = validate_named("nope", REGISTRY)
        self.assertEqual([f.code for f in report.findings], ["DK001"])
        self.assertFalse(report.ok)


# ═══ 4. the layout checks and the guard-parity proof ═══════════════════════════════════

_CLEAN = {
    "__init__.py": "from app.domain_package import DomainPackage\nfrom .environment import make\nfrom .model import services\n",
    "types.py": "import dataclasses\nfrom shared.contracts import RuntimeState\n",
    "model.py": "from .types import State\nimport kit\n",
    "environment.py": "from .types import State\n",
}


def _tree(stack, files, *, door_listed=False, door_commented=False):
    root = pathlib.Path(stack.enter_context(tempfile.TemporaryDirectory()))
    for existing in ("shared", "runtime", "app", "kit"):
        (root / existing).mkdir()
        (root / existing / "__init__.py").write_text("", encoding="utf-8")
    pkg = root / "domains" / "lamp"
    pkg.mkdir(parents=True)
    (root / "domains" / "__init__.py").write_text("", encoding="utf-8")
    contents = dict(_CLEAN)
    contents.update(files)
    for name, body in contents.items():
        (pkg / name).write_text(body, encoding="utf-8")
    guard = root / "tests"
    guard.mkdir()
    line = '    "domains/lamp/environment.py",\n'
    (guard / "test_no_backend_imports.py").write_text(
        "DOMAIN_ENVIRONMENT_MODULES = frozenset({\n"
        + (line if door_listed else ("#" + line if door_commented else ""))
        + "})\n", encoding="utf-8")
    return root


class TestLayoutCheck(unittest.TestCase):
    def _run(self, files, **kw):
        with contextlib.ExitStack() as stack:
            return check_layout("lamp", repo_root=_tree(stack, files, **kw))

    def test_a_clean_package_passes_and_needs_no_door(self):
        findings = self._run({})
        self.assertEqual([(f.code, f.status) for f in findings], [("DK080", Status.PASS), ("DK081", Status.PASS)])
        self.assertIn("no guard line needed", findings[1].details)

    def test_missing_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = check_layout("ghost", repo_root=pathlib.Path(tmp))
        self.assertEqual([f.status for f in findings], [Status.SKIPPED, Status.SKIPPED])

    def test_symbolic_side_violations_are_explained_in_the_headline(self):
        for body, phrase in (
            ("from .environment import make\n", "no feasibility oracle"),
            ("import runtime.executive_history\n", "only __init__.py may import"),
            ("from app.assembly import assemble_loop\n", "only __init__.py may import"),
            ("import numpy\n", "environment.py only"),
            ("from . import DOMAIN\n", "never the package"),
            ("from domains.other import x\n", "another domain"),
            ("import symbolic\n", "standard library, shared, kit and sibling"),
            ("import importlib\n", "dynamic imports are forbidden"),
        ):
            with self.subTest(body=body):
                (finding, _door) = self._run({"model.py": body})
                self.assertIs(finding.status, Status.FAIL, body)
                self.assertIn(phrase, finding.message)
                self.assertIn("Module roles", finding.message)

    def test_environment_and_init_violations(self):
        (finding, _) = self._run({"environment.py": "from .model import services\n"})
        self.assertIn("backend boundary", finding.message)
        (finding, _) = self._run({"environment.py": "import runtime\n"})
        self.assertIs(finding.status, Status.FAIL)
        (finding, _) = self._run({"__init__.py": _CLEAN["__init__.py"] + "import numpy\n"})
        self.assertIs(finding.status, Status.FAIL)
        self.assertIn("composition module wires components", finding.message)

    def test_a_backend_door_needs_the_guard_line_parsed_not_grepped(self):
        findings = self._run({"environment.py": "import numpy\n"})
        self.assertEqual([(f.code, f.status) for f in findings], [("DK080", Status.PASS), ("DK081", Status.FAIL)])
        self.assertIn('"domains/lamp/environment.py"', findings[1].message)
        self.assertIn("needs no line under tests/ at all", findings[1].message)
        listed = self._run({"environment.py": "import numpy\n"}, door_listed=True)
        self.assertEqual([f.status for f in listed], [Status.PASS, Status.PASS])
        commented = self._run({"environment.py": "import numpy\n"}, door_commented=True)
        self.assertEqual([f.status for f in commented], [Status.PASS, Status.FAIL])

    def test_an_lm_framework_in_the_door_can_never_be_exempted(self):
        for root in ("dspy", "torch", "legacy"):
            with self.subTest(root=root):
                (finding, door) = self._run({"environment.py": f"import {root}\n"}, door_listed=True)
                self.assertIs(finding.status, Status.FAIL)
                self.assertIn("never an LM binding", finding.message)
                self.assertIs(door.status, Status.PASS)          # no door is requested for it

    def test_the_real_boxpush_package_layout_passes(self):
        findings = check_layout("box_push")
        self.assertEqual([(f.code, f.status) for f in findings], [("DK080", Status.PASS), ("DK081", Status.PASS)])


class TestValidatorMirrorsTheGuard(unittest.TestCase):
    """The parity proof: the validator's rules are a mirror of the authority."""

    def test_the_mirrored_constants_equal_the_guards(self):
        self.assertEqual(BACKEND_ROOTS, FORBIDDEN_PREFIXES)
        self.assertEqual(NEVER_EXEMPT_ROOTS, GUARD_NEVER_EXEMPT)
        self.assertEqual(DYNAMIC_ROOTS, FORBIDDEN_DYNAMIC)
        # the door set is pinned against the registry (backend-wrapping domains only) in
        # tests/test_dk1_domain_package.py; here: every listed door is a registered domain
        self.assertTrue(all(d.split("/")[1] in REGISTRY for d in DOMAIN_ENVIRONMENT_MODULES))

    CASES = (
        ({}, False),
        ({"model.py": "import runtime.executive_history\n"}, False),
        ({"model.py": "from .environment import make\n"}, False),
        ({"model.py": "import numpy\n"}, False),
        ({"model.py": "from . import DOMAIN\n"}, False),
        ({"environment.py": "from .model import services\n"}, False),
        ({"environment.py": "import numpy\n"}, False),        # no door listed
        ({"environment.py": "import numpy\n"}, True),         # door listed
        ({"environment.py": "import box_push_env\n"}, False),  # guard-only root, no door
        ({"environment.py": "import torch\n"}, True),         # never exempt, door listed
        ({"environment.py": "import legacy\n"}, True),
        ({"__init__.py": _CLEAN["__init__.py"] + "import numpy\n"}, False),
        ({"__init__.py": _CLEAN["__init__.py"] + "import pettingzoo\n"}, True),
        ({"types.py": "import pkgutil\n"}, False),
    )

    def test_both_scanners_agree_on_every_probe_tree(self):
        for files, door_listed in self.CASES:
            with self.subTest(files=files, door_listed=door_listed), contextlib.ExitStack() as stack:
                root = _tree(stack, files, door_listed=door_listed)
                exempt = frozenset({"domains/lamp/environment.py"}) if door_listed else frozenset()
                guard_flags = bool(
                    domain_role_violations(root)
                    or backend_violations(("domains",), root, exempt_modules=exempt)
                    or any(m.split(".")[0] in FORBIDDEN_DYNAMIC
                           for p in (root / "domains" / "lamp").glob("*.py")
                           for m, _ in imported_modules(p))
                )
                validator_flags = any(f.status is Status.FAIL for f in check_layout("lamp", repo_root=root))
                self.assertEqual(validator_flags, guard_flags, files)

    def test_the_real_tree_agrees(self):
        self.assertEqual(domain_role_violations(), [])
        self.assertEqual([f.status for f in check_layout("box_push")], [Status.PASS, Status.PASS])


class TestLazyBackendCheck(unittest.TestCase):
    def _root(self, stack, init_body):
        root = pathlib.Path(stack.enter_context(tempfile.TemporaryDirectory()))
        pkg = root / "domains" / "lamp"
        pkg.mkdir(parents=True)
        (root / "domains" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text(init_body, encoding="utf-8")
        return root

    def test_a_lazy_package_passes_and_an_eager_backend_import_fails(self):
        with contextlib.ExitStack() as stack:
            self.assertIs(check_lazy_backend("lamp", repo_root=self._root(stack, "X = 1\n")).status, Status.PASS)
        with contextlib.ExitStack() as stack:
            finding = check_lazy_backend("lamp", repo_root=self._root(stack, "import numpy\n"))
        self.assertIs(finding.status, Status.FAIL)
        self.assertIn("INSIDE make_environment()", finding.message)
        self.assertIn("numpy", finding.details)

    def test_an_import_error_is_reported_without_a_traceback_headline(self):
        with contextlib.ExitStack() as stack:
            finding = check_lazy_backend("lamp", repo_root=self._root(stack, "import no_such_module_xyz\n"))
        self.assertIs(finding.status, Status.FAIL)
        self.assertIn("failed in a fresh interpreter", finding.message)
        self.assertNotIn("Traceback", finding.message)


# ═══ 5. the CLI ════════════════════════════════════════════════════════════════════════

class TestCli(unittest.TestCase):
    def _main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as exit_:                  # argparse usage errors
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def test_list_domains(self):
        code, out, _ = self._main("list-domains")
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), sorted(REGISTRY))
        self.assertIn("box_push", out.split())

    def test_validate_box_push_exits_zero(self):
        code, out, _ = self._main("validate-domain", "box_push")
        self.assertEqual(code, 0, out)
        self.assertIn("Result: 28 PASS", out)
        self.assertNotRegex(out, _INTERNAL)

    def test_the_budget_reaches_the_episodes(self):
        code, out, _ = self._main("validate-domain", "box_push", "--budget", "1")
        self.assertEqual(code, 0, out)
        self.assertIn("budget_exhausted", out)
        self.assertIn("1 executive steps", out)

    def test_unknown_name_exits_one_with_the_registry_lines(self):
        code, out, _ = self._main("validate-domain", "warehouse")
        self.assertEqual(code, 1)
        self.assertIn("DK001", out)
        self.assertIn(registry_line("warehouse")[0], out)

    def test_usage_errors_exit_two(self):
        self.assertEqual(self._main("validate-domain", "box_push", "--budget", "0")[0], 2)
        self.assertEqual(self._main()[0], 2)
        self.assertEqual(self._main("frobnicate")[0], 2)

    def test_maaos_uses_no_dynamic_import(self):
        for path in sorted((_REPO_ROOT / "maaos").glob("*.py")):
            for module, lineno in imported_modules(path):
                self.assertNotIn(module.split(".")[0], FORBIDDEN_DYNAMIC, f"{path.name}:{lineno}")
            self.assertNotIn("__import__", path.read_text(encoding="utf-8"))

    def test_python_dash_m_maaos_smoke(self):
        env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT), SDL_VIDEODRIVER="dummy")
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "maaos", "validate-domain", "box_push"],
            cwd=_REPO_ROOT, env=env, capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("0 FAIL", completed.stdout)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
