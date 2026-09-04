"""R4 domain-composition tests (report Phase 4).

Phase 4 acceptance, made mechanical:

- `runtime/` imports only shared contracts and domain-independent runtime helpers
  (`TestRuntimeImportBoundary`: an AST allowlist over EVERY runtime module, forbidding
  `domain`, `symbolic`, `nl`, `app`, the backend/legacy packages and the sys.path-mounted
  adapter modules; plus a vocabulary scan proving the runtime never reads an agent, box,
  or zone);
- the BoxPush runner assembles environment, domain services, tracks, comparator, recovery
  provider, and policy (`TestCompositionRoot`: `compose`/`build_loop` produce and inject
  the concrete components; the runner source goes through the composition root and never
  constructs the loop directly);
- changing one injected implementation does not require editing the loop
  (`TestInjectedSubstitution`: a substitute domain-services bundle, symbolic track,
  comparator, and recovery provider each drive a real episode through the UNMODIFIED
  `ExecutiveLoopManager`, observed at the trace/outcome seam);
- the `DomainServices` contract is satisfied by the BoxPush bundle at runtime and
  statically (`TestDomainServicesContract`), and its grounding verdicts are the frozen
  §19.1 item 5 identities (`TestGroundingIsDomainOwned`).

Offline and deterministic: the only environment touched is the local adapter.
"""
import ast
import os
import pathlib
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_DIR = os.path.join(_REPO_ROOT, "functional_layer", "custom_env", "box_push", "env")
for _p in (_REPO_ROOT, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from box_push_v1_adapter import BoxPushV1Adapter

from app.box_push_v1 import BoxPushComponents, BoxPushDomainServices, build_loop, compose
from app.comparator import BoxPushActionComparator
from domain.box_push_v1 import (
    AGENT_0,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    TASK_DELIVER_BOTH,
    initial_state,
)
from nl.recovery import propose_recovery
from nl.track import GroundedProposal
from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
from runtime.policies import AdvisoryTwoTrackPolicy
from shared.contracts import (
    ComparedAspect,
    ComparisonFinding,
    ComparisonReport,
    DomainServices,
    FindingSeverity,
    Prediction,
    ProposalComparator,
    RecoveryProvider,
    SymbolicTrack,
)
from shared.divergence import DivergenceKind, TrackDivergence
from shared.ids import AgentId, BoxId, ZoneId
from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import GroundedSkillCall, SkillName, UngroundedCall
from symbolic import ExactSymbolicBelief
from tests import contract_conformance

_RUNTIME_DIR = pathlib.Path(_REPO_ROOT, "runtime")
_RUNNER = pathlib.Path(_ENV_DIR, "box_push_v1_run.py")

GOTO = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
PUSH = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)


def _proposal(call):
    return GroundedProposal(
        call=call,
        coverage=CoverageReport(covered=("x",), residual=()),
        confidence=ConfidenceReport(source="nl", confidence=1.0),
    )


class _StubTrack:
    """Duck-typed advisory track: fixed proposals, no LM."""

    def __init__(self, proposals):
        self._proposals = list(proposals)
        self.proposed = 0

    def observe(self, snapshot, skill=None, outcome=None):
        pass

    def propose(self, task):
        self.proposed += 1
        return self._proposals.pop(0)


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module, node.lineno


# ── acceptance 1: the runtime import boundary ──────────────────────────────────────

class TestRuntimeImportBoundary(unittest.TestCase):
    """`runtime/` imports only shared contracts and domain-independent runtime helpers."""

    #: stdlib the runtime core actually uses — a WHITELIST, so any new dependency is a
    #: deliberate edit here, never a silent one in the runtime
    STDLIB = frozenset({"__future__", "re", "dataclasses", "enum", "typing"})
    ALLOWED_ROOTS = STDLIB | {"shared", "runtime"}
    #: the roots the report names (Part II) plus every legacy/backend root the repository
    #: guard already bans — listed explicitly so a violation names its category
    FORBIDDEN_ROOTS = frozenset({
        "domain", "symbolic", "nl", "app",
        "functional_layer", "middleware_layer", "model_layer",
        "box_push_v1_adapter", "box_push_v1_run", "box_push_env", "multi_agent_box_push_env",
        "skill_executor_push", "shared_skills", "box_push_centralized", "box_push_per_step",
    })

    def _runtime_sources(self):
        # rglob, not glob: a `runtime/<sub>/` package must not evade the boundary
        # (test-review F2)
        files = sorted(p for p in _RUNTIME_DIR.rglob("*.py") if "__pycache__" not in p.parts)
        self.assertGreaterEqual(len(files), 5, "runtime package unexpectedly small")
        for path in files:
            yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_the_boundary_scan_covers_runtime_subpackages(self):
        """Fail-closed: a throwaway `runtime/ext/leak.py` in a temp tree is found by the
        same enumeration the real scans use. Never touches the working tree."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp, "runtime")
            (root / "ext").mkdir(parents=True)
            (root / "loop.py").write_text("import shared\n", encoding="utf-8")
            (root / "ext" / "leak.py").write_text(
                "from domain.box_push_v1 import DOMAIN_IR\n", encoding="utf-8")
            found = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py"))
            self.assertEqual(found, ["ext/leak.py", "loop.py"])
            leaked = [m for p in root.rglob("*.py")
                      for m, _ in _imports(ast.parse(p.read_text(encoding="utf-8")))
                      if m.split(".")[0] in self.FORBIDDEN_ROOTS]
            self.assertEqual(leaked, ["domain.box_push_v1"])

    def test_runtime_imports_only_shared_contracts_and_runtime_helpers(self):
        for path, tree in self._runtime_sources():
            for module, lineno in _imports(tree):
                root = module.split(".")[0]
                with self.subTest(file=path.name, module=module):
                    self.assertNotIn(
                        root, self.FORBIDDEN_ROOTS,
                        f"runtime/{path.name}:{lineno} imports {module!r} — the runtime "
                        f"core must not import BoxPush, concrete tracks, the composition "
                        f"layer, or legacy packages (report Phase 4 item 4)",
                    )
                    self.assertIn(
                        root, self.ALLOWED_ROOTS,
                        f"runtime/{path.name}:{lineno} imports {module!r} outside the "
                        f"declared stdlib+shared+runtime surface",
                    )

    def test_the_forbidden_list_is_not_vacuous(self):
        """A probe module carrying each forbidden root must be caught by the same scan."""
        for root in ("domain.box_push_v1", "symbolic", "nl.recovery", "app.box_push_v1",
                     "box_push_v1_adapter", "functional_layer.custom_env"):
            tree = ast.parse(f"from {root} import x\n")
            caught = [m for m, _ in _imports(tree) if m.split(".")[0] in self.FORBIDDEN_ROOTS]
            self.assertTrue(caught, f"{root!r} would slip through the boundary scan")

    def test_no_dynamic_import_escapes_in_runtime(self):
        for path, tree in self._runtime_sources():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("__import__", text, path.name)
            for module, lineno in _imports(tree):
                self.assertNotIn(
                    module.split(".")[0], {"importlib", "imp", "pkgutil", "runpy"},
                    f"runtime/{path.name}:{lineno} imports {module!r}",
                )

    #: BoxPush vocabulary the generic runtime must never read or name (CLAUDE.md: "must
    #: not interpret BoxPush vocabulary such as agent, box, zone, or geometry")
    BOXPUSH_ATTRIBUTES = frozenset({
        "agents", "agent_id", "box", "boxes", "box_id", "zone", "zones", "goal_delivered",
        "position", "facing", "delivered", "static", "walls",
    })
    BOXPUSH_NAMES = frozenset({
        "DOMAIN_IR", "PROJECTION", "MODEL_VERSION", "TASK_DELIVER_BOTH", "DELIVERY_ZONE",
        "Universe", "project", "plan", "evaluate", "monitor_execution", "predict_symbolic",
        "predict_world_candidates", "propose_recovery", "ExactSymbolicBelief",
        "BoxPushActionComparator", "BoxPushActionEquivalence", "DEFAULT_COMPARATOR",
        "AgentId", "BoxId", "ZoneId",
    })

    def test_runtime_reads_no_agent_box_or_zone(self):
        """The loop used to check `call.agents`/`call.box`/`call.zone` against
        `snapshot.agents`/`snapshot.boxes`/`task.zone` itself; that vocabulary now lives
        only behind the injected domain services."""
        for path, tree in self._runtime_sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(
                        node.attr, self.BOXPUSH_ATTRIBUTES,
                        f"runtime/{path.name}:{node.lineno} reads .{node.attr}",
                    )
                elif isinstance(node, ast.Name):
                    self.assertNotIn(
                        node.id, self.BOXPUSH_NAMES,
                        f"runtime/{path.name}:{node.lineno} names {node.id}",
                    )

    def test_the_vocabulary_scan_is_not_vacuous(self):
        tree = ast.parse("def f(call, snapshot):\n    return call.zone, snapshot.agents\n")
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertTrue(attrs & self.BOXPUSH_ATTRIBUTES)


# ── the DomainServices contract ────────────────────────────────────────────────────

class TestDomainServicesContract(unittest.TestCase):
    def test_the_boxpush_bundle_satisfies_the_contract(self):
        services = BoxPushDomainServices(TASK_DELIVER_BOTH)
        self.assertIsInstance(services, DomainServices)
        self.assertIs(contract_conformance.domain_services_conform(services), services)

    def test_prediction_is_a_typed_pair_of_frozen_keys(self):
        import dataclasses
        prediction = Prediction()
        self.assertIsNone(prediction.symbolic_key)
        self.assertIsNone(prediction.world_key)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            prediction.world_key = None

    def test_bundle_operations_match_the_pre_r4_inline_wiring(self):
        """The bundle applies exactly the functions the loop applied itself through R3,
        with the frozen model constants — pinned at the seam, on the initial state."""
        from domain.box_push_v1 import DOMAIN_IR, MODEL_VERSION, PROJECTION, project
        from symbolic import Universe, evaluate, plan
        from symbolic.predictor import predict_symbolic, predict_world_candidates
        from shared.symbolic_state import GroundedLiteral
        services = BoxPushDomainServices(TASK_DELIVER_BOTH)
        snapshot = initial_state()
        symbolic = project(snapshot)
        self.assertIs(services.model_version, MODEL_VERSION)
        goal = frozenset(
            GroundedLiteral("delivered", (str(b),)) for b in TASK_DELIVER_BOTH.goal_delivered
        )
        expected_plan = plan(
            DOMAIN_IR, symbolic, goal,
            Universe.from_snapshot(snapshot, TASK_DELIVER_BOTH.zone), MODEL_VERSION,
        )
        self.assertEqual(services.plan(symbolic, snapshot), expected_plan)
        self.assertEqual(services.evaluate(symbolic, GOTO), evaluate(DOMAIN_IR, symbolic, GOTO))
        predicted = predict_symbolic(DOMAIN_IR, symbolic, GOTO)
        candidates = predict_world_candidates(snapshot, GOTO, TASK_DELIVER_BOTH.zone)
        self.assertEqual(
            services.predict(symbolic, snapshot, GOTO),
            Prediction(symbolic_key=PROJECTION.monitored_key(predicted),
                       world_key=candidates[0].world_key()),
        )

    def test_plan_reads_the_snapshot_for_identities_only(self):
        """Decision 6, at the new seam: `plan` receives the authoritative snapshot so the
        domain can fix its grounding universe, and for NOTHING else. Moving every agent
        and box (same identities, different positions/facing) must not change the plan — the
        planner decides from the symbolic literals alone, and the projected literals of
        the ORIGINAL snapshot are held fixed here so only the snapshot argument varies."""
        import dataclasses
        from domain.box_push_v1 import project
        from shared.state_snapshot import AgentSnapshot, BoxSnapshot, StateSnapshot
        services = BoxPushDomainServices(TASK_DELIVER_BOTH)
        snapshot = initial_state()
        symbolic = project(snapshot)
        moved = dataclasses.replace(
            snapshot,
            agents=tuple(dataclasses.replace(a, position=(2 + i, 2), direction=(i + 1) % 4)
                         for i, a in enumerate(snapshot.agents)),
            boxes=tuple(dataclasses.replace(b, position=(3, 5 + i))
                        for i, b in enumerate(snapshot.boxes)),
        )
        self.assertNotEqual(moved.world_key(), snapshot.world_key())   # geometry did move
        self.assertEqual(services.plan(symbolic, moved), services.plan(symbolic, snapshot))
        # and the universe it derived is the same identity set
        self.assertEqual(services._universe_for(moved), services._universe_for(snapshot))

    def test_the_universe_is_derived_from_each_plan_calls_snapshot(self):
        """Pins PER-CALL derivation (ADR-R4): the pre-R4 loop cached the universe from
        its first synced snapshot; the bundle instead derives it from the snapshot
        passed with EACH plan request. Discriminating case: the identity set changes
        between two calls on ONE services instance — a first-call cache would answer
        the second call with the first call's identities. In both orders."""
        import dataclasses
        from shared.planner_result import NoPlan, PlanFound
        from shared.task import Task
        from domain.box_push_v1 import project
        task = Task(task_id="heavy-solo", description="Deliver the heavy box",
                    goal_delivered=(BOX_HEAVY,), zone=DELIVERY_ZONE)
        full = initial_state()
        solo = dataclasses.replace(full, agents=full.agents[:1])     # one agent exists
        self.assertEqual(len(solo.agents), 1)
        for first, second, kinds in (
            (full, solo, (PlanFound, NoPlan)),
            (solo, full, (NoPlan, PlanFound)),
        ):
            with self.subTest(order=[len(first.agents), len(second.agents)]):
                services = BoxPushDomainServices(task)
                # the symbolic literals are held to the FULL projection in both orders
                # (projecting the solo snapshot would also drop agent_1's literals) so
                # the identity universe is the ONLY thing that differs between calls
                symbolic = project(full)
                self.assertIsInstance(services.plan(symbolic, first), kinds[0])
                self.assertIsInstance(services.plan(symbolic, second), kinds[1])

    def test_the_universe_override_is_the_synthetic_noplan_seam(self):
        """Decision 12: the one-agent universe makes CooperativePush ungroundable, so the
        heavy box has no plan — now an explicit composition override, not a private field."""
        from shared.planner_result import NoPlan, PlanFound
        from shared.task import Task
        from symbolic import Universe
        from domain.box_push_v1 import project
        task = Task(task_id="heavy-solo", description="Deliver the heavy box",
                    goal_delivered=(BOX_HEAVY,), zone=DELIVERY_ZONE)
        snapshot = initial_state()
        full = BoxPushDomainServices(task)
        solo = BoxPushDomainServices(task, universe=Universe(
            agents=(AGENT_0,), boxes=(BOX_HEAVY,), zone=DELIVERY_ZONE))
        self.assertIsInstance(full.plan(project(snapshot), snapshot), PlanFound)
        self.assertIsInstance(solo.plan(project(snapshot), snapshot), NoPlan)


class TestGroundingIsDomainOwned(unittest.TestCase):
    """§19.1 item 5, verbatim from the pre-R4 loop: unknown agent, unknown box, and
    zone-identity mismatch each yield the typed UngroundedCall; a known call yields None."""

    def setUp(self):
        self.services = BoxPushDomainServices(TASK_DELIVER_BOTH)
        self.snapshot = initial_state()

    def test_known_identities_ground(self):
        self.assertIsNone(self.services.ground(self.snapshot, GOTO))

    def test_unknown_agent_is_ungrounded(self):
        ghost = GroundedSkillCall(
            SkillName.GOTO_PUSH_POSE, (AgentId("agent_9"),), BOX_LIGHT, DELIVERY_ZONE)
        verdict = self.services.ground(self.snapshot, ghost)
        self.assertIsInstance(verdict, UngroundedCall)
        self.assertIn("unknown agent", verdict.reason)
        self.assertEqual(verdict.call, ghost)

    def test_unknown_box_is_ungrounded(self):
        ghost = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BoxId(7), DELIVERY_ZONE)
        verdict = self.services.ground(self.snapshot, ghost)
        self.assertIsInstance(verdict, UngroundedCall)
        self.assertIn("unknown box", verdict.reason)

    def test_foreign_zone_is_ungrounded(self):
        alien = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, ZoneId("mars"))
        verdict = self.services.ground(self.snapshot, alien)
        self.assertIsInstance(verdict, UngroundedCall)
        self.assertIn("zone identity mismatch", verdict.reason)


# ── acceptance 2: the composition root ─────────────────────────────────────────────

class TestCompositionRoot(unittest.TestCase):
    def test_compose_assembles_the_concrete_v1_components(self):
        components = compose(TASK_DELIVER_BOTH)
        self.assertIsInstance(components, BoxPushComponents)
        self.assertIsInstance(components.domain, BoxPushDomainServices)
        self.assertIs(components.domain.task, TASK_DELIVER_BOTH)
        self.assertIsInstance(components.symbolic_track, ExactSymbolicBelief)
        self.assertIsInstance(components.comparator, BoxPushActionComparator)
        self.assertIs(components.recovery_provider, propose_recovery)
        # each is the contract the loop consumes
        self.assertIsInstance(components.domain, DomainServices)
        self.assertIsInstance(components.symbolic_track, SymbolicTrack)
        self.assertIsInstance(components.comparator, ProposalComparator)
        self.assertIsInstance(components.recovery_provider, RecoveryProvider)

    def test_compose_yields_a_fresh_symbolic_track_per_loop(self):
        """A belief is per-episode state; two loops must never share one."""
        self.assertIsNot(compose(TASK_DELIVER_BOTH).symbolic_track,
                         compose(TASK_DELIVER_BOTH).symbolic_track)

    def test_build_loop_injects_the_composed_components_and_the_policy(self):
        env = BoxPushV1Adapter()
        loop = build_loop(
            env, TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
        )
        self.assertIsInstance(loop, ExecutiveLoopManager)
        self.assertIs(loop.env, env)
        self.assertIs(loop.task, TASK_DELIVER_BOTH)
        self.assertIsInstance(loop.domain, BoxPushDomainServices)
        self.assertIsInstance(loop.belief, ExactSymbolicBelief)
        self.assertIsInstance(loop.comparator, BoxPushActionComparator)
        self.assertIs(loop.recovery_provider, propose_recovery)
        self.assertIsInstance(loop.policy, AdvisoryTwoTrackPolicy)
        env.close()

    def test_build_loop_overrides_are_honored_by_identity(self):
        components = compose(TASK_DELIVER_BOTH)
        provider = lambda discrepancy: ()                       # noqa: E731
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            domain=components.domain, symbolic_track=components.symbolic_track,
            comparator=components.comparator, recovery_provider=provider,
        )
        self.assertIs(loop.domain, components.domain)
        self.assertIs(loop.belief, components.symbolic_track)
        self.assertIs(loop.comparator, components.comparator)
        self.assertIs(loop.recovery_provider, provider)
        loop.env.close()

    def test_the_loop_refuses_to_run_without_injected_domain_services(self):
        """The pre-R4 two-argument construction composed BoxPush inside the runtime; that
        default is gone by design, and the refusal is loud at construction."""
        env = BoxPushV1Adapter()
        with self.assertRaisesRegex(TypeError, "domain"):
            ExecutiveLoopManager(env, TASK_DELIVER_BOTH)
        env.close()

    def test_an_attached_track_without_a_comparator_is_a_composition_error(self):
        components = compose(TASK_DELIVER_BOTH)
        env = BoxPushV1Adapter()
        with self.assertRaisesRegex(TypeError, "comparator"):
            ExecutiveLoopManager(
                env, TASK_DELIVER_BOTH, nl_track=_StubTrack([]),
                domain=components.domain, symbolic_track=components.symbolic_track,
            )
        env.close()

    def test_the_runner_goes_through_the_composition_root(self):
        """The BoxPush runner assembles through `app.box_push_v1.build_loop` and never
        constructs the generic loop directly (report Phase 4 item 3)."""
        source = _RUNNER.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {(m, a.name) for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and (m := node.module)
                    for a in node.names}
        self.assertIn(("app.box_push_v1", "build_loop"), imported)
        self.assertNotIn(("runtime.loop", "ExecutiveLoopManager"), imported)
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("build_loop", calls)
        self.assertNotIn("ExecutiveLoopManager", calls)

    def test_the_composition_layer_never_imports_the_backend(self):
        """`app` is discovered and backend-guarded by tests/test_no_backend_imports.py;
        pinned here too so the R4 boundary reads in one place."""
        from tests.test_no_backend_imports import (
            backend_violations, discovered_guarded_packages,
        )
        self.assertIn("app", discovered_guarded_packages())
        self.assertEqual(backend_violations(["app"]), [])

    def test_accepted_outcomes_hold_through_the_composition_root(self):
        """The R0 characterization pins the cycle-by-cycle transcripts; this is the
        one-line outcome check at the new assembly seam."""
        expected = {
            OrchestrationPolicy.SYMBOLIC_PRIMARY: EpisodeOutcome.HALTED_REPEATED_FAILURE,
            OrchestrationPolicy.ADVISORY_TWO_TRACK: EpisodeOutcome.GOAL_REACHED,
        }
        for policy, outcome in expected.items():
            with self.subTest(policy=policy.value):
                loop = build_loop(BoxPushV1Adapter(), TASK_DELIVER_BOTH,
                                  OrchestrationConfig(policy=policy))
                episode = loop.run()
                self.assertIs(episode.outcome, outcome)
                self.assertEqual(len(episode.discrepancies), 3)
                loop.env.close()


# ── acceptance 3: one injected implementation changes, the loop does not ───────────

class _StrictServicesProxy:
    """Delegates to the real bundle, records every consultation in order, and REFUSES any
    attribute outside the DomainServices contract — proving the loop reaches the domain
    only through the declared surface."""

    CONTRACT = ("model_version", "plan", "ground", "evaluate", "predict", "monitor")

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    @property
    def model_version(self):
        return self._inner.model_version

    def __getattr__(self, name):
        if name not in self.CONTRACT:
            raise AssertionError(f"loop reached outside the DomainServices contract: {name}")
        target = getattr(self._inner, name)

        def recorded(*args):
            self.calls.append(name)
            return target(*args)
        return recorded


class _CountingTrack:
    """A SymbolicTrack substitute wrapping the real belief; counts the contract calls."""

    def __init__(self, inner):
        self._inner = inner
        self.synced = 0
        self.recorded = 0

    def sync(self, snapshot, /):
        self.synced += 1
        self._inner.sync(snapshot)

    @property
    def state(self):
        return self._inner.state

    def record_outcome(self, result, /):
        self.recorded += 1
        self._inner.record_outcome(result)


class _CannedComparator:
    """A ProposalComparator substitute: the same report for every compared pair."""

    def __init__(self, report):
        self.report = report
        self.compared = []

    def compare(self, symbolic_call, nl_proposal, /):
        self.compared.append((symbolic_call, nl_proposal))
        return self.report


class TestInjectedSubstitution(unittest.TestCase):
    def test_a_substitute_domain_bundle_drives_the_episode_through_the_contract_only(self):
        proxy = _StrictServicesProxy(BoxPushDomainServices(TASK_DELIVER_BOTH))
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            domain=proxy,
        )
        self.assertIs(loop.domain, proxy)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        executed = [e for e in episode.history.entries if e.execution is not None]
        self.assertEqual(len(executed), 9)
        # every executed cycle consulted the domain in the frozen order: plan, then the
        # head verdict, then (after the decision) ground + evaluate + predict, then monitor.
        # One plan per CYCLE: the REQUEST_PROPOSAL entry and the recovery enactment that
        # follows it share one cycle's planner result (two entries, one plan call).
        cycles_planned = {e.executive_step for e in episode.history.entries
                          if e.symbolic_result is not None}
        self.assertEqual(proxy.calls.count("plan"), len(cycles_planned))
        self.assertEqual(proxy.calls.count("ground"), 9)
        self.assertEqual(proxy.calls.count("predict"), 9)
        self.assertEqual(proxy.calls.count("monitor"), 9)
        # the WHOLE sequence (test-review W1): every executed cycle is exactly
        # plan -> head verdict -> [decision] -> ground -> evaluate -> predict -> monitor.
        # The REQUEST_PROPOSAL cycle has the same shape: its re-selection carries the
        # standing recovery call, for which no head verdict is computed (the preliminary
        # context with standing advice has no head_validation), so the enacted advice
        # goes straight to the ground -> evaluate gates. An evaluate() BEFORE ground()
        # (the §19.1 item 5 inversion) would break this list.
        cycle = ["plan", "evaluate", "ground", "evaluate", "predict", "monitor"]
        self.assertEqual(proxy.calls, cycle * 9)
        loop.env.close()

    def test_trace_entries_are_stamped_with_the_domain_model_version(self):
        """Test-review W2: the entry stamp is the DOMAIN's model version even when an
        injected Provenance carries a different one (pre-R4 the stamp was the frozen
        constant regardless of provenance; the seam moved, the rule did not)."""
        from shared.versioning import ModelVersion, Provenance
        from domain.box_push_v1 import MODEL_VERSION
        foreign = ModelVersion(revision=99, label="not-the-domain")
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY),
            provenance=Provenance(source="test", model_version=foreign),
        )
        episode = loop.run()
        self.assertTrue(episode.history.entries)
        for entry in episode.history.entries:
            self.assertEqual(entry.model_version, MODEL_VERSION)
            self.assertEqual(entry.provenance.model_version, foreign)
        loop.env.close()

    def test_a_substitute_symbolic_track_is_the_one_synced_and_fed(self):
        from domain.box_push_v1 import DOMAIN_IR, PROJECTION, project
        track = _CountingTrack(ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project))
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY),
            symbolic_track=track,
        )
        self.assertIs(loop.belief, track)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        executed = [e for e in episode.history.entries if e.execution is not None]
        self.assertEqual(track.recorded, len(executed))
        # one sync per cycle plus one per completed attempt (post_state), exactly as the
        # loop always synchronized
        self.assertEqual(track.synced, len(episode.history.entries) + len(executed))
        loop.env.close()

    def test_a_substitute_comparator_is_the_only_source_of_divergence_evidence(self):
        canned = ComparisonReport(findings=(ComparisonFinding(
            aspect=ComparedAspect.ACTION_CHOICE, severity=FindingSeverity.ATTENTION,
            divergence=TrackDivergence(
                kind=DivergenceKind.CONTRADICTION, message="canned by the test comparator",
                nl_view="test", symbolic_view="test"),
        ),))
        comparator = _CannedComparator(canned)
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_StubTrack([_proposal(GOTO)] * 40), comparator=comparator,
        )
        self.assertIs(loop.comparator, comparator)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertTrue(comparator.compared)
        executed = [e for e in episode.history.entries if e.execution is not None]
        self.assertTrue(executed)
        for entry in executed:
            self.assertEqual(entry.divergences, canned.divergences)
        # the comparator saw the call the loop then enacted (R3 invariant, kept)
        for (symbolic_call, _), entry in zip(comparator.compared, executed):
            self.assertEqual(symbolic_call, entry.selected_call)
        loop.env.close()

    def test_a_substitute_recovery_provider_decides_the_livelock_escape(self):
        """The provider's advice is what REQUEST_PROPOSAL enacts — through the same gates
        — and no provider means no advice, halting exactly as an empty proposal does."""
        seen = []

        def re_pose_with_the_other_agent(discrepancy):
            seen.append(discrepancy)
            call = discrepancy.call
            return (GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AgentId("agent_1"),),
                                      call.box, call.zone),)

        config = OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK)
        loop = build_loop(BoxPushV1Adapter(), TASK_DELIVER_BOTH, config,
                          recovery_provider=re_pose_with_the_other_agent)
        episode = loop.run()
        self.assertTrue(seen, "the injected provider was never consulted")
        entries = episode.history.entries
        requests = [i for i, e in enumerate(entries)
                    if e.decision is ExecutiveDecision.REQUEST_PROPOSAL]
        self.assertTrue(requests)
        enacted = entries[requests[0] + 1]
        self.assertIs(enacted.decision, ExecutiveDecision.EXECUTE)
        self.assertEqual(enacted.selected_call.agents, (AgentId("agent_1"),))
        self.assertIsNotNone(enacted.execution)            # went through the executor
        loop.env.close()

        silent = build_loop(BoxPushV1Adapter(), TASK_DELIVER_BOTH, config,
                            recovery_provider=lambda discrepancy: ())
        episode = silent.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("no recovery advice available", episode.reason)
        silent.env.close()

        none_injected = ExecutiveLoopManager(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH, config,
            domain=compose(TASK_DELIVER_BOTH).domain,
            symbolic_track=compose(TASK_DELIVER_BOTH).symbolic_track,
        )
        self.assertIsNone(none_injected.recovery_provider)
        episode = none_injected.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("no recovery advice available", episode.reason)
        none_injected.env.close()


if __name__ == "__main__":
    unittest.main()
