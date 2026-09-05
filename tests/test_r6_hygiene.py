"""R6 hygiene (report Phase 6 items 1-3): observation aliasing, malformed backend returns,
and the discriminated NL proposal type.

Acceptance criteria pinned here:
  - mutating a returned observation cannot alter authoritative state — `observe()` deep-copies
    the very objects the adapter feeds to the backend skills, and `export_full_state()` is a
    frozen value with no reference into the backend;
  - no raw attribute/type exception escapes for a malformed backend result — every value the
    adapter reads back from the backend (the `env.reset()`/`env.step()` tuples, the `world`
    reads before, during and after an attempt) becomes the typed `MALFORMED_BACKEND_RESULT`
    fault, with case-(c) provenance exactly when an attempt already consumed env steps; and the
    runtime's own executor boundary converts a foreign environment's off-contract return the
    same way (exercised on the R5 probe, so the runtime-side proof is BoxPush-free);
  - `NLProposal` is `GroundedProposal | MalformedProposal`: each variant requires its own
    payload, neither admits the other's, both keep the runtime's `AdvisoryProposal` read
    surface, and `tests/contract_conformance.py::proposal_narrows_statically` is the mypy
    witness that an `isinstance` check proves which one a consumer holds.

Like `test_p1_adapter.py`, the adapter classes step the real backend: deterministic, offline,
no LM, no rendering.
"""
import copy
import dataclasses
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_DIR = os.path.join(_REPO_ROOT, "functional_layer", "custom_env", "box_push", "env")
for _p in (_REPO_ROOT, _ENV_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                                    # noqa: E402
from box_push_v1_adapter import BoxPushV1Adapter                     # noqa: E402

from domain.box_push_v1 import (                                      # noqa: E402
    AGENT_0,
    BOX_LIGHT,
    DELIVERY_ZONE,
    TASK_DELIVER_BOTH,
    initial_state,
)
from nl import NLTrack, RecordedLM, interpret_task, parse_skill_call  # noqa: E402
from nl.track import GroundedProposal, MalformedProposal, NLProposal  # noqa: E402
from app.comparator import DEFAULT_COMPARATOR                         # noqa: E402
from runtime.executor import execute                                  # noqa: E402
from runtime.loop import EpisodeOutcome                               # noqa: E402
from shared.contracts import AdvisoryProposal                         # noqa: E402
from shared.divergence import DivergenceKind                          # noqa: E402
from shared.execution import ExecutionResult                          # noqa: E402
from shared.faults import FaultKind, InfrastructureFaultError         # noqa: E402
from shared.reports import ConfidenceReport, CoverageReport           # noqa: E402
from shared.skills import GroundedSkillCall, MalformedCall, SkillName  # noqa: E402
from tests.probe_counter import (                                     # noqa: E402
    COUNTER,
    TASK,
    CounterEnvironment,
    build_probe_loop,
    increment,
    sticky_environment,
)

GOTO = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
PUSH = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)


def _fresh() -> BoxPushV1Adapter:
    adapter = BoxPushV1Adapter()
    adapter.reset()
    return adapter


def _obs_equal(a, b) -> bool:
    if set(a) != set(b):
        return False
    for aid in a:
        if set(a[aid]) != set(b[aid]):
            return False
        for key in a[aid]:
            x, y = a[aid][key], b[aid][key]
            if isinstance(x, np.ndarray) or isinstance(y, np.ndarray):
                if not (isinstance(x, np.ndarray) and isinstance(y, np.ndarray)
                        and np.array_equal(x, y)):
                    return False
            elif x != y:
                return False
    return True


def _assert_malformed(testcase, ctx, *, primitive_steps=None, source=None):
    fault = ctx.exception.fault
    testcase.assertIs(fault.kind, FaultKind.MALFORMED_BACKEND_RESULT)
    testcase.assertIsNone(ctx.exception.result)
    testcase.assertFalse(fault.message.startswith("refused:"))      # never a case-(b) refusal
    if primitive_steps is None:
        testcase.assertNotIn("primitive_steps", fault.detail)        # no attempt ran
    else:
        testcase.assertIn(f"primitive_steps_before_failure={primitive_steps}", fault.detail)
    if source is not None:
        testcase.assertEqual(fault.source, source)


# ── item 1: observations do not alias backend state ────────────────────────────────

class TestObservationsDoNotAliasBackendState(unittest.TestCase):
    def test_observe_returns_a_deep_copy_of_what_the_skills_are_fed(self):
        adapter = _fresh()
        obs = adapter.observe()
        internal = adapter._obs                          # what `_drive` hands to each skill
        self.assertIsNot(obs, internal)
        for aid in internal:
            self.assertIsNot(obs[aid], internal[aid])
            self.assertIsNot(obs[aid]["image"], internal[aid]["image"])
        self.assertTrue(_obs_equal(obs, internal))       # a copy, not a different channel

    def test_mutating_a_returned_observation_leaves_the_backend_untouched(self):
        """The acceptance criterion itself: every kind of mutation a caller can perform on
        the returned mapping — in-place array writes, scalar overwrites, key deletion,
        replacing a nested object — is invisible to the adapter's own observation, to the
        next `observe()`, and to the exact state."""
        adapter, witness = _fresh(), _fresh()
        obs = adapter.observe()
        obs["agent_0"]["image"][...] = 0
        obs["agent_0"]["direction"] = 99
        obs["agent_0"]["mission"] = "vandalized"
        obs["agent_1"]["image"] = None
        del obs["agent_1"]["direction"]
        obs.pop("agent_1")
        self.assertTrue(_obs_equal(adapter._obs, witness._obs))
        self.assertTrue(_obs_equal(adapter.observe(), witness.observe()))
        self.assertEqual(adapter.export_full_state(), witness.export_full_state())
        self.assertEqual(adapter.export_full_state().replay_key(),
                         witness.export_full_state().replay_key())

    def test_a_mutated_observation_never_reaches_a_backend_skill(self):
        """After a caller vandalizes its copy, the observation the adapter feeds the backend
        skill on the next attempt is still the backend's own, and the attempt is byte-identical
        to one on a pristine adapter."""
        adapter, witness = _fresh(), _fresh()
        vandalized = adapter.observe()
        vandalized["agent_0"]["image"][...] = 0
        vandalized["agent_0"]["direction"] = 99
        seen = []
        original_drive = adapter._drive

        def spying_drive(skills):
            seen.append(copy.deepcopy(adapter._obs))
            return original_drive(skills)

        adapter._drive = spying_drive
        pristine = witness.observe()                     # the backend's own, pre-attempt
        mine = adapter.execute_skill(GOTO)
        theirs = witness.execute_skill(GOTO)
        self.assertTrue(_obs_equal(seen[0], pristine))
        self.assertFalse(_obs_equal(seen[0], vandalized))
        self.assertEqual(mine.canonical(), theirs.canonical())
        self.assertEqual(mine.detail, theirs.detail)

    def test_the_exact_state_is_a_frozen_value_with_no_backend_reference(self):
        adapter = _fresh()
        snapshot = adapter.export_full_state()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.agents = ()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.agents[0].position = (0, 0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.boxes[0].delivered = True
        self.assertIsInstance(snapshot.static.walls, tuple)
        self.assertIsInstance(snapshot.static.delivery_zone, tuple)
        # value semantics in the other direction too: the backend moving on does not reach
        # back into an already-exported snapshot
        adapter.execute_skill(GOTO)
        self.assertEqual(snapshot, initial_state())
        self.assertEqual(snapshot.episode.step_count, 0)


# ── item 2: malformed backend returns are typed faults ─────────────────────────────

class TestMalformedBackendReturnsAreTypedFaults(unittest.TestCase):
    """Each case injects an off-contract value at the exact backend seam the adapter reads,
    then asserts the typed fault (kind, no attached result, provenance) — never the bare
    ValueError/AttributeError/TypeError/KeyError the raw read would have raised."""

    def _adapter_whose_step_returns(self, make_bad, after=2):
        adapter = _fresh()
        original_step = adapter._env.step
        good = []

        def step(actions):
            returned = original_step(actions)
            if len(good) >= after:
                return make_bad(returned)
            good.append(1)
            return returned

        adapter._env.step = step
        return adapter

    def test_a_step_tuple_of_the_wrong_length_is_a_typed_fault_with_provenance(self):
        adapter = self._adapter_whose_step_returns(lambda r: r[:4])
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(GOTO)
        # two good transitions plus the one that returned malformed: three env.step calls ran
        _assert_malformed(self, ctx, primitive_steps=3, source="BoxPushV1Adapter._drive")
        self.assertIn("5-tuple", ctx.exception.fault.message)
        self.assertEqual(adapter.export_full_state().episode.step_count, 3)   # world moved on

    def test_a_non_tuple_step_return_is_a_typed_fault(self):
        adapter = self._adapter_whose_step_returns(lambda r: None, after=0)
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(GOTO)
        _assert_malformed(self, ctx, primitive_steps=1)
        self.assertIn("NoneType", ctx.exception.fault.message)

    def test_per_agent_flags_that_are_not_mappings_are_a_typed_fault(self):
        for index, name in ((2, "terminations"), (3, "truncations")):
            with self.subTest(field=name):
                def bad(r, index=index):
                    parts = list(r)
                    parts[index] = [False, False]          # a list: `.values()` would raise
                    return tuple(parts)
                adapter = self._adapter_whose_step_returns(bad, after=1)
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    adapter.execute_skill(GOTO)
                _assert_malformed(self, ctx, primitive_steps=2)
                self.assertIn(name, ctx.exception.fault.message)

    def test_flags_missing_an_agent_are_a_typed_fault(self):
        def bad(r):
            parts = list(r)
            parts[2] = {"agent_0": False}                    # agent_1 absent
            return tuple(parts)
        adapter = self._adapter_whose_step_returns(bad, after=0)
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(GOTO)
        _assert_malformed(self, ctx, primitive_steps=1)

    def test_observations_missing_an_agent_or_not_a_mapping_are_a_typed_fault(self):
        cases = {
            "not a mapping": lambda r: (["agent_0"],) + tuple(r[1:]),
            "missing agent": lambda r: ({"agent_0": r[0]["agent_0"]},) + tuple(r[1:]),
            "entry not a mapping": lambda r: ({**r[0], "agent_1": 42},) + tuple(r[1:]),
        }
        for label, make_bad in cases.items():
            with self.subTest(case=label):
                adapter = self._adapter_whose_step_returns(make_bad, after=1)
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    adapter.execute_skill(GOTO)
                _assert_malformed(self, ctx, primitive_steps=2)
                self.assertIn("observations", ctx.exception.fault.message)

    def test_a_malformed_reset_return_is_a_typed_fault_before_any_attempt(self):
        adapter = BoxPushV1Adapter()
        original_reset = adapter._env.reset
        for label, make_bad in (
            ("bare dict", lambda r: r[0]),
            ("obs not a mapping", lambda r: (None, r[1])),
            ("obs missing agent", lambda r: ({"agent_0": r[0]["agent_0"]}, r[1])),
        ):
            with self.subTest(case=label):
                adapter._env.reset = lambda seed=None, make_bad=make_bad: make_bad(
                    original_reset(seed=seed))
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    adapter.reset()
                _assert_malformed(self, ctx, source="BoxPushV1Adapter.reset")
        # the latch was never set: the adapter still refuses use-before-reset (D8), and a
        # sound reset afterwards recovers it
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.export_full_state()
        self.assertTrue(ctx.exception.fault.message.startswith("refused:"))
        adapter._env.reset = original_reset
        self.assertEqual(adapter.reset(), initial_state())

    def test_a_raise_out_of_reset_is_a_typed_backend_fault(self):
        """The reset seam mirrors the step seam: an exception out of the authoritative reset
        is BACKEND_API_EXCEPTION (pre-attempt, no provenance key), and the D8 latch stays
        unset so use-before-reset is still refused afterwards."""
        adapter = BoxPushV1Adapter()

        def exploding_reset(seed=None):
            raise RuntimeError("cosmic ray at reset")

        adapter._env.reset = exploding_reset
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.reset()
        fault = ctx.exception.fault
        self.assertIs(fault.kind, FaultKind.BACKEND_API_EXCEPTION)
        self.assertIn("cosmic ray at reset", fault.message)
        self.assertNotIn("primitive_steps", fault.detail)
        self.assertIsNone(ctx.exception.result)
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.export_full_state()
        self.assertTrue(ctx.exception.fault.message.startswith("refused:"))

    def test_a_malformed_world_before_an_attempt_is_a_typed_fault_without_provenance(self):
        cases = {
            "agent position None": lambda w: setattr(w.agents["agent_0"], "position", None),
            "box position scalar": lambda w: setattr(w.objects[1], "position", 7),
            "direction out of range": lambda w: setattr(w.agents["agent_1"], "direction", 9),
            "agents not a mapping": lambda w: setattr(w, "agents", ["agent_0"]),
            "objects None": lambda w: setattr(w, "objects", None),
            "static missing walls": lambda w: delattr(w.static, "walls"),
        }
        for label, corrupt in cases.items():
            with self.subTest(case=label):
                adapter = _fresh()
                corrupt(adapter._env.core_env.world)
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    adapter.export_full_state()
                _assert_malformed(self, ctx, source="BoxPushV1Adapter.export_full_state")
                self.assertIn("malformed", ctx.exception.fault.message)
                # the pre-attempt export inside execute_skill routes the same way, with
                # zero env.step calls made
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    adapter.execute_skill(GOTO)
                _assert_malformed(self, ctx)

    def test_a_malformed_episode_record_is_a_typed_fault(self):
        adapter = _fresh()
        adapter._env.core_env.world.episode = None
        for method in (adapter.is_terminal, lambda: adapter.execute_skill(GOTO)):
            with self.subTest(method=getattr(method, "__name__", "execute_skill")):
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    method()
                _assert_malformed(self, ctx, source="BoxPushV1Adapter._episode_flags")

    def test_a_world_that_turns_malformed_after_the_attempt_carries_case_c_provenance(self):
        """The post-attempt export reads a world the attempt just changed; if THAT read is
        malformed the attempt already consumed env steps, so the fault is case (c) and must
        say how many primitives ran (the loop charges them from this key)."""
        adapter = _fresh()
        original_drive = adapter._drive
        consumed = []

        def drive_then_corrupt(skills):
            primitive_steps, calls_made = original_drive(skills)
            consumed.append(primitive_steps)
            adapter._env.core_env.world.objects[0].required_agents = None
            return primitive_steps, calls_made

        adapter._drive = drive_then_corrupt
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(GOTO)
        self.assertGreater(consumed[0], 0)                  # the attempt really ran
        _assert_malformed(self, ctx, primitive_steps=consumed[0],
                          source="BoxPushV1Adapter.export_full_state")
        self.assertEqual(adapter._env.core_env.world.episode.step_count, consumed[0])

    def test_a_world_that_turns_malformed_mid_attempt_carries_case_c_provenance(self):
        """The entities view is re-derived from `world` on every primitive step; a world that
        becomes unreadable there is the same typed fault with the primitives consumed so far."""
        adapter = _fresh()
        original_step = adapter._env.step
        calls = []

        def step(actions):
            returned = original_step(actions)
            calls.append(1)
            if len(calls) == 2:
                adapter._env.core_env.world.objects[1].position = "bad"
            return returned

        adapter._env.step = step
        with self.assertRaises(InfrastructureFaultError) as ctx:
            adapter.execute_skill(GOTO)
        _assert_malformed(self, ctx, primitive_steps=2, source="BoxPushV1Adapter._drive")

    def test_sound_returns_are_untouched_by_the_boundary_checks(self):
        """Behavior preservation: with the real backend the checks are inert — the same
        attempt, accounting and post-state as before, and the runner transcripts pinned in
        test_r0_characterization still hold."""
        adapter, witness = _fresh(), _fresh()
        result = adapter.execute_skill(GOTO)
        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.canonical(), witness.execute_skill(GOTO).canonical())
        self.assertEqual(result.accounting.primitive_steps,
                         adapter.export_full_state().episode.step_count)


class _GarbageEnv(CounterEnvironment):
    """A foreign environment whose `execute_skill` breaks the typed contract."""

    def __init__(self, garbage, **kw):
        super().__init__(**kw)
        self.garbage = garbage

    def execute_skill(self, call, /):
        super().execute_skill(call)                 # the backend really ran the attempt
        return self.garbage


class TestExecutorNormalizesOffContractReturns(unittest.TestCase):
    """The runtime side of item 2, on the R5 probe so it is BoxPush-free: the executor is
    the single backend boundary, and an environment returning something outside
    `ExecutionResult | MalformedCall | UngroundedCall` becomes the typed fault there."""

    def _env(self, garbage):
        from tests.probe_counter import INITIAL
        env = _GarbageEnv(garbage, initial=INITIAL)
        env.reset()
        return env

    def test_execute_raises_the_typed_fault_instead_of_returning_the_foreign_object(self):
        for garbage in ("done", None, 42, {"outcome": "success"}, object()):
            with self.subTest(garbage=type(garbage).__name__):
                with self.assertRaises(InfrastructureFaultError) as ctx:
                    execute(self._env(garbage), increment(COUNTER, 1))
                fault = ctx.exception.fault
                self.assertIs(fault.kind, FaultKind.MALFORMED_BACKEND_RESULT)
                self.assertIsNone(ctx.exception.result)
                self.assertIn(type(garbage).__name__, fault.message)
                # honest case-(c) provenance: the attempt reached the executor (one
                # executive step) and the backend reported no accounting — 0 is the bound
                self.assertIn("primitive_steps_before_failure=0", fault.detail)
                self.assertIn("lower bound", fault.detail)
                self.assertEqual(fault.source, "runtime/executor.py::execute")

    def test_the_loop_records_the_fault_and_charges_one_executive_step(self):
        episode_env = self._env("garbage")
        loop = build_probe_loop(episode_env, TASK)
        episode = loop.run()                                # no bare exception escapes
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("malformed_backend_result", episode.reason)
        (entry,) = episode.history.entries
        self.assertIsNone(entry.execution)                  # no typed result exists to record
        self.assertEqual([f.kind for f in entry.faults], [FaultKind.MALFORMED_BACKEND_RESULT])
        self.assertEqual(entry.selected_call, increment(COUNTER, 1))
        self.assertEqual(loop.executive_steps_charged, 1)   # case (c): charged from provenance
        self.assertEqual(loop.primitive_steps_charged, 0)
        self.assertEqual(episode.discrepancies, ())         # a fault, never a discrepancy
        self.assertEqual(episode_env.executed, [increment(COUNTER, 1)])   # the backend did run

    def test_typed_returns_pass_verbatim(self):
        env = sticky_environment()
        env.reset()
        returned = []
        original = env.execute_skill

        def recording(call):
            returned.append(original(call))
            return returned[-1]

        env.execute_skill = recording
        result = execute(env, increment(COUNTER, 1))
        self.assertIsInstance(result, ExecutionResult)
        self.assertIs(result, returned[0])                  # the same object, untouched


# ── item 3: the discriminated proposal type ────────────────────────────────────────

def _track_answering(selector_response: str, repair_response=None) -> NLTrack:
    probe = NLTrack(RecordedLM())
    probe.observe(initial_state())
    request = probe._selector.build_request(interpret_task(TASK_DELIVER_BOTH), probe.belief)
    recorded = {request: selector_response}
    if repair_response is not None:
        malformed = parse_skill_call(selector_response)
        recorded[probe._repair.build_request(malformed)] = repair_response
    track = NLTrack(RecordedLM.of(recorded))
    track.observe(initial_state())
    return track


class TestProposalVariants(unittest.TestCase):
    def test_the_track_returns_the_grounded_variant_for_a_well_formed_cycle(self):
        proposal = _track_answering("Push(agent_0; box_1; delivery_zone)").propose(TASK_DELIVER_BOTH)
        self.assertIsInstance(proposal, GroundedProposal)
        self.assertNotIsInstance(proposal, MalformedProposal)
        self.assertEqual(proposal.call, PUSH)
        self.assertIsInstance(proposal.confidence, ConfidenceReport)
        self.assertIsNone(proposal.malformed)

    def test_the_track_returns_the_malformed_variant_after_a_failed_repair(self):
        proposal = _track_answering("let's push the light box", "still chatting").propose(
            TASK_DELIVER_BOTH)
        self.assertIsInstance(proposal, MalformedProposal)
        self.assertIsInstance(proposal.malformed, MalformedCall)
        self.assertIsNone(proposal.call)
        self.assertIsNone(proposal.confidence)
        self.assertIsInstance(proposal.coverage, CoverageReport)   # interpretation evidence kept

    def test_both_variants_satisfy_the_runtime_proposal_contract_and_are_frozen(self):
        grounded = GroundedProposal(
            call=PUSH, coverage=CoverageReport(),
            confidence=ConfidenceReport(source="nl", confidence=1.0),
        )
        malformed = MalformedProposal(malformed=MalformedCall("r"), coverage=CoverageReport())
        for proposal in (grounded, malformed):
            with self.subTest(variant=type(proposal).__name__):
                self.assertIsInstance(proposal, AdvisoryProposal)
                self.assertIsInstance(proposal, NLProposal)
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    proposal.coverage = CoverageReport()
        self.assertFalse(grounded.repaired)

    def test_the_comparator_narrows_on_the_variant(self):
        malformed = MalformedProposal(
            malformed=MalformedCall("garbage", raw="x"),
            coverage=CoverageReport(residual=("clause",)),
        )
        report = DEFAULT_COMPARATOR.compare(GOTO, malformed)
        self.assertEqual([d.kind for d in report.divergences],
                         [DivergenceKind.COVERAGE_GAP, DivergenceKind.TRANSLATION_RESIDUAL])
        grounded = GroundedProposal(
            call=GOTO, coverage=CoverageReport(covered=("x",)),
            confidence=ConfidenceReport(source="nl", confidence=1.0),
        )
        self.assertEqual(DEFAULT_COMPARATOR.compare(GOTO, grounded).divergences, ())


if __name__ == "__main__":
    unittest.main()
