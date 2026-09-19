"""DK2 — the kit, proven EQUIVALENT beside the untouched R5 probe.

The probe (`tests/probe_counter.py`) hand-writes every mechanic the kit now supplies. This
module rebuilds the same one-integer domain from the kit (types with `identities()`, a
`SymbolicModel`, an `EnvironmentBase` subclass with the same sticky rule, `ProjectionTrack`,
`DefaultProposalComparator`) and runs it through the SAME `ExecutiveLoopManager` on the
probe's own scenario, then compares episode by episode against the hand-written probe:
decisions, executed calls, outcomes, discrepancy kinds, step accounting, and both accepted
episode outcomes. The probe is not modified; it is the oracle.

Also pinned here, per the DK2 spec:
- the environment base's fault semantics: refusals (`"refused:"`, protocol kind), malformed
  and ungrounded ARMS (returned, never raised), an `_attempt` exception -> the typed
  `BACKEND_API_EXCEPTION` with `primitive_steps_before_failure=N` (never a FAILURE result),
  a typed fault passing through untouched, `failed()` refusing to default the failure class
  and deriving PARTIAL_EXECUTION only when the world changed, `raw_label` never set,
  observations deep-copied;
- the derived monitor: frozen kinds only, world basis present iff `apply_world`, author
  errors re-raised as chained ValueError (the loop's established conversion);
- `bfs_plan`: the frozen planner's five result categories, state-free signature;
- the default comparator: kind/aspect parity with the probe's at default settings and with
  BoxPush's opt-in arms;
- structural guarantees by AST: kit imports stdlib + shared (+ kit) only; only
  `kit/environment.py` imports `shared.faults`; no kit module imports
  `shared.contracts.environment` except the environment base; the kit never catches an
  `InfrastructureFaultError`; no `state`/`env` parameter on `bfs_plan`.

Offline and deterministic: no backend, no LM, no network.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import pathlib
import sys
import unittest
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, FrozenSet, Optional

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.assembly import assemble_loop                                   # noqa: E402
from app.domain_package import DomainPackage                             # noqa: E402
from kit import (                                                        # noqa: E402
    CASE_C_KEY,
    DefaultProposalComparator,
    DerivedDomainServices,
    EnvironmentBase,
    ProjectionTrack,
    bfs_plan,
    ground_by_identity,
    symbolic_key,
    world_key,
)
from runtime.loop import EpisodeOutcome, ExecutiveLoopManager            # noqa: E402
from runtime.loop import _CASE_C_KEY as _LOOP_CASE_C_KEY                  # noqa: E402
from shared.comparison_keys import SymbolicKey, WorldKey                 # noqa: E402
from shared.contracts import (                                           # noqa: E402
    ComparedAspect,
    DomainServices,
    Environment,
    ProposalComparator,
    SymbolicTrack,
)
from shared.discrepancy import DiscrepancyKind                           # noqa: E402
from shared.divergence import DivergenceKind                             # noqa: E402
from shared.execution import (                                           # noqa: E402
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    StepAccounting,
)
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError  # noqa: E402
from shared.orchestration_config import (                                # noqa: E402
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.planner_result import NoPlan, PlanFound, PlannerFailure     # noqa: E402
from shared.reports import ConfidenceReport, CoverageReport              # noqa: E402
from shared.skills import (                                              # noqa: E402
    MalformedCall,
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)
from shared.versioning import ModelVersion                               # noqa: E402
from tests import probe_counter as probe                                 # noqa: E402
from tests.test_no_backend_imports import imported_modules               # noqa: E402

_KIT_DIR = _REPO_ROOT / "kit"


# ═══ the same one-integer domain, built from the kit ═══════════════════════════════════

class Op(StrEnum):
    INCREMENT = "Increment"
    STOP = "Stop"


@dataclass(frozen=True, slots=True)
class KState:
    counter_id: str
    value: int
    target: int
    stopped: bool = False
    tick: int = 0                                     # episode bookkeeping, not world content

    def canonical(self) -> Dict[str, Any]:
        return {"counter": self.counter_id, "value": self.value, "target": self.target,
                "stopped": self.stopped}

    def world_key(self) -> WorldKey:
        return world_key(self.canonical())

    def same_world(self, other: "KState", /) -> bool:
        return self.canonical() == other.canonical()

    def identities(self) -> FrozenSet[str]:
        return frozenset({self.counter_id})


@dataclass(frozen=True, slots=True)
class KCall:
    op: Op
    counter_id: str
    amount: int = 0

    @property
    def skill(self) -> Op:
        return self.op

    @property
    def cost(self) -> int:
        return 1

    def canonical(self) -> Dict[str, Any]:
        return {"op": str(self.op), "counter": self.counter_id, "amount": self.amount}

    def key(self) -> str:
        return json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))

    def identities(self) -> FrozenSet[str]:
        return frozenset({self.counter_id})

    def __str__(self) -> str:
        return (f"Increment({self.counter_id}; +{self.amount})" if self.op is Op.INCREMENT
                else f"Stop({self.counter_id})")


def inc(counter: str, amount: int = 1) -> KCall:
    return KCall(Op.INCREMENT, counter, amount)


def halt(counter: str) -> KCall:
    return KCall(Op.STOP, counter)


@dataclass(frozen=True, slots=True)
class KSym:
    value: int
    target: int
    stopped: bool

    def canonical(self) -> Dict[str, Any]:
        return {"value": self.value, "target": self.target, "stopped": self.stopped}

    def symbolic_key(self) -> SymbolicKey:
        return symbolic_key(self.canonical())


@dataclass(frozen=True, slots=True)
class KTask:
    task_id: str
    description: str
    counter_id: str

    def is_satisfied_by(self, state: KState, /) -> bool:
        return state.stopped and state.value == state.target

    def canonical(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "description": self.description,
                "counter": self.counter_id}


VERSION = ModelVersion(revision=0, label="kit-built")


class KModel:
    """The author's SymbolicModel: the probe's transition, written once."""

    def __init__(self, counter: str) -> None:
        self.counter = counter

    @property
    def model_version(self) -> ModelVersion:
        return VERSION

    def project(self, state: KState, /) -> KSym:
        return KSym(state.value, state.target, state.stopped)

    def apply(self, sym: KSym, call: KCall, /) -> KSym:
        if call.op is Op.INCREMENT:
            return KSym(sym.value + call.amount, sym.target, sym.stopped)
        return KSym(sym.value, sym.target, True)

    def applicable(self, sym: KSym, call: KCall, /):
        if sym.stopped:
            return SymbolicallyInapplicable(reason=f"{call}: already stopped", call=call,
                                            unsatisfied=("not stopped",))
        if call.op is Op.INCREMENT:
            if sym.value + call.amount > sym.target:
                return SymbolicallyInapplicable(reason=f"{call}: would overshoot", call=call,
                                                unsatisfied=("value + amount <= target",))
            return ValidatedCall(call=call)
        if sym.value != sym.target:
            return SymbolicallyInapplicable(reason=f"{call}: not at the target", call=call,
                                            unsatisfied=("value == target",))
        return ValidatedCall(call=call)

    def plan(self, sym: KSym, identities: FrozenSet[str], /):
        """Closed form, as the probe plans — NoPlan past the target, empty once stopped."""
        (counter,) = identities
        if sym.stopped:
            return PlanFound(plan=(), model_version=VERSION)
        if sym.value > sym.target:
            return NoPlan(reason="the value exceeds the target and the model has no decrement",
                          model_version=VERSION)
        steps = [inc(counter, 1)] * (sym.target - sym.value) + [halt(counter)]
        return PlanFound(plan=tuple(steps), model_version=VERSION)


def apply_world(state: KState, call: KCall) -> KState:
    if call.op is Op.INCREMENT:
        return KState(state.counter_id, state.value + call.amount, state.target, state.stopped,
                      state.tick)
    return KState(state.counter_id, state.value, state.target, True, state.tick)


class KEnv(EnvironmentBase[KState, KCall]):
    """The probe's sticky environment on the kit base: only `_reset`/`_attempt`/`_is_terminal`."""
    call_type = KCall

    def __init__(self, initial: KState, *, sticky_at=None) -> None:
        super().__init__()
        self._initial = initial
        self._sticky = frozenset() if sticky_at is None else frozenset(
            (sticky_at,) if isinstance(sticky_at, int) else sticky_at)

    def _reset(self, seed: Optional[int]) -> KState:
        return dataclasses.replace(self._initial, tick=0)

    def _is_terminal(self, state: KState) -> bool:
        return state.stopped

    def _attempt(self, call: KCall, pre: KState):
        bumped = dataclasses.replace(pre, tick=pre.tick + 1)
        if call.op is Op.INCREMENT:
            self.note_primitive_steps(1)
            stuck = pre.value in self._sticky and call.amount == 1
            if stuck or pre.value + call.amount > pre.target:
                return self.failed(call, pre, bumped, failure_class=FailureStateClass.UNCHANGED,
                                   detail="the counter did not advance")
            post = dataclasses.replace(bumped, value=pre.value + call.amount)
            return self.succeeded(call, pre, post, primitive_steps=call.amount)
        self.note_primitive_steps(1)
        if pre.value != pre.target:
            return self.failed(call, pre, bumped,
                               failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION,
                               detail="cannot stop away from the target")
        return self.succeeded(call, pre, dataclasses.replace(bumped, stopped=True))


def k_recovery(discrepancy):
    call = discrepancy.call
    return (inc(call.counter_id, call.amount + 1),) if call.op is Op.INCREMENT else ()


COUNTER = probe.COUNTER
TASK = KTask("count-to-four", "Count to four, then stop", COUNTER)
INITIAL = KState(COUNTER, 0, 4)


def kit_package(*, sticky=True) -> DomainPackage:
    model = KModel(COUNTER)
    return DomainPackage(
        name="kit_built",
        tasks={TASK.task_id: TASK},
        default_task=TASK.task_id,
        environment=lambda: KEnv(INITIAL, sticky_at=probe.STICKY_AT if sticky else None),
        services=lambda task: DerivedDomainServices(model, apply_world=apply_world),
        symbolic_track=lambda: ProjectionTrack(model.project),
        recovery_provider=k_recovery,
        comparator=lambda: DefaultProposalComparator(),
    )


PRIMARY = OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY)
ADVISORY = OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK)


def _story(episode, loop):
    """Everything comparable between the two implementations, entry by entry."""
    rows = []
    for e in episode.history.entries:
        rows.append((
            e.executive_step,
            e.decision.value if e.decision else None,
            e.selected_call.canonical() if e.selected_call else None,
            e.execution.outcome.value if e.execution else None,
            e.execution.failure_class.value if e.execution and e.execution.failure_class else None,
            e.execution.accounting.canonical() if e.execution else None,
            tuple(d.kind.value for d in e.discrepancies),
            tuple(f.kind.value for f in e.faults),
            e.validation.__class__.__name__ if e.validation else None,
            tuple(d.kind.value for d in e.divergences),
            e.nl_proposal.canonical() if e.nl_proposal is not None else None,
            e.predicted_world_key, e.predicted_symbolic_key,
            type(e.symbolic_result).__name__ if e.symbolic_result is not None else None,
            e.pre_state.canonical(),
        ))
    return (
        episode.outcome.value, rows, loop.executive_steps_charged, loop.primitive_steps_charged,
        tuple(d.kind.value for d in episode.discrepancies),
    )


# ═══ 1. equivalence beside the probe ═══════════════════════════════════════════════════

class TestKitDomainMatchesTheHandWrittenProbe(unittest.TestCase):
    def _probe(self, config, env):
        loop = probe.build_probe_loop(env, probe.TASK, config)
        return loop, loop.run()

    def _kit(self, config, *, sticky):
        loop = assemble_loop(kit_package(sticky=sticky), config=config)
        return loop, loop.run()

    def test_sticky_scenario_under_both_policies(self):
        for config, expected in ((PRIMARY, EpisodeOutcome.HALTED_REPEATED_FAILURE),
                                 (ADVISORY, EpisodeOutcome.GOAL_REACHED)):
            with self.subTest(policy=config.policy.value):
                p_loop, p_ep = self._probe(config, probe.sticky_environment())
                k_loop, k_ep = self._kit(config, sticky=True)
                self.assertIs(p_ep.outcome, expected)
                self.assertEqual(_story(k_ep, k_loop), _story(p_ep, p_loop))
                self.assertEqual([c.canonical() for c in k_loop.env.executed],
                                 [c.canonical() for c in p_loop.env.executed])

    def test_smooth_scenario_under_both_policies(self):
        for config in (PRIMARY, ADVISORY):
            with self.subTest(policy=config.policy.value):
                p_loop, p_ep = self._probe(config, probe.smooth_environment())
                k_loop, k_ep = self._kit(config, sticky=False)
                self.assertIs(k_ep.outcome, EpisodeOutcome.GOAL_REACHED)
                self.assertEqual(_story(k_ep, k_loop), _story(p_ep, p_loop))
                self.assertEqual([c.canonical() for c in k_loop.env.executed],
                                 [c.canonical() for c in p_loop.env.executed])

    def test_advisory_scenario_with_an_echo_track_on_both_sides(self):
        """The probe's accepted advisory scenario (`test_r5_probe.py:458`) runs WITH a
        track; so must the equivalence proof. The kit side needs a KIT-TYPED echo track (a
        probe `CounterAction` never equals a `KCall`). The one field deliberately NOT
        reproduced by the kit comparator is the CONTRADICTION finding's `residual`: the probe
        forwards its proposal's opaque `evidence`, which is not on `AdvisoryProposal`."""

        class KitEcho(probe.FakeReasoningTrack):
            def propose(self, task, /):
                p = super().propose(task)
                call = None if p.call is None else (
                    inc(p.call.counter_id, p.call.amount) if p.call.op is probe.CounterOp.INCREMENT
                    else halt(p.call.counter_id))
                return dataclasses.replace(p, call=call)

        p_loop = probe.build_probe_loop(probe.sticky_environment(), probe.TASK, ADVISORY,
                                        nl_track=probe.FakeReasoningTrack())
        k_loop = assemble_loop(kit_package(sticky=True), config=ADVISORY, nl_track=KitEcho())
        p_ep, k_ep = p_loop.run(), k_loop.run()
        self.assertIs(p_ep.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(_story(k_ep, k_loop), _story(p_ep, p_loop))
        self.assertTrue(any(e.nl_proposal is not None for e in k_ep.history.entries))

    def test_the_kit_components_satisfy_the_contracts_and_the_loop_is_unmodified(self):
        loop = assemble_loop(kit_package())
        self.assertIs(type(loop), ExecutiveLoopManager)
        self.assertIsInstance(loop.env, Environment)
        self.assertIsInstance(loop.domain, DomainServices)
        self.assertIsInstance(loop.belief, SymbolicTrack)
        self.assertIsInstance(loop.comparator, ProposalComparator)

    def test_predictions_match_the_probe_key_for_key(self):
        p = probe.CounterDomainServices(probe.TASK)
        k = DerivedDomainServices(KModel(COUNTER), apply_world=apply_world)
        p_state, k_state = probe.INITIAL, INITIAL
        p_pred = p.predict(probe.project(p_state), p_state, probe.increment(COUNTER, 1))
        k_pred = k.predict(KModel(COUNTER).project(k_state), k_state, inc(COUNTER, 1))
        self.assertEqual(k_pred.world_key, p_pred.world_key)     # same canonical payloads
        self.assertEqual(k_pred.symbolic_key, p_pred.symbolic_key)


# ═══ 2. environment base fault semantics ═══════════════════════════════════════════════

class TestEnvironmentBase(unittest.TestCase):
    def setUp(self):
        self.env = KEnv(INITIAL, sticky_at=2)

    def test_refusal_before_reset_is_typed_and_prefixed(self):
        for method in (self.env.observe, self.env.export_full_state, self.env.is_terminal,
                       self.env.render, lambda: self.env.execute_skill(inc(COUNTER))):
            with self.assertRaises(InfrastructureFaultError) as caught:
                method()
            self.assertIs(caught.exception.fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)
            self.assertTrue(caught.exception.fault.message.startswith("refused:"))
            self.assertIsNone(caught.exception.result)

    def test_post_terminal_refusal(self):
        env = KEnv(KState(COUNTER, 4, 4))
        env.reset()
        env.execute_skill(halt(COUNTER))
        self.assertTrue(env.is_terminal())
        with self.assertRaises(InfrastructureFaultError) as caught:
            env.execute_skill(inc(COUNTER))
        self.assertTrue(caught.exception.fault.message.startswith("refused:"))
        self.assertIs(caught.exception.fault.kind, FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE)

    def test_malformed_and_ungrounded_are_returned_not_raised(self):
        self.env.reset()
        malformed = self.env.execute_skill("Increment")          # type: ignore[arg-type]
        self.assertIsInstance(malformed, MalformedCall)
        self.assertIn("KCall", malformed.reason)
        ghost = self.env.execute_skill(inc("c9"))
        self.assertIsInstance(ghost, UngroundedCall)
        self.assertEqual(ghost.call, inc("c9"))
        self.assertIn("c9", ghost.reason)
        self.assertEqual(self.env.executed, [])                  # zero steps, nothing ran

    def test_grounding_is_written_once_and_shared_with_the_services(self):
        services = DerivedDomainServices(KModel(COUNTER))
        self.assertEqual(services.ground(INITIAL, inc("c9")), ground_by_identity(INITIAL, inc("c9")))
        self.assertIsNone(services.ground(INITIAL, inc(COUNTER)))

    def test_state_advances_to_the_result_post_state(self):
        self.env.reset()
        result = self.env.execute_skill(inc(COUNTER, 2))
        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(self.env.export_full_state(), result.post_state)
        self.assertEqual(result.accounting, StepAccounting(executive_steps=1, primitive_steps=2))
        self.assertIsNone(result.raw_label)

    def test_an_attempt_exception_is_a_backend_api_fault_with_case_c_provenance(self):
        class Crashing(KEnv):
            def _attempt(self, call, pre):
                self.note_primitive_steps(3)
                raise KeyError("backend blew up")

        env = Crashing(INITIAL)
        env.reset()
        with self.assertRaises(InfrastructureFaultError) as caught:
            env.execute_skill(inc(COUNTER))
        fault = caught.exception.fault
        self.assertIs(fault.kind, FaultKind.BACKEND_API_EXCEPTION)
        self.assertEqual(fault.detail, "primitive_steps_before_failure=3")   # the literal
        self.assertEqual(_LOOP_CASE_C_KEY.search(fault.detail).group(1), "3")  # what the loop parses
        self.assertIn("KeyError", fault.message)
        self.assertIsNone(caught.exception.result)                # never a FAILURE result
        self.assertIsInstance(caught.exception.__cause__, KeyError)
        self.assertEqual(env.export_full_state(), INITIAL)          # the base did not advance

    def test_a_crashing_attempt_routes_through_the_loop_as_a_charged_fault(self):
        class Crashing(KEnv):
            def _attempt(self, call, pre):
                self.note_primitive_steps(3)
                raise KeyError("backend blew up")

        loop = assemble_loop(kit_package(), environment=Crashing(INITIAL))
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        (entry,) = [e for e in episode.history.entries if e.faults]
        self.assertEqual([f.kind for f in entry.faults], [FaultKind.BACKEND_API_EXCEPTION])
        self.assertIsNone(entry.execution)
        self.assertEqual(loop.executive_steps_charged, 1)      # case (c): one step charged
        self.assertEqual(loop.primitive_steps_charged, 3)      # ... plus the noted primitives

    def test_a_typed_fault_from_the_author_passes_through_untouched(self):
        marker = InfrastructureFaultError(InfrastructureFault(
            kind=FaultKind.MALFORMED_BACKEND_RESULT, message="the backend returned garbage",
            detail=f"{CASE_C_KEY}=1", source="author",
        ))

        class Faulting(KEnv):
            def _attempt(self, call, pre):
                raise marker

        env = Faulting(INITIAL)
        env.reset()
        with self.assertRaises(InfrastructureFaultError) as caught:
            env.execute_skill(inc(COUNTER))
        self.assertIs(caught.exception, marker)

    def test_mid_attempt_fault_helper_carries_the_key(self):
        env = KEnv(INITIAL)
        env.reset()
        env.note_primitive_steps(2)
        error = env.mid_attempt_fault(FaultKind.MALFORMED_BACKEND_RESULT, "bad step tuple")
        self.assertEqual(error.fault.detail, f"{CASE_C_KEY}=2")
        self.assertIs(error.fault.kind, FaultKind.MALFORMED_BACKEND_RESULT)

    def test_failed_never_defaults_the_failure_class(self):
        env = KEnv(INITIAL)
        env.reset()
        pre = INITIAL
        with self.assertRaisesRegex(ValueError, "UNCHANGED.*BACKEND_REJECTED_BEFORE_TRANSITION"):
            env.failed(inc(COUNTER), pre, pre)
        unchanged = env.failed(inc(COUNTER), pre, pre, failure_class=FailureStateClass.UNCHANGED)
        self.assertIs(unchanged.failure_class, FailureStateClass.UNCHANGED)
        rejected = env.failed(inc(COUNTER), pre, pre,
                              failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION)
        self.assertIs(rejected.failure_class, FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION)

    def test_failed_derives_partial_execution_only_when_the_world_changed(self):
        env = KEnv(INITIAL)
        env.reset()
        moved = dataclasses.replace(INITIAL, value=1)
        partial = env.failed(inc(COUNTER, 2), INITIAL, moved)
        self.assertIs(partial.failure_class, FailureStateClass.PARTIAL_EXECUTION)
        with self.assertRaisesRegex(ValueError, "PARTIAL_EXECUTION"):
            env.failed(inc(COUNTER, 2), INITIAL, moved, failure_class=FailureStateClass.UNCHANGED)
        with self.assertRaisesRegex(ValueError, "SUCCESS"):
            env.failed(inc(COUNTER), INITIAL, INITIAL, outcome=ExecutionOutcome.SUCCESS)

    def test_observations_are_deep_copies(self):
        class Aliasing(KEnv):
            def _observe(self, state):
                return {"nested": [state.value]}

        env = Aliasing(INITIAL)
        env.reset()
        first = env.observe()
        first["nested"].append(99)
        self.assertEqual(env.observe(), {"nested": [0]})

    def test_a_subclass_without_call_type_is_refused_at_instantiation(self):
        class Missing(EnvironmentBase):          # an abstract intermediate base is fine...
            def _reset(self, seed):
                return INITIAL

            def _attempt(self, call, pre):
                return self.succeeded(call, pre, pre)

            def _is_terminal(self, state):
                return False

        with self.assertRaisesRegex(TypeError, "call_type"):
            Missing()                            # ...instantiating one without call_type is not

        class Concrete(Missing):
            call_type = KCall

        Concrete()

    def test_a_call_less_proposal_never_reaches_the_confidence_arm(self):
        """BoxPush returns after the no-call findings (`app/comparator.py:98-118`); so does
        the kit, even with the confidence arm opted in."""
        malformed = probe.CounterProposal(call=None, coverage=CoverageReport(residual=("x",)),
                                          confidence=ConfidenceReport(source="nl", confidence=0.1))
        report = DefaultProposalComparator(
            low_confidence_threshold=0.75, report_translation_residual=True,
        ).compare(probe.increment(COUNTER, 1), malformed)
        self.assertEqual([f.classification for f in report.findings],
                         [DivergenceKind.COVERAGE_GAP, DivergenceKind.TRANSLATION_RESIDUAL])


# ═══ 3. derived services / monitor ══════════════════════════════════════════════════════

class TestDerivedServices(unittest.TestCase):
    def setUp(self):
        self.model = KModel(COUNTER)
        self.with_world = DerivedDomainServices(self.model, apply_world=apply_world)
        self.symbolic_only = DerivedDomainServices(self.model)

    def _result(self, call, pre, post, outcome=ExecutionOutcome.SUCCESS, failure_class=None):
        return ExecutionResult(call=call, outcome=outcome, pre_state=pre, post_state=post,
                               accounting=StepAccounting(executive_steps=1, primitive_steps=1),
                               failure_class=failure_class)

    def test_plan_reads_identities_only(self):
        sym = self.model.project(INITIAL)
        elsewhere = dataclasses.replace(INITIAL, tick=42)
        self.assertEqual(self.with_world.plan(sym, INITIAL), self.with_world.plan(sym, elsewhere))
        self.assertIsInstance(self.with_world.plan(sym, INITIAL), PlanFound)

    def test_world_basis_present_iff_apply_world(self):
        sym = self.model.project(INITIAL)
        self.assertIsNotNone(self.with_world.predict(sym, INITIAL, inc(COUNTER)).world_key)
        self.assertIsNone(self.symbolic_only.predict(sym, INITIAL, inc(COUNTER)).world_key)
        self.assertIsNotNone(self.symbolic_only.predict(sym, INITIAL, inc(COUNTER)).symbolic_key)

    def test_failure_of_applicable_call_is_the_typed_outcome_alone(self):
        result = self._result(inc(COUNTER), INITIAL, dataclasses.replace(INITIAL, tick=1),
                              ExecutionOutcome.FAILURE, FailureStateClass.UNCHANGED)
        (found,) = self.with_world.monitor(self.model.project(INITIAL), result)
        self.assertIs(found.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)
        self.assertEqual(found.comparison_bases, ())
        self.assertEqual(found.model_version, VERSION)

    def test_success_that_matches_the_prediction_is_silent(self):
        post = dataclasses.replace(INITIAL, value=1, tick=1)
        self.assertEqual(self.with_world.monitor(self.model.project(INITIAL),
                                                 self._result(inc(COUNTER), INITIAL, post)), ())

    def test_mismatch_carries_every_complete_pair(self):
        surprise = dataclasses.replace(INITIAL, value=3, tick=1)      # +3 realized for +1
        result = self._result(inc(COUNTER), INITIAL, surprise)
        (both,) = self.with_world.monitor(self.model.project(INITIAL), result)
        self.assertIs(both.kind, DiscrepancyKind.STATE_EFFECT_MISMATCH)
        self.assertEqual(len(both.comparison_bases), 2)
        self.assertEqual(len(both.mismatched_bases), 2)
        (sym_only,) = self.symbolic_only.monitor(self.model.project(INITIAL), result)
        self.assertEqual(len(sym_only.comparison_bases), 1)
        self.assertIsNone(sym_only.predicted_world_key)

    def test_only_the_frozen_kinds_are_produced(self):
        source = (_KIT_DIR / "services.py").read_text(encoding="utf-8")
        used = {node.attr for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "DiscrepancyKind"}
        self.assertEqual(used, {"EXECUTION_FAILURE_OF_APPLICABLE_SKILL", "STATE_EFFECT_MISMATCH"})

    def test_author_errors_inside_the_monitor_become_value_errors(self):
        class Broken(KModel):
            def project(self, state, /):
                raise KeyError("author bug")

        services = DerivedDomainServices(Broken(COUNTER))
        result = self._result(inc(COUNTER), INITIAL, dataclasses.replace(INITIAL, value=1))
        with self.assertRaises(ValueError) as caught:
            services.monitor(KSym(0, 4, False), result)
        self.assertIsInstance(caught.exception.__cause__, KeyError)
        self.assertIn("Broken", str(caught.exception))
        # a ValueError from the author is the established escape and passes through
        class Loud(KModel):
            def project(self, state, /):
                raise ValueError("wiring")

        with self.assertRaisesRegex(ValueError, "^wiring$"):
            DerivedDomainServices(Loud(COUNTER)).monitor(KSym(0, 4, False), result)


# ═══ 4. bfs_plan ═══════════════════════════════════════════════════════════════════════

class TestBfsPlan(unittest.TestCase):
    model = KModel(COUNTER)

    def _plan(self, start, target=4, **kwargs):
        candidates = [inc(COUNTER, 1), inc(COUNTER, 2), halt(COUNTER)]
        return bfs_plan(
            start, is_goal=lambda s: s.stopped and s.value == s.target,
            candidates=kwargs.pop("candidates", candidates),
            applicable=self.model.applicable, apply=self.model.apply,
            model_version=VERSION, **kwargs,
        )

    def test_goal_already_satisfied(self):
        found = self._plan(KSym(4, 4, True))
        self.assertIsInstance(found, PlanFound)
        self.assertEqual(found.plan, ())
        self.assertEqual(found.model_version, VERSION)

    def test_shortest_plan_found(self):
        found = self._plan(KSym(0, 4, False))
        self.assertIsInstance(found, PlanFound)
        self.assertEqual(found.plan, (inc(COUNTER, 2), inc(COUNTER, 2), halt(COUNTER)))

    def test_no_candidates_is_noplan(self):
        self.assertIsInstance(self._plan(KSym(0, 4, False), candidates=[]), NoPlan)

    def test_exhaustion_is_noplan_not_failure(self):
        result = self._plan(KSym(5, 4, False))                  # past the target: no decrement
        self.assertIsInstance(result, NoPlan)
        self.assertIn("exhausted", result.reason)

    def test_budget_is_planner_failure_timed_out(self):
        result = self._plan(KSym(0, 4, False), node_budget=1)
        self.assertIsInstance(result, PlannerFailure)
        self.assertTrue(result.timed_out)

    def test_an_exception_is_planner_failure(self):
        result = bfs_plan(KSym(0, 4, False), is_goal=lambda s: False, candidates=[inc(COUNTER)],
                          applicable=lambda s, c: ValidatedCall(call=c),
                          apply=lambda s, c: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertIsInstance(result, PlannerFailure)
        self.assertFalse(result.timed_out)
        self.assertIn("RuntimeError", result.error)

    def test_the_signature_admits_no_state_or_environment(self):
        params = inspect.signature(bfs_plan).parameters
        self.assertEqual(set(params) - {"start"},
                         {"is_goal", "candidates", "applicable", "apply", "model_version",
                          "node_budget"})
        for name in ("state", "snapshot", "env", "environment"):
            self.assertNotIn(name, params)


# ═══ 5. default comparator parity ══════════════════════════════════════════════════════

class TestDefaultComparator(unittest.TestCase):
    def _shape(self, report):
        # Compared: aspect, kind, severity, both views. Deliberately NOT compared: `message`
        # (each comparator's own wording), the nl_view wording for a MISSING call (same), and
        # `residual` (the probe forwards its proposal's opaque `evidence`, which the
        # `AdvisoryProposal` contract does not carry; the kit forwards `coverage.residual`).
        return [(f.aspect, f.classification, f.severity,
                 f.divergence.nl_view if f.aspect is not ComparedAspect.PROPOSAL_FORM else "-",
                 f.divergence.symbolic_view)
                for f in report.findings]

    def test_parity_with_the_probe_comparator_at_default_settings(self):
        theirs, ours = probe.CounterActionComparator(), DefaultProposalComparator()
        selected = probe.increment(COUNTER, 1)
        agree = probe.CounterProposal(call=selected, coverage=CoverageReport(covered=("c",)),
                                      confidence=ConfidenceReport(source="nl", confidence=1.0))
        differ = dataclasses.replace(agree, call=probe.stop(COUNTER))
        malformed = dataclasses.replace(agree, call=None)
        for proposal in (None, agree, differ, malformed):
            with self.subTest(proposal=proposal):
                self.assertEqual(self._shape(ours.compare(selected, proposal)),
                                 self._shape(theirs.compare(selected, proposal)))
        self.assertEqual(ours.compare(None, differ).findings, ())     # no symbolic side: nothing

    def test_boxpush_arms_are_opt_in(self):
        class Equivalent:
            def benign_equivalence(self, proposed, selected, /):
                return "same op" if proposed.op is selected.op else None

        selected, proposed = probe.increment(COUNTER, 1), probe.increment(COUNTER, 2)
        low = probe.CounterProposal(call=proposed, coverage=CoverageReport(residual=("x",)),
                                    confidence=ConfidenceReport(source="nl", confidence=0.2))
        default = DefaultProposalComparator().compare(selected, low)
        self.assertEqual([f.classification for f in default.findings],
                         [DivergenceKind.CONTRADICTION])
        configured = DefaultProposalComparator(
            Equivalent(), low_confidence_threshold=0.75, report_translation_residual=True,
        ).compare(selected, low)
        self.assertEqual(
            [(f.aspect, f.classification) for f in configured.findings],
            [(ComparedAspect.TASK_TRANSLATION, DivergenceKind.TRANSLATION_RESIDUAL),
             (ComparedAspect.ACTION_CHOICE, DivergenceKind.BENIGN_ABSTRACTION_MISMATCH),
             (ComparedAspect.CONFIDENCE, DivergenceKind.CONFIDENCE_MISMATCH)],
        )
        self.assertTrue(all(f.divergence.residual == ("x",) or f.aspect is not
                            ComparedAspect.TASK_TRANSLATION for f in configured.findings))
        with self.assertRaises(ValueError):
            DefaultProposalComparator(low_confidence_threshold=1.5)

    def test_malformed_proposal_with_residual_mirrors_boxpush_when_opted_in(self):
        """R3 item 6 (`app/comparator.py:108-118`): a malformed proposal does not suppress
        the independent residual finding — when the residual arm is opted in."""
        malformed = probe.CounterProposal(call=None, coverage=CoverageReport(residual=("x",)),
                                          confidence=ConfidenceReport(source="nl", confidence=1.0))
        selected = probe.increment(COUNTER, 1)
        default = DefaultProposalComparator().compare(selected, malformed)
        self.assertEqual([f.classification for f in default.findings], [DivergenceKind.COVERAGE_GAP])
        opted = DefaultProposalComparator(report_translation_residual=True).compare(selected, malformed)
        self.assertEqual([(f.aspect, f.classification) for f in opted.findings],
                         [(ComparedAspect.PROPOSAL_FORM, DivergenceKind.COVERAGE_GAP),
                          (ComparedAspect.TASK_TRANSLATION, DivergenceKind.TRANSLATION_RESIDUAL)])
        self.assertTrue(all(f.divergence.residual == ("x",) for f in opted.findings))


# ═══ 6. structural guarantees (AST) ═════════════════════════════════════════════════════

class TestKitStructure(unittest.TestCase):
    ALLOWED_ROOTS = frozenset({
        "__future__", "abc", "collections", "copy", "dataclasses", "enum", "hashlib", "json",
        "typing", "shared", "kit",
    })

    def _modules(self):
        return sorted(p for p in _KIT_DIR.glob("*.py"))

    def test_kit_imports_only_stdlib_shared_and_kit(self):
        self.assertGreaterEqual(len(self._modules()), 7)
        for path in self._modules():
            for module, lineno in imported_modules(path):
                self.assertIn(module.split(".")[0], self.ALLOWED_ROOTS,
                              f"{path.name}:{lineno} imports {module}")

    def test_only_the_environment_base_touches_faults(self):
        for path in self._modules():
            roots = {m for m, _ in imported_modules(path)}
            if path.name == "environment.py":
                self.assertIn("shared.faults", roots)
            else:
                self.assertNotIn("shared.faults", roots, path.name)
                self.assertNotIn("shared.contracts.environment", roots, path.name)
                self.assertNotIn("shared.backend_contract", roots, path.name)

    #: the catch-all handlers the kit deliberately keeps: each converts ANY author error
    #: into the frozen escape its consumer expects — the BACKEND_API_EXCEPTION fault for an
    #: `_attempt` raise (after the re-raise handler, so a typed fault never reaches it),
    #: ValueError for the loop's monitor wrap, PlannerFailure for the planner contract (the
    #: same shape as `symbolic/planner.py:140`)
    ALLOWED_CATCH_ALLS = {"environment.py": 1, "services.py": 1, "planning.py": 1}

    def test_fault_handlers_re_raise_and_catch_alls_are_enumerated(self):
        checked, catch_alls = 0, {}
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                names = ({n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)}
                         if node.type is not None else set())
                if "InfrastructureFaultError" in names:
                    checked += 1                       # the one allowed shape: re-raise untouched
                    self.assertEqual(path.name, "environment.py")
                    self.assertEqual(len(node.body), 1, path.name)
                    self.assertIsInstance(node.body[0], ast.Raise, path.name)
                    self.assertIsNone(node.body[0].exc, path.name)
                elif node.type is None or "Exception" in names or "BaseException" in names:
                    catch_alls[path.name] = catch_alls.get(path.name, 0) + 1
        self.assertGreaterEqual(checked, 1)
        self.assertEqual(catch_alls, self.ALLOWED_CATCH_ALLS)

    def test_protocols_is_a_leaf_so_the_package_has_no_import_cycle(self):
        roots = {m for m, _ in imported_modules(_KIT_DIR / "protocols.py")}
        self.assertFalse({r for r in roots if r.split(".")[0] == "kit"}, roots)

    def test_no_domain_vocabulary_in_kit_identifiers(self):
        stems = ("box", "agent", "zone", "grid", "push", "deliver", "counter", "probe")
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                name = getattr(node, "id", None) or getattr(node, "attr", None) or (
                    node.name if isinstance(node, (ast.ClassDef, ast.FunctionDef)) else None
                ) or (node.arg if isinstance(node, (ast.arg, ast.keyword)) else None)
                if name:
                    for stem in stems:
                        self.assertNotIn(stem, name.lower(), f"{path.name} names {name!r}")

    def test_kit_is_discovered_as_the_symbolic_side(self):
        from tests.test_no_backend_imports import (
            TestSymbolicSideCannotReachRuntimeState as Guard, runtime_violations,
        )
        self.assertIn("kit", Guard.symbolic_side())
        self.assertEqual(runtime_violations(("kit",)), [])


if __name__ == "__main__":
    unittest.main()
