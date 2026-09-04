"""R5 substitutability tests (report Phase 5).

Phase 5 acceptance, made mechanical over the TEST-ONLY counter probe in
`tests/probe_counter.py`:

- the same runtime loop executes the probe domain without BoxPush imports or conditionals
  (`TestProbeFixtureIsBoxPushFree`: AST import/vocabulary scans of the fixture, a
  subprocess proof that a full probe episode under both policies loads no `domain`/
  `symbolic`/`nl`/`app`/backend module, and a scan that the runtime names no probe
  concept; `TestTheSameLoopRunsTheProbe`: both shipped policies drive the UNMODIFIED
  `ExecutiveLoopManager` to the accepted outcome shapes — designed physical failure of a
  symbolically applicable call, recovery through the same gates, NoPlan, budgets);
- the test-only domain does not imitate boxes, agents, zones, or geometry (the vocabulary
  scan; the probe's own types are integers and flags);
- unknown domain-specific evidence survives tracing and policy delivery unchanged
  (`TestUnknownDomainEvidenceSurvives`);
- contract tests for proposal acquisition order and comparison-before-decision
  (`TestAcquisitionOrderAndComparisonBeforeDecision`), typed decisions
  (`TestTypedDecisionsDriveTheProbe`), execution validation
  (`TestExecutionValidationGatesEveryCall`), and the R5 structural protocols being exactly
  what the runtime reads (`TestDomainTypeContractsAreWhatTheRuntimeReads`);
- composite-comparator aggregation with fake components, and no production composite
  (`TestCompositeComparatorAggregation`).

Offline and deterministic: no environment beyond the in-memory probe is touched, and the
one subprocess runs the same interpreter on the same tree with `-B`.
"""
import ast
import json
import os
import pathlib
import subprocess
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from runtime.executor import execute
from runtime.loop import EpisodeOutcome, ExecutiveLoopManager
from runtime.policies import AdvisoryTwoTrackPolicy, SymbolicPrimaryPolicy
from shared.contracts import (
    AdvisoryProposal,
    ComparedAspect,
    ComparisonFinding,
    ComparisonReport,
    DomainServices,
    Environment,
    Execute,
    FindingSeverity,
    Halt,
    OrchestrationPolicyContract,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    Replan,
    RequestProposal,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
    TrackRequest,
)
from shared.discrepancy import DiscrepancyKind
from shared.divergence import DivergenceKind, TrackDivergence
from shared.execution import ExecutionOutcome, ExecutionResult, FailureStateClass, StepAccounting
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError
from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.planner_result import NoPlan
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import MalformedCall, SymbolicallyInapplicable, UngroundedCall
from tests import probe_counter as probe
from tests.probe_counter import (
    COUNTER,
    INITIAL,
    STICKY_AT,
    TASK,
    CounterActionComparator,
    CounterDomainServices,
    CounterEnvironment,
    CounterProposal,
    CounterState,
    CounterSymbolicTrack,
    CounterTask,
    FakeReasoningTrack,
    build_probe_loop,
    compose_probe,
    increment,
    project,
    smooth_environment,
    sticky_environment,
    stop,
)

_FIXTURE = pathlib.Path(_REPO_ROOT, "tests", "probe_counter.py")
_RUNTIME_DIR = pathlib.Path(_REPO_ROOT, "runtime")
_PRODUCTION_DIRS = tuple(pathlib.Path(_REPO_ROOT, d) for d in ("shared", "runtime", "app"))

PRIMARY = OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY)
ADVISORY = OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK)

INC1 = increment(COUNTER, 1)
INC2 = increment(COUNTER, 2)
STOP = stop(COUNTER)

#: the accepted probe shapes (the counter analogue of the R0 characterization)
PRIMARY_DECISIONS = [ExecutiveDecision.EXECUTE] * 5 + [ExecutiveDecision.HALT]
ADVISORY_DECISIONS = (
    [ExecutiveDecision.EXECUTE] * 5
    + [ExecutiveDecision.REQUEST_PROPOSAL, ExecutiveDecision.EXECUTE, ExecutiveDecision.EXECUTE]
)


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module, node.lineno


def _sources(*dirs):
    for directory in dirs:
        for path in sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts):
            yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _decisions(episode):
    return [e.decision for e in episode.history.entries]


def _executed(episode):
    return [e for e in episode.history.entries if e.execution is not None]


# ── acceptance 1: no BoxPush imports or conditionals ────────────────────────────────

class TestProbeFixtureIsBoxPushFree(unittest.TestCase):
    ALLOWED_ROOTS = frozenset({
        "__future__", "hashlib", "json", "dataclasses", "enum", "typing", "shared", "runtime",
    })
    FORBIDDEN_ROOTS = frozenset({
        "domain", "symbolic", "nl", "app", "functional_layer", "middleware_layer",
        "model_layer", "box_push_v1_adapter", "box_push_v1_run", "box_push_env",
        "multi_agent_box_push_env", "skill_executor_push", "shared_skills",
    })
    #: BoxPush/geometry vocabulary the probe must not imitate (report Phase 5 acceptance 2)
    BOXPUSH_TOKENS = frozenset({
        "agent", "agents", "box", "boxes", "zone", "zones", "grid", "cell", "cells",
        "position", "facing", "direction", "wall", "walls", "pose", "push", "deliver",
        "delivered", "delivery", "geometry", "move", "moves", "row", "rows", "col", "cols",
        "coord", "coords", "adjacent", "occupied", "obstacle", "navigate", "reach",
    })

    def test_fixture_imports_only_stdlib_shared_and_runtime(self):
        tree = ast.parse(_FIXTURE.read_text(encoding="utf-8"))
        seen = set()
        for module, lineno in _imports(tree):
            root = module.split(".")[0]
            seen.add(root)
            with self.subTest(module=module):
                self.assertNotIn(root, self.FORBIDDEN_ROOTS,
                                 f"probe_counter.py:{lineno} imports {module!r}")
                self.assertIn(root, self.ALLOWED_ROOTS,
                              f"probe_counter.py:{lineno} imports {module!r} outside the "
                              f"declared surface")
        self.assertIn("runtime", seen)                  # it really composes the product loop
        self.assertIn("shared", seen)

    def test_fixture_names_no_boxpush_vocabulary(self):
        import re
        tree = ast.parse(_FIXTURE.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                names.add(node.name)
                if isinstance(node, ast.FunctionDef):
                    for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                        names.add(arg.arg)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        for name in sorted(names):
            spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
            for segment in re.split(r"[_\d]+", spaced.lower()):
                self.assertNotIn(segment, self.BOXPUSH_TOKENS,
                                 f"probe identifier {name!r} carries BoxPush vocabulary")

    def test_the_vocabulary_scan_is_not_vacuous(self):
        tree = ast.parse("def f(box, agent_id):\n    return box.zone, agent_id\n")
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        args = {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                for a in n.args.args}
        self.assertTrue(attrs & self.BOXPUSH_TOKENS)
        self.assertTrue({"box"} <= args)

    def test_a_full_probe_episode_loads_no_boxpush_module(self):
        """The strongest form of acceptance 1: in a fresh interpreter, the probe drives
        the product loop under BOTH policies, and afterwards `sys.modules` holds no module
        rooted at the BoxPush DOMAIN PACKAGES — `domain`, `symbolic`, `nl`, `app`, the
        adapter, the backend, or the legacy packages. Any EXECUTED import of those — direct,
        lazy, string-based, or conditional — surfaces here; an import in a branch the
        episode never executes is caught by the static R4 allowlist instead. Scope note:
        `shared` is allowed, and the frozen V1 record types under it (`shared.skills`,
        `shared.state_snapshot`, `shared.task`, `shared.execution`) DO load — they are the
        typed channels the contracts are built on, not the BoxPush domain."""
        script = (
            "import sys, json\n"
            "from tests import probe_counter as p\n"
            "from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy\n"
            "out = {}\n"
            "for pol in OrchestrationPolicy:\n"
            "    loop = p.build_probe_loop(p.sticky_environment(), p.TASK, OrchestrationConfig(policy=pol),\n"
            "                              nl_track=p.FakeReasoningTrack())\n"
            "    out[pol.value] = loop.run().outcome.value\n"
            f"forbidden = {sorted(self.FORBIDDEN_ROOTS)!r}\n"
            "loaded = sorted(m for m in sys.modules if m.split('.')[0] in forbidden)\n"
            "print(json.dumps({'outcomes': out, 'loaded': loaded, 'runtime': 'runtime.loop' in sys.modules}))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=_REPO_ROOT,
            env={**os.environ, "PYTHONPATH": _REPO_ROOT},
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertTrue(report["runtime"], "the product runtime was not the loop that ran")
        self.assertEqual(report["outcomes"], {
            "symbolic_primary": "halted_repeated_failure",
            "advisory_two_track": "goal_reached",
        })
        self.assertEqual(report["loaded"], [], f"BoxPush modules were imported: {report['loaded']}")

    def test_the_runtime_and_contracts_name_no_probe_concept(self):
        """No production component contains a special case for the probe (report Phase 5:
        "no production component should contain a special case for it")."""
        for path, tree in _sources(*_PRODUCTION_DIRS):
            for node in ast.walk(tree):
                name = getattr(node, "id", None) or getattr(node, "attr", None) or (
                    node.name if isinstance(node, (ast.ClassDef, ast.FunctionDef)) else None)
                if name is None:
                    continue
                self.assertNotIn("counter", name.lower(),
                                 f"{path.relative_to(_REPO_ROOT)}:{node.lineno} names {name!r}")
                self.assertNotIn("probe", name.lower(),
                                 f"{path.relative_to(_REPO_ROOT)}:{node.lineno} names {name!r}")


class TestProbeComponentsSatisfyTheContracts(unittest.TestCase):
    def test_every_probe_component_is_a_contract_instance(self):
        components = compose_probe(TASK)
        env = sticky_environment()
        self.assertIsInstance(env, Environment)
        self.assertIsInstance(components.domain, DomainServices)
        self.assertIsInstance(components.symbolic_track, SymbolicTrack)
        self.assertIsInstance(components.comparator, ProposalComparator)
        self.assertIsInstance(components.recovery_provider, RecoveryProvider)
        self.assertIsInstance(FakeReasoningTrack(), ReasoningTrack)
        self.assertIsInstance(INITIAL, RuntimeState)
        self.assertIsInstance(INC1, RuntimeCall)
        self.assertIsInstance(TASK, TaskContract)
        self.assertIsInstance(CounterProposal(call=INC1), AdvisoryProposal)
        # the static witnesses are real functions over real instances
        self.assertIs(probe.environment_conforms(env), env)
        self.assertIs(probe.domain_services_conform(components.domain), components.domain)
        self.assertIs(probe.state_conforms(INITIAL), INITIAL)
        self.assertIs(probe.call_conforms(INC1), INC1)
        self.assertIs(probe.task_conforms(TASK), TASK)

    def test_the_frozen_v1_types_satisfy_the_same_structural_protocols(self):
        """The R5 protocols describe what the runtime requires; the accepted V1 types meet
        them unchanged (nothing in `shared/` or `nl/` was edited for R5). Imported locally:
        this is the one place the R5 module touches BoxPush, and only to check conformance."""
        from domain.box_push_v1 import AGENT_0, BOX_LIGHT, DELIVERY_ZONE, TASK_DELIVER_BOTH, initial_state
        from nl.track import NLProposal
        from shared.skills import GroundedSkillCall, SkillName
        self.assertIsInstance(initial_state(), RuntimeState)
        self.assertIsInstance(
            GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE), RuntimeCall)
        self.assertIsInstance(TASK_DELIVER_BOTH, TaskContract)
        self.assertIsInstance(
            NLProposal(call=None, malformed=MalformedCall(reason="x"), coverage=None,
                       confidence=None, repaired=False),
            AdvisoryProposal)

    def test_plan_reads_the_state_for_identity_only(self):
        """Decision 6 at the probe seam (the BoxPush bundle has the same pin): the
        authoritative state passed to `plan` fixes the counter IDENTITY and nothing else —
        a state with a different value/flag yields the identical plan for the same
        symbolic state."""
        services = CounterDomainServices(TASK)
        symbolic = project(INITIAL)
        for other in (CounterState(COUNTER, 9, 4), CounterState(COUNTER, 4, 4, stopped=True),
                      CounterState(COUNTER, 0, 4, tick=7)):
            self.assertEqual(services.plan(symbolic, other), services.plan(symbolic, INITIAL))

    def test_the_probe_state_and_call_are_immutable(self):
        import dataclasses
        with self.assertRaises(dataclasses.FrozenInstanceError):
            INITIAL.value = 3
        with self.assertRaises(dataclasses.FrozenInstanceError):
            INC1.amount = 2
        self.assertNotEqual(INITIAL.world_key(), CounterState(COUNTER, 1, 4).world_key())
        # episode bookkeeping is excluded from the world key, like the V1 snapshot's counters
        self.assertEqual(INITIAL.world_key(), CounterState(COUNTER, 0, 4, tick=9).world_key())


# ── the same loop runs the probe ────────────────────────────────────────────────────

class _StrictServicesProxy:
    """Delegates to the probe bundle, records every consultation, refuses anything outside
    the DomainServices contract (the R4 proxy, re-used against a foreign domain)."""

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


class _StrictEnv:
    """Refuses every environment method except the three the executive layer is allowed to
    depend on: `reset`, `export_full_state`, `execute_skill`."""

    ALLOWED = ("reset", "export_full_state", "execute_skill")

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise AssertionError(f"the runtime used environment method {name!r}")
        target = getattr(self._inner, name)

        def recorded(*args, **kwargs):
            self.calls.append(name)
            return target(*args, **kwargs)
        return recorded


class TestTheSameLoopRunsTheProbe(unittest.TestCase):
    def test_symbolic_primary_halts_at_the_designed_physical_obstacle(self):
        """The counter analogue of the accepted BoxPush livelock: an applicable
        Increment(1) fails physically at the sticky value, the failure is typed evidence
        on the executed entry, the world stays where the BACKEND left it, and the
        conservative policy halts with the discrepancy history after the threshold."""
        env = sticky_environment()
        loop = build_probe_loop(env, TASK, PRIMARY)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("failed 3x under SYMBOLIC_PRIMARY", episode.reason)
        self.assertEqual(_decisions(episode), PRIMARY_DECISIONS)
        self.assertEqual(len(episode.discrepancies), 3)
        for discrepancy in episode.discrepancies:
            self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)
            self.assertEqual(discrepancy.call, INC1)
        failing = [e for e in _executed(episode) if e.execution.outcome is not ExecutionOutcome.SUCCESS]
        self.assertEqual(len(failing), 3)
        for entry in failing:
            self.assertEqual(entry.pre_state.value, STICKY_AT)
            self.assertEqual(entry.discrepancies, (episode.discrepancies[failing.index(entry)],))
            self.assertEqual(entry.execution.pre_state.same_world(entry.execution.post_state), True)
        self.assertEqual(loop.executive_steps_charged, 5)
        self.assertEqual(loop.primitive_steps_charged, 5)
        final = env.export_full_state()
        self.assertEqual((final.value, final.stopped), (STICKY_AT, False))
        self.assertEqual(env.executed, [INC1] * 5)

    def test_advisory_recovers_through_the_same_gates_and_executor(self):
        env = sticky_environment()
        proxy = _StrictServicesProxy(CounterDomainServices(TASK))
        loop = build_probe_loop(env, TASK, ADVISORY, domain=proxy)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(_decisions(episode), ADVISORY_DECISIONS)
        entries = episode.history.entries
        request, enacted, final = entries[5], entries[6], entries[7]
        self.assertIs(request.decision, ExecutiveDecision.REQUEST_PROPOSAL)
        self.assertEqual(request.selected_call, INC1)
        self.assertIsNone(request.execution)
        self.assertEqual(enacted.selected_call, INC2)         # the provider's advice
        self.assertEqual(enacted.nl_proposal, INC2)           # typed recovery provenance
        self.assertIsNotNone(enacted.execution)               # through the executor
        self.assertIs(enacted.execution.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(final.selected_call, STOP)
        # every executed cycle consulted the domain in the frozen order, the recovery
        # enactment included: plan -> head verdict -> ground -> evaluate -> predict -> monitor
        cycle = ["plan", "evaluate", "ground", "evaluate", "predict", "monitor"]
        self.assertEqual(proxy.calls, cycle * 7)
        self.assertEqual(env.executed, [INC1] * 5 + [INC2, STOP])
        self.assertEqual(loop.executive_steps_charged, 7)
        self.assertEqual(loop.primitive_steps_charged, 8)
        self.assertTrue(TASK.is_satisfied_by(env.export_full_state()))

    def test_a_smooth_environment_reaches_the_goal_with_matching_predictions(self):
        """Successful deterministic transitions match the recorded predictions on BOTH
        Decision-13 bases (the probe's projection is exact)."""
        for config in (PRIMARY, ADVISORY):
            with self.subTest(policy=config.policy.value):
                env = smooth_environment()
                episode = build_probe_loop(env, TASK, config).run()
                self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
                self.assertEqual(_decisions(episode), [ExecutiveDecision.EXECUTE] * 5)
                self.assertEqual(episode.discrepancies, ())
                for entry in _executed(episode):
                    self.assertEqual(entry.predicted_world_key, entry.post_state.world_key())
                    self.assertEqual(entry.predicted_symbolic_key,
                                     project(entry.post_state).symbolic_key())
                self.assertEqual(env.executed, [INC1] * 4 + [STOP])

    def test_noplan_is_a_semantic_halt_not_a_fault(self):
        env = CounterEnvironment(CounterState(COUNTER, value=6, target=4))
        episode = build_probe_loop(env, TASK, PRIMARY).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_NO_PLAN)
        (entry,) = episode.history.entries
        self.assertIsInstance(entry.symbolic_result, NoPlan)
        self.assertIs(entry.decision, ExecutiveDecision.HALT)
        self.assertEqual(entry.faults, ())
        self.assertEqual(env.executed, [])

    def test_budgets_bound_the_probe_episode(self):
        env = smooth_environment()
        loop = build_probe_loop(env, TASK, OrchestrationConfig(executive_step_budget=2))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(len(_executed(episode)), 2)
        self.assertEqual(env.export_full_state().value, 2)

    def test_the_runtime_uses_only_the_three_authoritative_environment_methods(self):
        env = _StrictEnv(sticky_environment())
        episode = build_probe_loop(env, TASK, ADVISORY, nl_track=FakeReasoningTrack()).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(env.calls[0], "reset")
        self.assertEqual(set(env.calls), set(_StrictEnv.ALLOWED))
        # one export per cycle (eight cycles incl. the final goal check), never a
        # re-export after an attempt: the result's post_state is reused
        self.assertEqual(env.calls.count("export_full_state"), 8)
        self.assertEqual(env.calls.count("execute_skill"), 7)

    def test_the_probe_composition_root_injects_by_identity(self):
        components = compose_probe(TASK)
        provider = lambda discrepancy: ()                       # noqa: E731
        loop = build_probe_loop(
            sticky_environment(), TASK, ADVISORY,
            domain=components.domain, symbolic_track=components.symbolic_track,
            comparator=components.comparator, recovery_provider=provider,
        )
        self.assertIsInstance(loop, ExecutiveLoopManager)
        self.assertIs(loop.domain, components.domain)
        self.assertIs(loop.belief, components.symbolic_track)
        self.assertIs(loop.comparator, components.comparator)
        self.assertIs(loop.recovery_provider, provider)
        self.assertIsInstance(loop.policy, AdvisoryTwoTrackPolicy)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("no recovery advice available", episode.reason)


# ── acquisition order and comparison before the decision ───────────────────────────

class _Recorder:
    """One shared event log across a recording track, comparator, and policy."""

    def __init__(self):
        self.events = []
        self.decide_contexts = []
        self.compared = []


class _RecordingTrack(FakeReasoningTrack):
    def __init__(self, recorder, script=None):
        super().__init__(script)
        self._recorder = recorder

    def propose(self, task, /):
        self._recorder.events.append("propose")
        return super().propose(task)


class _RecordingComparator(CounterActionComparator):
    def __init__(self, recorder):
        self._recorder = recorder

    def compare(self, symbolic_call, nl_proposal, /):
        report = super().compare(symbolic_call, nl_proposal)
        self._recorder.events.append("compare")
        self._recorder.compared.append((symbolic_call, nl_proposal, report))
        return report


class _RecordingAdvisoryPolicy(AdvisoryTwoTrackPolicy):
    def __init__(self, recorder, **kw):
        super().__init__(**kw)
        self._recorder = recorder

    def required_inputs(self, context, /):
        self._recorder.events.append("required_inputs")
        return super().required_inputs(context)

    def decide(self, context, /):
        self._recorder.events.append("decide")
        self._recorder.decide_contexts.append(context)
        return super().decide(context)


class TestAcquisitionOrderAndComparisonBeforeDecision(unittest.TestCase):
    ENACT = ["required_inputs", "propose", "compare", "decide"]
    REQUEST = ["required_inputs", "decide"] + ENACT     # escape, then the standing advice

    def _run(self, script=None):
        recorder = _Recorder()
        track = _RecordingTrack(recorder, script)
        loop = build_probe_loop(
            sticky_environment(), TASK, ADVISORY, nl_track=track,
            policy=_RecordingAdvisoryPolicy(recorder, repeated_failure_threshold=3),
            comparator=_RecordingComparator(recorder),
        )
        return recorder, track, loop.run()

    def test_the_exact_event_order_over_the_whole_episode(self):
        recorder, track, episode = self._run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(recorder.events, self.ENACT * 5 + self.REQUEST + self.ENACT)
        self.assertEqual(len(track.proposed), 7)                  # once per enacting decision

    def test_the_policy_decides_with_the_very_objects_the_track_and_comparator_produced(self):
        recorder, track, _ = self._run()
        enacting = [c for c in recorder.decide_contexts if c.nl_proposal is not None]
        self.assertEqual(len(enacting), 7)
        for context, proposal, (symbolic_call, compared_proposal, report) in zip(
            enacting, track.proposed, recorder.compared
        ):
            self.assertIs(context.nl_proposal, proposal)
            self.assertIs(compared_proposal, proposal)
            self.assertIs(context.comparison, report)
        # the non-enacting escape decision saw neither
        escapes = [c for c in recorder.decide_contexts if c.nl_proposal is None]
        self.assertEqual(len(escapes), 1)
        self.assertIsNone(escapes[0].comparison)

    def test_the_compared_symbolic_side_is_the_call_then_enacted(self):
        recorder, _, episode = self._run()
        executed = _executed(episode)
        self.assertEqual(len(recorder.compared), len(executed))
        for (symbolic_call, _, _), entry in zip(recorder.compared, executed):
            self.assertEqual(symbolic_call, entry.selected_call)
        # the recovery enactment compared the STANDING advice, not the plan head
        self.assertEqual(recorder.compared[5][0], INC2)

    def test_disagreement_is_evidence_the_shipped_policy_records_but_does_not_follow(self):
        contrary = [CounterProposal(call=STOP, evidence=("contrary",))] * 10
        recorder, _, episode = self._run(script=contrary)
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        executed = _executed(episode)
        for entry in executed[:5]:
            self.assertEqual([d.kind for d in entry.divergences], [DivergenceKind.CONTRADICTION])
            self.assertEqual(entry.nl_proposal, STOP)             # recorded, not enacted
            self.assertEqual(entry.selected_call, INC1)
        self.assertEqual(executed[-1].divergences, ())            # Stop agreed at the end

    def test_symbolic_primary_never_acquires_but_still_feeds_the_observer(self):
        class _ExplodingTrack(FakeReasoningTrack):
            def propose(self, task, /):
                raise AssertionError("SYMBOLIC_PRIMARY must never consult propose()")
        track = _ExplodingTrack()
        episode = build_probe_loop(sticky_environment(), TASK, PRIMARY, nl_track=track).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertEqual(len(track.observations), 1 + len(_executed(episode)))
        labels = [label for _, label, _ in track.observations[1:]]
        self.assertEqual(labels, [str(INC1.skill)] * 5)          # the RuntimeCall.skill label
        self.assertEqual([o for _, _, o in track.observations[1:]],
                         [ExecutionOutcome.SUCCESS] * 2 + [ExecutionOutcome.FAILURE] * 3)

    def test_an_acquisition_fault_is_pre_decision_and_fail_closed(self):
        class _RaisingTrack(FakeReasoningTrack):
            def propose(self, task, /):
                raise RuntimeError("probe LM seam down")
        env = sticky_environment()
        episode = build_probe_loop(env, TASK, ADVISORY, nl_track=_RaisingTrack()).run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (entry,) = episode.history.entries
        (fault,) = entry.faults
        self.assertIs(fault.kind, FaultKind.NL_TRACK_FAILURE)
        self.assertEqual(fault.stage, "propose")
        self.assertTrue(fault.arises_before_execution)
        self.assertIsNone(entry.decision)
        self.assertIsNone(entry.selected_call)
        self.assertIsNone(entry.execution)
        self.assertEqual(entry.divergences, ())                   # no manufactured divergence
        self.assertEqual(env.executed, [])


# ── typed decisions ─────────────────────────────────────────────────────────────────

class _ScriptedPolicy:
    """A pure policy answering from a script; requests no track inputs."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.seen = []

    def required_inputs(self, context, /):
        return TrackRequest()

    def decide(self, context, /):
        self.seen.append(context)
        if not self._decisions:
            raise AssertionError("scripted policy exhausted")
        decision = self._decisions.pop(0)
        return decision(context) if callable(decision) else decision


class TestTypedDecisionsDriveTheProbe(unittest.TestCase):
    def test_a_scripted_policy_is_a_contract_instance(self):
        self.assertIsInstance(_ScriptedPolicy([]), OrchestrationPolicyContract)

    def test_halt_without_a_call_is_the_no_plan_outcome(self):
        env = smooth_environment()
        episode = build_probe_loop(env, TASK, policy=_ScriptedPolicy([Halt(reason="probe halt")])).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_NO_PLAN)
        self.assertEqual(episode.reason, "probe halt")
        self.assertEqual(env.executed, [])

    def test_halt_with_a_call_is_the_repeated_failure_outcome(self):
        episode = build_probe_loop(
            smooth_environment(), TASK, policy=_ScriptedPolicy([Halt(reason="about INC1", call=INC1)]),
        ).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertEqual(episode.history.entries[0].selected_call, INC1)

    def test_replan_is_free_and_bounded(self):
        env = smooth_environment()
        config = OrchestrationConfig(max_rejections_per_cycle=3)
        loop = build_probe_loop(env, TASK, config, policy=_ScriptedPolicy([Replan(reason="again")] * 10))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("pre-executor rejections", episode.reason)
        self.assertEqual(loop.executive_steps_charged, 0)
        self.assertEqual(env.executed, [])

    def test_execute_reaches_the_executor_exactly_once_per_cycle(self):
        env = smooth_environment()
        policy = _ScriptedPolicy([lambda c: Execute(call=c.preliminary.planner_result.plan[0])] * 5)
        episode = build_probe_loop(env, TASK, policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(env.executed, [INC1] * 4 + [STOP])

    def test_request_proposal_enacts_the_providers_advice_through_the_gates(self):
        env = sticky_environment()
        head = lambda c: Execute(call=c.preliminary.planner_result.plan[0])   # noqa: E731
        standing = lambda c: Execute(call=c.preliminary.standing_recovery)    # noqa: E731
        policy = _ScriptedPolicy(
            [head] * 3                                            # 2 successes, 1 failure
            + [lambda c: RequestProposal(call=INC1, reason="escape")]
            + [standing, head],
        )
        episode = build_probe_loop(env, TASK, policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(env.executed, [INC1] * 3 + [INC2, STOP])
        self.assertEqual(_decisions(episode)[3:5],
                         [ExecutiveDecision.REQUEST_PROPOSAL, ExecutiveDecision.EXECUTE])

    def test_standing_recovery_is_matched_by_value_not_identity(self):
        """`RuntimeCall` requires value equality: a policy enacting an EQUAL but distinct
        call object on the standing cycle is still the recovery enactment (typed
        recovery provenance on `nl_proposal`) and consumes the standing advice."""
        env = sticky_environment()
        head = lambda c: Execute(call=c.preliminary.planner_result.plan[0])   # noqa: E731
        fresh_equal = lambda c: Execute(                                       # noqa: E731
            call=increment(c.preliminary.standing_recovery.counter_id,
                           c.preliminary.standing_recovery.amount))
        policy = _ScriptedPolicy(
            [head] * 3 + [lambda c: RequestProposal(call=INC1, reason="escape")]
            + [fresh_equal, head],
        )
        episode = build_probe_loop(env, TASK, policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        enacted = episode.history.entries[4]
        self.assertEqual(enacted.selected_call, INC2)
        self.assertEqual(enacted.nl_proposal, INC2)                # provenance by value
        self.assertIsNone(policy.seen[-1].preliminary.standing_recovery)  # consumed

    def test_request_proposal_without_evidence_halts_with_no_advice(self):
        env = smooth_environment()
        policy = _ScriptedPolicy([RequestProposal(call=INC1, reason="premature")])
        episode = build_probe_loop(env, TASK, policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIn("no recovery advice available", episode.reason)
        self.assertEqual(env.executed, [])


# ── execution validation ────────────────────────────────────────────────────────────

class TestExecutionValidationGatesEveryCall(unittest.TestCase):
    def test_an_ungrounded_recovery_call_faults_before_the_executor(self):
        """The ghost call is ALSO symbolically inapplicable (amount 9 overshoots), so the
        §19.1 item 5 ordering is asserted on the routing itself: MISSING_GROUNDING, never
        a quiet REPLAN verdict."""
        ghost = increment("ghost", 9)
        env = sticky_environment()
        loop = build_probe_loop(env, TASK, ADVISORY, recovery_provider=lambda d: (ghost,))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        last = episode.history.entries[-1]
        self.assertEqual(last.selected_call, ghost)
        self.assertIsInstance(last.validation, UngroundedCall)
        self.assertEqual([f.kind for f in last.faults], [FaultKind.MISSING_GROUNDING])
        self.assertIsNone(last.execution)
        self.assertNotIn(ghost, env.executed)
        self.assertEqual(loop.executive_steps_charged, 5)         # the ghost cost nothing

    def test_an_inapplicable_recovery_call_is_replanned_at_zero_cost_and_liveness_bounded(self):
        overshoot = increment(COUNTER, 9)
        env = sticky_environment()
        loop = build_probe_loop(env, TASK, ADVISORY, recovery_provider=lambda d: (overshoot,))
        episode = loop.run()
        replans = [e for e in episode.history.entries if e.decision is ExecutiveDecision.REPLAN]
        self.assertTrue(replans)
        for entry in replans:
            self.assertEqual(entry.selected_call, overshoot)
            self.assertIsInstance(entry.validation, SymbolicallyInapplicable)
            self.assertIsNone(entry.execution)
        self.assertNotIn(overshoot, env.executed)
        # the stale advice never becomes progress: the loop's liveness guard ends it
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("liveness guard", episode.reason)
        self.assertEqual(loop.executive_steps_charged, 5)

    def test_a_policy_cannot_bypass_the_gates(self):
        env = smooth_environment()
        policy = _ScriptedPolicy([Execute(call=increment(COUNTER, 9))] * 10)
        loop = build_probe_loop(env, TASK, policy=policy)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)     # liveness guard
        self.assertEqual(env.executed, [])
        self.assertEqual(loop.executive_steps_charged, 0)
        for entry in episode.history.entries[:-1]:
            self.assertIsInstance(entry.validation, SymbolicallyInapplicable)

        env = smooth_environment()
        policy = _ScriptedPolicy([Execute(call=increment("ghost", 1))])
        episode = build_probe_loop(env, TASK, policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertEqual([f.kind for f in episode.history.entries[0].faults],
                         [FaultKind.MISSING_GROUNDING])
        self.assertEqual(env.executed, [])

    def test_request_proposal_consults_the_last_discrepancy_for_that_call(self):
        """§19.1 item 1: the provider is handed the LAST discrepancy for the ESCAPED call —
        not the first one for it, and not the last one overall. The probe's discrepancy
        message carries the pre-attempt value, which makes the selection observable."""
        class _AlsoStuckOnTwo(CounterEnvironment):
            """Increment(1) sticks at 1 and 3; Increment(2) additionally sticks at 3."""
            def execute_skill(self, call, /):
                pre = self.export_full_state()
                if call == INC2 and pre.value == 3:
                    post = CounterState(pre.counter_id, pre.value, pre.target, pre.stopped, pre.tick + 1)
                    self._state = post
                    self.executed.append(call)
                    return ExecutionResult(
                        call=call, outcome=ExecutionOutcome.FAILURE, pre_state=pre, post_state=post,
                        accounting=StepAccounting(executive_steps=1, primitive_steps=1),
                        failure_class=FailureStateClass.UNCHANGED, detail="stuck",
                    )
                return super().execute_skill(call)
        env = _AlsoStuckOnTwo(CounterState(COUNTER, 0, 10), sticky_at=(1, 3))
        seen = []

        def provider(discrepancy):
            seen.append(discrepancy)
            return ()
        script = [
            lambda c: Execute(call=INC1),             # 0 -> 1
            lambda c: Execute(call=INC1),             # fails at 1   (FIRST for INC1)
            lambda c: Execute(call=INC2),             # 1 -> 3
            lambda c: Execute(call=INC1),             # fails at 3   (LAST for INC1)
            lambda c: Execute(call=INC2),             # fails at 3   (last overall, other call)
            lambda c: RequestProposal(call=INC1, reason="escape"),
        ]
        episode = build_probe_loop(env, TASK, policy=_ScriptedPolicy(script),
                                   recovery_provider=provider).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertEqual([d.call for d in episode.discrepancies], [INC1, INC1, INC2])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].call, INC1)
        self.assertIn("counter held at 3", seen[0].message)
        self.assertIs(seen[0], episode.discrepancies[1])

    def test_the_executor_returns_the_environments_typed_rejections_verbatim(self):
        env = smooth_environment()
        env.reset()
        self.assertIsInstance(execute(env, increment("ghost", 1)), UngroundedCall)
        self.assertIsInstance(execute(env, object()), MalformedCall)
        self.assertEqual(env.executed, [])

    def test_a_mid_execution_fault_is_charged_from_provenance(self):
        class _CaseCEnv(CounterEnvironment):
            def execute_skill(self, call, /):
                raise InfrastructureFaultError(InfrastructureFault(
                    kind=FaultKind.BACKEND_API_EXCEPTION, message="probe crashed mid-attempt",
                    detail="primitive_steps_before_failure=3",
                ))
        loop = build_probe_loop(_CaseCEnv(INITIAL), TASK)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (entry,) = episode.history.entries
        self.assertIsNone(entry.execution)
        self.assertEqual(loop.executive_steps_charged, 1)
        self.assertEqual(loop.primitive_steps_charged, 3)

    def test_a_completed_attempt_that_then_faults_keeps_its_first_class_record(self):
        class _CaseAEnv(CounterEnvironment):
            def execute_skill(self, call, /):
                result = super().execute_skill(call)
                raise InfrastructureFaultError(InfrastructureFault(
                    kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                    message="probe post-flight violation",
                ), result=result)
        env = _CaseAEnv(INITIAL)
        loop = build_probe_loop(env, TASK)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (entry,) = episode.history.entries
        self.assertIsNotNone(entry.execution)
        self.assertEqual(entry.post_state.value, 1)
        self.assertEqual(loop.executive_steps_charged, 1)

    def test_the_environment_refuses_use_before_reset_and_after_terminal(self):
        env = smooth_environment()
        with self.assertRaises(InfrastructureFaultError) as raised:
            env.execute_skill(INC1)
        self.assertTrue(raised.exception.fault.message.startswith("refused:"))
        episode = build_probe_loop(env, TASK).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertTrue(env.is_terminal())
        with self.assertRaises(InfrastructureFaultError) as raised:
            env.execute_skill(INC1)
        self.assertIn("terminal", raised.exception.fault.message)

    def test_a_monitor_value_error_is_wrapped_into_the_typed_fault(self):
        foreign = CounterDomainServices(CounterTask("t", "foreign", counter_id="other"))
        services = CounterDomainServices(TASK)
        # plan/ground/evaluate/predict from the matching bundle, monitor from the foreign one
        class _Mixed:
            model_version = services.model_version
            plan, ground, evaluate, predict = (services.plan, services.ground,
                                               services.evaluate, services.predict)
            monitor = foreign.monitor
        episode = build_probe_loop(smooth_environment(), TASK, domain=_Mixed()).run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (entry,) = episode.history.entries
        self.assertEqual([f.kind for f in entry.faults], [FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE])
        self.assertIn("untyped ValueError", entry.faults[0].message)
        self.assertIsNotNone(entry.execution)                     # the attempt stands


# ── unknown domain evidence survives ────────────────────────────────────────────────

class _CapturingPolicy(SymbolicPrimaryPolicy):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.states = []
        self.proposals = []

    def required_inputs(self, context, /):
        return TrackRequest(nl_proposal=True)

    def decide(self, context, /):
        self.states.append(context.preliminary.state)
        self.proposals.append(context.nl_proposal)
        return super().decide(context)


class _ExportRecordingEnv(CounterEnvironment):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.exported = []

    def export_full_state(self):
        state = super().export_full_state()
        self.exported.append(state)
        return state


class TestUnknownDomainEvidenceSurvives(unittest.TestCase):
    def test_state_objects_reach_the_trace_and_the_policy_by_identity(self):
        env = _ExportRecordingEnv(INITIAL, sticky_at=STICKY_AT)
        policy = _CapturingPolicy(repeated_failure_threshold=3)
        script = [CounterProposal(call=INC1, evidence=(f"tick-note-{i}",)) for i in range(10)]
        episode = build_probe_loop(env, TASK, PRIMARY, nl_track=FakeReasoningTrack(script),
                                   policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        entries = episode.history.entries
        self.assertEqual(len(entries), len(env.exported))        # one export per cycle
        for entry, exported, seen in zip(entries, env.exported, policy.states):
            self.assertIs(entry.pre_state, exported)
            self.assertIs(seen, exported)
        # the domain's own bookkeeping field is carried untouched
        self.assertEqual([e.pre_state.tick for e in entries], list(range(len(entries))))

    def test_domain_discrepancy_evidence_is_recorded_verbatim(self):
        episode = build_probe_loop(sticky_environment(), TASK, PRIMARY).run()
        failing = [e for e in _executed(episode) if e.discrepancies]
        self.assertEqual(len(failing), 3)
        for entry in failing:
            (discrepancy,) = entry.discrepancies
            self.assertTrue(discrepancy.message.startswith("probe:"))
            self.assertIn(discrepancy, episode.discrepancies)
            self.assertEqual(discrepancy.canonical()["message"], discrepancy.message)
            self.assertEqual(str(discrepancy.model_version), "counter-probe.r0")

    def test_proposal_evidence_reaches_the_policy_and_the_residual_unchanged(self):
        marker = ("hint:alpha", "hint:beta")
        script = [CounterProposal(call=STOP, evidence=marker)] * 10
        policy = _CapturingPolicy(repeated_failure_threshold=3)
        episode = build_probe_loop(smooth_environment(), TASK, PRIMARY,
                                   nl_track=FakeReasoningTrack(script), policy=policy).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        for proposal in policy.proposals:
            self.assertIs(proposal, script[0])
            self.assertEqual(proposal.evidence, marker)
        for entry in _executed(episode)[:-1]:                     # Increments contradict Stop
            (divergence,) = entry.divergences
            self.assertIs(divergence.kind, DivergenceKind.CONTRADICTION)
            self.assertEqual(divergence.residual, marker)
            self.assertEqual(entry.canonical()["divergences"][0]["residual"], list(marker))

    def test_a_reactive_policy_can_act_on_evidence_the_runtime_never_read(self):
        class _EvidenceReactivePolicy(_CapturingPolicy):
            def decide(self, context, /):
                proposal = context.nl_proposal
                if proposal is not None and "abort" in proposal.evidence:
                    return Halt(reason="advisory evidence says abort")
                return super().decide(context)
        script = [CounterProposal(call=INC1, evidence=("fine",)),
                  CounterProposal(call=INC1, evidence=("abort",))]
        env = smooth_environment()
        episode = build_probe_loop(env, TASK, PRIMARY, nl_track=FakeReasoningTrack(script),
                                   policy=_EvidenceReactivePolicy(repeated_failure_threshold=3)).run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_NO_PLAN)
        self.assertEqual(episode.reason, "advisory evidence says abort")
        self.assertEqual(env.executed, [INC1])
        # and the runtime indeed never reads such a member
        for path, tree in _sources(_RUNTIME_DIR):
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            self.assertNotIn("evidence", attrs, path.name)

    def test_the_trace_serializes_the_probe_without_a_domain_adapter(self):
        for config in (PRIMARY, ADVISORY):
            with self.subTest(policy=config.policy.value):
                episode = build_probe_loop(sticky_environment(), TASK, config,
                                           nl_track=FakeReasoningTrack()).run()
                rows = [e.canonical() for e in episode.history.entries]
                json.dumps(rows)                                   # serializable as-is
                for row, entry in zip(rows, episode.history.entries):
                    self.assertEqual(row["task"], TASK.canonical())
                    self.assertEqual(row["pre_state"], entry.pre_state.world_key())
                    self.assertEqual(row["model_version"], "counter-probe.r0")
                    if entry.selected_call is not None:
                        self.assertEqual(row["selected_call"]["op"], str(entry.selected_call.op))


# ── composite-comparator aggregation with fakes (report Phase 5 item 4) ─────────────

class _CannedComparator:
    def __init__(self, *findings):
        self.findings = findings
        self.compared = 0

    def compare(self, symbolic_call, nl_proposal, /):
        self.compared += 1
        return ComparisonReport(findings=self.findings)


class _CompositeComparator:
    """TEST-LOCAL aggregation: the concatenation, in component order, of each component's
    findings. Evidence only — it selects and executes nothing. No production counterpart
    exists (pinned below): building one now would be the forbidden speculative machinery."""

    def __init__(self, *components):
        self.components = components

    def compare(self, symbolic_call, nl_proposal, /):
        findings = []
        for component in self.components:
            findings.extend(component.compare(symbolic_call, nl_proposal).findings)
        return ComparisonReport(findings=tuple(findings))


def _finding(kind, aspect, severity, message):
    return ComparisonFinding(aspect=aspect, severity=severity,
                             divergence=TrackDivergence(kind=kind, message=message))


class TestCompositeComparatorAggregation(unittest.TestCase):
    CONTRA = _finding(DivergenceKind.CONTRADICTION, ComparedAspect.ACTION_CHOICE,
                      FindingSeverity.ATTENTION, "fake A: contradiction")
    LOWCONF = _finding(DivergenceKind.CONFIDENCE_MISMATCH, ComparedAspect.CONFIDENCE,
                       FindingSeverity.BENIGN, "fake C: low confidence")

    def test_aggregation_preserves_component_order_and_payloads(self):
        a, b, c = _CannedComparator(self.CONTRA), _CannedComparator(), _CannedComparator(self.LOWCONF)
        composite = _CompositeComparator(a, b, c)
        self.assertIsInstance(composite, ProposalComparator)
        report = composite.compare(INC1, CounterProposal(call=STOP))
        self.assertEqual(report.findings, (self.CONTRA, self.LOWCONF))
        self.assertEqual(report.divergences, (self.CONTRA.divergence, self.LOWCONF.divergence))
        self.assertTrue(report.contradicted)
        self.assertFalse(report.all_benign)
        self.assertEqual((a.compared, b.compared, c.compared), (1, 1, 1))

    def test_all_empty_components_aggregate_to_genuine_agreement(self):
        report = _CompositeComparator(_CannedComparator(), _CannedComparator()).compare(INC1, None)
        self.assertEqual(report, ComparisonReport())
        self.assertTrue(report.all_benign)
        self.assertFalse(report.contradicted)

    def test_the_composite_is_injectable_without_loop_edits(self):
        """The real probe comparator (agreeing echo proposals -> nothing) beside two canned
        fakes: every executed entry carries exactly the fakes' payloads, in order."""
        composite = _CompositeComparator(
            _CannedComparator(self.CONTRA), CounterActionComparator(), _CannedComparator(self.LOWCONF),
        )
        episode = build_probe_loop(smooth_environment(), TASK, ADVISORY,
                                   nl_track=FakeReasoningTrack(), comparator=composite).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        executed = _executed(episode)
        self.assertEqual(len(executed), 5)
        for entry in executed:
            self.assertEqual(entry.divergences, (self.CONTRA.divergence, self.LOWCONF.divergence))

    #: every production class that implements `compare` — a new comparator of ANY name
    #: (composite, merged, aggregating, ...) is a deliberate edit here, never a silent one
    PRODUCTION_COMPARATORS = {"ProposalComparator", "BoxPushActionComparator"}

    def test_no_production_composite_comparator_exists(self):
        found = {}
        for path, tree in _sources(*_PRODUCTION_DIRS):
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    isinstance(b, ast.FunctionDef) and b.name == "compare" for b in node.body
                ):
                    found[node.name] = path.relative_to(_REPO_ROOT).as_posix()
        self.assertEqual(set(found), self.PRODUCTION_COMPARATORS, found)
        self.assertEqual(found["BoxPushActionComparator"], "app/comparator.py")


# ── the R5 structural protocols are exactly what the runtime reads ──────────────────

class _StrictTask:
    """Refuses every member outside `TaskContract`."""

    def __init__(self, inner):
        self._inner = inner
        self.reads = []

    def __getattr__(self, name):
        if name not in ("is_satisfied_by", "canonical"):
            raise AssertionError(f"the runtime read task.{name}")
        self.reads.append(name)
        return getattr(self._inner, name)


class TestDomainTypeContractsAreWhatTheRuntimeReads(unittest.TestCase):
    #: the members each protocol declares
    STATE = {"world_key", "same_world"}
    CALL = {"skill", "cost", "key", "canonical"}
    TASK_MEMBERS = {"is_satisfied_by", "canonical"}
    PROPOSAL = {"call", "coverage", "confidence"}

    STATE_RECEIVERS = {"snapshot", "pre_state", "post_state", "state"}
    CALL_RECEIVERS = {"call", "selected_call", "standing_recovery", "symbolic_call"}
    TASK_RECEIVERS = {"task"}
    PROPOSAL_RECEIVERS = {"nl_proposal", "cached_proposal", "proposal"}

    def _attribute_reads(self, receiver_names):
        """Attribute reads in `runtime/**` whose receiver is a bare name OR the last
        segment of an attribute chain (`self.task.x`, `result.post_state.x`,
        `error.result.post_state.x`, `decision.call.x`)."""
        reads = {}
        for path, tree in _sources(_RUNTIME_DIR):
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                receiver = None
                if isinstance(node.value, ast.Name):
                    receiver = node.value.id
                elif isinstance(node.value, ast.Attribute):
                    receiver = node.value.attr
                if receiver in receiver_names:
                    reads.setdefault(receiver, set()).add(node.attr)
        return reads

    def test_the_receiver_scan_sees_nested_chains(self):
        tree = ast.parse("def f(error):\n    return error.result.post_state.canonical()\n")
        found = {n.value.attr: n.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)}
        self.assertEqual(found.get("post_state"), "canonical")

    def test_runtime_reads_of_state_call_task_and_proposal_stay_within_the_protocols(self):
        receivers = (self.STATE_RECEIVERS | self.CALL_RECEIVERS
                     | self.TASK_RECEIVERS | self.PROPOSAL_RECEIVERS)
        reads = self._attribute_reads(receivers)

        def union(names):
            return set().union(*(reads.get(n, set()) for n in names))
        self.assertLessEqual(union(self.STATE_RECEIVERS), self.STATE)
        self.assertLessEqual(union(self.CALL_RECEIVERS), self.CALL)
        self.assertLessEqual(union(self.TASK_RECEIVERS), self.TASK_MEMBERS)
        self.assertLessEqual(union(self.PROPOSAL_RECEIVERS), self.PROPOSAL)
        # and the scan sees the reads that exist (non-vacuous), including nested ones
        self.assertIn("world_key", reads["pre_state"])
        self.assertIn("skill", reads["call"])
        self.assertEqual(reads["task"], {"is_satisfied_by"})      # via `self.task.`
        self.assertEqual(reads["nl_proposal"], self.PROPOSAL)

    def test_the_runtime_reads_nothing_of_the_task_beyond_the_contract(self):
        strict = _StrictTask(TASK)
        # the DOMAIN keeps its own task (it may read whatever it owns); only the RUNTIME
        # receives the strict proxy — the scripted track never reads the task either
        episode = build_probe_loop(sticky_environment(), strict, ADVISORY,
                                   nl_track=FakeReasoningTrack(
                                       [CounterProposal(call=INC1)] * 20),
                                   domain=CounterDomainServices(TASK)).run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(set(strict.reads), {"is_satisfied_by"})
        for entry in episode.history.entries:
            self.assertIs(entry.task, strict)
        # serialization is the only other contract member, and it is the domain's own form
        self.assertEqual(episode.history.entries[0].canonical()["task"], TASK.canonical())

    def test_the_protocols_are_runtime_checkable_and_minimal(self):
        for protocol, members in ((RuntimeState, self.STATE), (RuntimeCall, self.CALL),
                                  (TaskContract, self.TASK_MEMBERS), (AdvisoryProposal, self.PROPOSAL)):
            with self.subTest(protocol=protocol.__name__):
                declared = {n for n in vars(protocol)
                            if not n.startswith("_") and n not in ("__protocol_attrs__",)}
                self.assertEqual(declared, members)

        class _Bare:
            pass
        self.assertNotIsInstance(_Bare(), RuntimeState)
        self.assertNotIsInstance(_Bare(), TaskContract)


if __name__ == "__main__":
    unittest.main()
