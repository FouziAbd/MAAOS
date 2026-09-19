"""DK1 — the domain declaration record, generic assembly, the BoxPush declaration, and the
two guard decisions (`docs/decisions/DK1_DOMAIN_PACKAGE.md`).

What this module pins, in the order the ADR states it:

  1. `app/domain_package.py` is a domain-neutral record: no BoxPush vocabulary in its names,
     imports only stdlib + `shared`, refuses malformed declarations loudly at construction.
  2. `domains/<x>/` module roles are enforced on the real tree AND fail closed on probe
     trees: `model.py -> runtime`, `model.py -> environment`, `model.py -> numpy`,
     `environment.py -> model`, `environment.py -> legacy`, and the package-laundering case
     are each caught; the enumerated `environment.py` exemption equals the registry.
  3. `assemble_loop(domains.box_push.DOMAIN)` builds the SAME loop `build_loop` builds: same
     component types, the accepted outcomes and discrepancy count, the loop's own default
     provenance, and — the transcript pin — both baseline transcripts reproduced cycle by cycle
     through the assembled loop with the R0 renderer.
  4. `import domains` loads no backend module (subprocess); the environment factory is lazy.

Offline and deterministic: local backend, no LM, no network, no render.
"""
from __future__ import annotations

import ast
import contextlib
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ENV_DIR = _REPO_ROOT / "functional_layer" / "custom_env" / "box_push" / "env"
for _p in (str(_REPO_ROOT), str(_ENV_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from box_push_v1_adapter import BoxPushV1Adapter                         # noqa: E402

from app.assembly import assemble_loop                                   # noqa: E402
from app.box_push_v1 import BoxPushDomainServices, build_loop, compose   # noqa: E402
from app.comparator import BoxPushActionComparator                      # noqa: E402
from app.domain_package import DomainExamples, DomainPackage             # noqa: E402
from domain.box_push_v1 import TASK_DELIVER_BOTH, TASK_DELIVER_LIGHT      # noqa: E402
from domains.box_push import DOMAIN                                      # noqa: E402
from domains.registry import REGISTRY                                    # noqa: E402
from nl.recovery import propose_recovery                                 # noqa: E402
from runtime.loop import EpisodeOutcome, ExecutiveLoopManager            # noqa: E402
from shared.contracts import (                                           # noqa: E402
    DomainServices,
    Environment,
    ProposalComparator,
    RecoveryProvider,
    SymbolicTrack,
)
from shared.orchestration_config import (                                # noqa: E402
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.state_snapshot import StateSnapshot                          # noqa: E402
from symbolic import ExactSymbolicBelief                                 # noqa: E402
from tests.test_no_backend_imports import (                              # noqa: E402
    DOMAIN_ENVIRONMENT_MODULES,
    FORBIDDEN_PREFIXES,
    backend_violations,
    discovered_guarded_packages,
    domain_role_violations,
    imported_modules,
)
from tests.test_r0_characterization import (                             # noqa: E402
    _parse_transcript,
    _render_episode,
)

_PACKAGE_MODULE = _REPO_ROOT / "app" / "domain_package.py"
_ASSEMBLY_MODULE = _REPO_ROOT / "app" / "assembly.py"


# ── 1. the record is domain-neutral and loud ──────────────────────────────────────────

class TestDomainPackageIsANeutralRecord(unittest.TestCase):
    BOXPUSH_STEMS = ("box", "agent", "zone", "grid", "push", "deliver", "cell", "wall")
    ALLOWED_ROOTS = frozenset({"__future__", "dataclasses", "types", "typing", "shared"})

    def _names(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node, "id", None) or getattr(node, "attr", None) or (
                node.name if isinstance(node, (ast.ClassDef, ast.FunctionDef)) else None)
            if name is not None:
                yield name, node.lineno

    def test_no_boxpush_vocabulary_in_the_record(self):
        for name, lineno in self._names(_PACKAGE_MODULE):
            for stem in self.BOXPUSH_STEMS:
                self.assertNotIn(stem, name.lower(), f"domain_package.py:{lineno} names {name!r}")

    def test_the_record_imports_only_stdlib_and_shared(self):
        for module, lineno in imported_modules(_PACKAGE_MODULE):
            self.assertIn(module.split(".")[0], self.ALLOWED_ROOTS,
                          f"domain_package.py:{lineno} imports {module}")

    def _declare(self, **overrides):
        kwargs = dict(
            name="probe_free_name", tasks={"t": TASK_DELIVER_BOTH}, default_task="t",
            environment=DOMAIN.environment, services=DOMAIN.services,
            symbolic_track=DOMAIN.symbolic_track,
        )
        kwargs.update(overrides)
        return DomainPackage(**kwargs)

    def test_a_bad_name_is_refused_with_the_registry_hint(self):
        with self.assertRaisesRegex(ValueError, "identifier.*registry"):
            self._declare(name="not a name")

    def test_a_missing_default_task_is_refused(self):
        with self.assertRaisesRegex(ValueError, "default_task 'x' is not one of"):
            self._declare(default_task="x")

    def test_no_tasks_is_refused(self):
        with self.assertRaisesRegex(ValueError, "at least one task"):
            self._declare(tasks={}, default_task="t")

    def test_a_reasoning_track_without_a_comparator_is_refused(self):
        with self.assertRaisesRegex(ValueError, "reasoning_track requires a comparator"):
            self._declare(reasoning_track=lambda: None)

    def test_tasks_become_read_only_and_task_lookup_is_author_facing(self):
        package = self._declare(tasks={"a": TASK_DELIVER_BOTH, "b": TASK_DELIVER_LIGHT},
                                default_task="a")
        with self.assertRaises(TypeError):
            package.tasks["c"] = TASK_DELIVER_LIGHT           # type: ignore[index]
        self.assertIs(package.task(), TASK_DELIVER_BOTH)
        self.assertIs(package.task("b"), TASK_DELIVER_LIGHT)
        with self.assertRaisesRegex(ValueError, "no task 'zzz'; declared tasks: \\['a', 'b'\\]"):
            package.task("zzz")

    def test_examples_are_optional_and_typed(self):
        self.assertIsNone(self._declare().examples)
        self.assertIsInstance(DOMAIN.examples, DomainExamples)


# ── 2. module roles inside domains/<x>/ ───────────────────────────────────────────────

class TestDomainModuleRoles(unittest.TestCase):
    def test_the_real_tree_has_no_role_violations(self):
        self.assertEqual(domain_role_violations(), [])

    def test_the_real_tree_has_no_backend_violations_outside_the_door(self):
        self.assertEqual(backend_violations(discovered_guarded_packages()), [])

    def test_the_exempt_set_is_exactly_the_registered_domains_environment_modules(self):
        expected = {f"domains/{name}/environment.py" for name in REGISTRY}
        self.assertEqual(set(DOMAIN_ENVIRONMENT_MODULES), expected)
        for rel in DOMAIN_ENVIRONMENT_MODULES:
            self.assertTrue((_REPO_ROOT / rel).is_file(), rel)

    def test_the_exemption_is_load_bearing_and_covers_exactly_one_line(self):
        """Withdraw the exemption: the real tree must report exactly the door's one adapter
        import — one door, one line — and nothing else."""
        found = backend_violations(discovered_guarded_packages(), exempt_modules=frozenset())
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("domains/box_push/environment.py:"), found)
        self.assertIn("imports functional_layer.custom_env.box_push.env.box_push_v1_adapter", found[0])

    def test_the_boxpush_door_imports_the_backend_only_inside_the_factory(self):
        source = (_REPO_ROOT / "domains" / "box_push" / "environment.py").read_text("utf-8")
        tree = ast.parse(source)
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        for node in top_level:
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            self.assertNotIn(module.split(".")[0], FORBIDDEN_PREFIXES, module)
        self.assertNotIn("sys.path", source)

    # ── fail-closed probes (throwaway trees, never the working tree) ─────────────────
    @staticmethod
    def _probe(stack, files):
        root = pathlib.Path(stack.enter_context(tempfile.TemporaryDirectory()))
        for existing in ("shared", "runtime", "app", "kit"):
            (root / existing).mkdir()
            (root / existing / "__init__.py").write_text("", encoding="utf-8")
        pkg = root / "domains" / "probe_dom"
        pkg.mkdir(parents=True)
        (root / "domains" / "__init__.py").write_text("", encoding="utf-8")
        defaults = {"__init__.py": "", "types.py": "", "model.py": "", "environment.py": ""}
        defaults.update(files)
        for name, body in defaults.items():
            (pkg / name).write_text(body, encoding="utf-8")
        return root

    def _violations(self, files):
        with contextlib.ExitStack() as stack:
            return domain_role_violations(self._probe(stack, files))

    def test_a_clean_probe_package_passes(self):
        self.assertEqual(self._violations({
            "__init__.py": "from app.domain_package import DomainPackage\n"
                           "from runtime.loop import ExecutiveLoopManager\n"
                           "from .environment import make_environment\n"
                           "from .model import services\n",
            "types.py": "import dataclasses\nfrom shared.contracts import RuntimeState\n",
            "model.py": "from .types import State\nfrom . import types\nimport kit\n",
            "environment.py": "import numpy\nfrom .types import State\n",
        }), [])

    def test_model_importing_runtime_is_caught(self):
        self.assertTrue(self._violations({"model.py": "import runtime.executive_history\n"}))
        self.assertTrue(self._violations({"model.py": "from app.assembly import assemble_loop\n"}))

    def test_model_importing_environment_is_caught(self):
        self.assertTrue(self._violations({"model.py": "from .environment import make\n"}))
        self.assertTrue(self._violations({"model.py": "from domains.probe_dom.environment import x\n"}))

    def test_model_importing_a_backend_is_caught_by_the_role_scan(self):
        self.assertTrue(self._violations({"model.py": "import numpy\n"}))
        self.assertTrue(self._violations({"types.py": "import functional_layer.custom_env\n"}))

    def test_environment_importing_model_or_runtime_is_caught(self):
        self.assertTrue(self._violations({"environment.py": "from .model import services\n"}))
        self.assertTrue(self._violations({"environment.py": "import runtime\n"}))

    def test_environment_importing_legacy_is_never_exempt(self):
        with contextlib.ExitStack() as stack:
            root = self._probe(stack, {"environment.py": "import legacy\nimport numpy\n"})
            found = backend_violations(
                ("domains",), root, exempt_modules={"domains/probe_dom/environment.py"}
            )
        self.assertEqual(len(found), 1, found)
        self.assertIn("imports legacy", found[0])

    def test_environment_importing_an_lm_framework_is_never_exempt(self):
        with contextlib.ExitStack() as stack:
            root = self._probe(stack, {"environment.py": "import dspy\nimport torch\nimport numpy\n"})
            found = backend_violations(
                ("domains",), root, exempt_modules={"domains/probe_dom/environment.py"}
            )
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all("dspy" in f or "torch" in f for f in found), found)

    def test_the_exemption_does_not_reach_model(self):
        with contextlib.ExitStack() as stack:
            root = self._probe(stack, {"model.py": "import numpy\n", "environment.py": "import numpy\n"})
            found = backend_violations(
                ("domains",), root, exempt_modules={"domains/probe_dom/environment.py"}
            )
        self.assertEqual(len(found), 1, found)
        self.assertIn("model.py", found[0])

    def test_package_laundering_is_caught(self):
        for body in ("from . import DOMAIN\n", "from domains.probe_dom import DOMAIN\n",
                     "import domains.probe_dom\n", "from domains.other_dom import x\n"):
            with self.subTest(body=body):
                self.assertTrue(self._violations({"model.py": body}), body)

    def test_a_sibling_module_import_is_allowed_in_both_spellings(self):
        self.assertEqual(self._violations({"model.py": "from .types import S\nfrom . import types\n"}), [])


# ── 3. assemble_loop == build_loop for BoxPush ────────────────────────────────────────

_CACHE: dict[OrchestrationPolicy, tuple[ExecutiveLoopManager, object]] = {}


def _assembled(policy):
    if policy not in _CACHE:
        loop = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=policy))
        _CACHE[policy] = (loop, loop.run())
    return _CACHE[policy]


class TestAssembleLoopMatchesBuildLoop(unittest.TestCase):
    def test_the_registry_names_boxpush(self):
        self.assertIn("box_push", REGISTRY)
        self.assertIs(REGISTRY["box_push"], DOMAIN)
        for key, package in REGISTRY.items():          # the key IS the declared name
            self.assertEqual(key, package.name)
            self.assertIsInstance(package, DomainPackage)
        self.assertEqual(DOMAIN.name, "box_push")
        self.assertEqual(set(DOMAIN.tasks), {"deliver_both", "deliver_light", "deliver_heavy"})
        self.assertEqual(DOMAIN.default_task, "deliver_both")
        self.assertIsNone(DOMAIN.reasoning_track)

    def test_component_types_equal_compose(self):
        expected = compose(TASK_DELIVER_BOTH)
        loop = assemble_loop(DOMAIN)
        self.assertIsInstance(loop.domain, BoxPushDomainServices)
        self.assertIs(type(loop.domain), type(expected.domain))
        self.assertIs(type(loop.belief), ExactSymbolicBelief)
        self.assertIs(type(loop.comparator), BoxPushActionComparator)
        self.assertIs(loop.recovery_provider, propose_recovery)
        self.assertIs(loop.task, TASK_DELIVER_BOTH)
        self.assertIs(type(loop), ExecutiveLoopManager)
        for component, contract in (
            (loop.domain, DomainServices), (loop.belief, SymbolicTrack),
            (loop.comparator, ProposalComparator), (loop.recovery_provider, RecoveryProvider),
            (loop.env, Environment),
        ):
            self.assertIsInstance(component, contract)

    def test_the_environment_is_the_frozen_headless_instance(self):
        loop = assemble_loop(DOMAIN)
        snapshot = loop.env.reset()
        self.assertIsInstance(snapshot, StateSnapshot)
        # an INDEPENDENTLY built adapter (the name the runner/tests use) — same frozen instance
        self.assertEqual(snapshot.world_key(), BoxPushV1Adapter().reset().world_key())
        self.assertEqual(snapshot, BoxPushV1Adapter().reset())

    def test_provenance_is_the_loops_own_default(self):
        loop = assemble_loop(DOMAIN)
        self.assertEqual(loop.provenance.source, "runtime/loop.py::ExecutiveLoopManager")
        self.assertEqual(loop.provenance, build_loop(loop.env, TASK_DELIVER_BOTH).provenance)

    def test_accepted_outcomes_and_discrepancy_count(self):
        _, primary = _assembled(OrchestrationPolicy.SYMBOLIC_PRIMARY)
        _, advisory = _assembled(OrchestrationPolicy.ADVISORY_TWO_TRACK)
        self.assertIs(primary.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIs(advisory.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(len(primary.discrepancies), 3)
        self.assertEqual(len(advisory.discrepancies), 3)

    def test_both_baseline_transcripts_reproduce_through_assemble_loop(self):
        """The transcript pin at the accepted R0 granularity — every cycle row (step,
        decision, call, outcome, discrepancy kind, recovery marker), the step-accounting
        footer and the outcome line — from a loop assembled from the declaration rather
        than from `build_loop`. Non-vacuity guards mirror the R0 module's."""
        for policy in OrchestrationPolicy:
            with self.subTest(policy=policy.value):
                loop, episode = _assembled(policy)
                rows, footer, outcome = _parse_transcript(policy)
                self.assertGreaterEqual(len(rows), 8)                # non-vacuity, as in R0
                self.assertIsNotNone(footer)
                self.assertIsNotNone(outcome)
                self.assertEqual(_render_episode(episode), rows)
                self.assertEqual(
                    (loop.executive_steps_charged, loop.primitive_steps_charged,
                     len(episode.discrepancies)),
                    footer,
                )
                self.assertEqual((episode.outcome.value.upper(), episode.reason), outcome)

    def test_each_keyword_overrides_exactly_one_component(self):
        class _Loop(ExecutiveLoopManager):
            pass
        env = DOMAIN.environment()
        services = BoxPushDomainServices(TASK_DELIVER_LIGHT)
        loop = assemble_loop(
            DOMAIN, "deliver_light", loop_class=_Loop, environment=env, domain=services,
            recovery_provider=None,
        )
        self.assertIs(type(loop), _Loop)
        self.assertIs(loop.env, env)
        self.assertIs(loop.domain, services)
        self.assertIs(loop.task, TASK_DELIVER_LIGHT)
        self.assertIs(loop.recovery_provider, propose_recovery)   # None means "not overridden"
        self.assertIs(type(loop.belief), ExactSymbolicBelief)
        track = ExactSymbolicBelief.__new__(ExactSymbolicBelief)   # identity is all that matters
        comparator = BoxPushActionComparator(compose(TASK_DELIVER_BOTH).comparator.equivalence)
        loop2 = assemble_loop(DOMAIN, symbolic_track=track, comparator=comparator)
        self.assertIs(loop2.belief, track)
        self.assertIs(loop2.comparator, comparator)
        self.assertIsNot(loop2.domain, services)

    def test_a_declared_reasoning_track_is_attached_by_default_and_can_be_suppressed(self):
        calls = []

        class _Track:
            def observe(self, state, label=None, outcome=None, /):
                pass

            def propose(self, task, /):
                raise AssertionError("never called here")

        def factory():
            calls.append("track")
            return _Track()

        declared = dataclasses.replace(DOMAIN, reasoning_track=factory)
        attached = assemble_loop(declared)
        self.assertIsInstance(attached.nl_track, _Track)
        self.assertEqual(calls, ["track"])
        self.assertIs(type(attached.comparator), BoxPushActionComparator)
        suppressed = assemble_loop(declared, use_reasoning_track=False)
        self.assertIsNone(suppressed.nl_track)
        self.assertEqual(calls, ["track"])                          # factory not called
        explicit = _Track()
        replaced = assemble_loop(declared, nl_track=explicit)
        self.assertIs(replaced.nl_track, explicit)
        self.assertEqual(calls, ["track"])                          # explicit bypasses it
        # the record itself refuses a track without a comparator (mirrors the loop's refusal)
        with self.assertRaisesRegex(ValueError, "requires a comparator"):
            dataclasses.replace(DOMAIN, reasoning_track=factory, comparator=None)

    def test_an_unknown_task_name_is_an_author_facing_error(self):
        with self.assertRaisesRegex(ValueError, "no task 'nope'"):
            assemble_loop(DOMAIN, "nope")

    def test_the_environment_is_never_handed_to_a_domain_factory(self):
        """Structural: no factory on the record takes an environment parameter, and the
        assembly source passes `env` to the loop only."""
        source = _ASSEMBLY_MODULE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        for call in calls:
            func = call.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "package":
                passed = list(call.args) + [kw.value for kw in call.keywords]
                for arg in passed:
                    self.assertNotEqual(getattr(arg, "id", None), "env", ast.dump(call))
        self.assertNotIn("**", source.split("def assemble_loop")[1])


# ── 4. import domains loads no backend ────────────────────────────────────────────────

class TestImportingDomainsLoadsNoBackend(unittest.TestCase):
    def test_import_domains_and_registry_leaves_the_backend_unloaded(self):
        script = (
            "import json, sys\n"
            "import domains, domains.registry, domains.box_push\n"
            "roots = " + repr(sorted(FORBIDDEN_PREFIXES)) + "\n"
            "loaded = sorted(m for m in sys.modules if m.split('.')[0] in roots)\n"
            "env = domains.box_push.DOMAIN.environment()\n"          # the positive control
            "after = sorted(m for m in sys.modules if m.split('.')[0] in roots)\n"
            "print(json.dumps({'loaded': loaded, 'after': after, "
            "'names': sorted(domains.registry.REGISTRY)}))\n"
        )
        env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT), SDL_VIDEODRIVER="dummy")
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=_REPO_ROOT, env=env,
            capture_output=True, text=True, timeout=120, check=True,
        )
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(report["loaded"], [], f"backend modules loaded: {report['loaded']}")
        self.assertEqual(report["names"], ["box_push"])
        # positive control: the scan DOES see the backend once the factory runs
        self.assertIn("functional_layer.custom_env.box_push.env.box_push_v1_adapter", report["after"])


if __name__ == "__main__":
    unittest.main()
