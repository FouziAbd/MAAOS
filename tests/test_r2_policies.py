"""R2 policy-extraction tests (report Phase 2).

Phase 2 acceptance, made mechanical:

- policies are unit-testable as PURE transformations of immutable context into typed
  decisions (`TestPoliciesArePureDecisionTables`);
- `required_inputs()` lets symbolic-primary avoid NL calls while two-track policies
  request them (`TestRequiredInputsGovernNLAcquisition`);
- a policy cannot call the environment through its public interface — structurally: the
  policies module imports only stdlib + `shared`, and a full episode runs with a policy
  whose only inputs are the contexts (`TestPolicyCannotReachTheEnvironment`);
- adding a test policy requires NO edits to `runtime/loop.py`: a novel policy class defined
  HERE is injected and drives a real episode (`TestLoopAcceptsAnInjectedPolicyObject`);
- dispatch is an open name registry, not the closed enum (`TestRegistryDispatch`);
- the legacy `runtime.orchestrator.decide` surface stays behavior-identical as a shim
  (routing itself is still pinned by tests/test_p4_runtime.py::TestOrchestratorRouting).

Frozen reason strings asserted here are baseline surface (the R0 transcripts pin the
symbolic-primary halt reason verbatim) — they are part of accepted V1 behavior.

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

from shared.contracts import (
    Execute,
    Halt,
    OrchestrationContext,
    OrchestrationPolicyContract,
    PreliminaryContext,
    Replan,
    RequestProposal,
    TrackRequest,
)
from shared.ids import AgentId, BoxId, ZoneId
from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
from shared.planner_result import NoPlan, PlanFound, PlannerFailure
from shared.skills import (
    GroundedSkillCall,
    SkillName,
    SymbolicallyInapplicable,
    ValidatedCall,
)

from app.box_push_v1 import build_loop
from runtime.policies import (
    POLICY_FACTORIES,
    AdvisoryTwoTrackPolicy,
    SymbolicPrimaryPolicy,
    build_policy,
)

_PUSH = GroundedSkillCall(
    SkillName.PUSH, (AgentId("agent_0"),), BoxId(1), ZoneId("delivery_zone")
)
_GOTO = GroundedSkillCall(
    SkillName.GOTO_PUSH_POSE, (AgentId("agent_0"),), BoxId(0), ZoneId("delivery_zone")
)


def _context(planner_result, head_validation=None, failure_count=0,
             standing_recovery=None):
    """Contexts carry no environment handle by construction; `state=None` proves the
    shipped policies never read it."""
    return OrchestrationContext(preliminary=PreliminaryContext(
        state=None, planner_result=planner_result, head_validation=head_validation,
        failure_count=failure_count, standing_recovery=standing_recovery,
    ))


def _policies(threshold=3):
    return (SymbolicPrimaryPolicy(repeated_failure_threshold=threshold),
            AdvisoryTwoTrackPolicy(repeated_failure_threshold=threshold))


class TestShippedPoliciesSatisfyTheContract(unittest.TestCase):
    def test_both_policies_are_contract_instances(self):
        for policy in _policies():
            self.assertIsInstance(policy, OrchestrationPolicyContract)

    def test_static_witnesses_exist(self):
        from tests import contract_conformance
        self.assertIsInstance(
            contract_conformance.symbolic_primary_policy_conforms(
                SymbolicPrimaryPolicy(repeated_failure_threshold=3)),
            SymbolicPrimaryPolicy,
        )
        self.assertIsInstance(
            contract_conformance.advisory_two_track_policy_conforms(
                AdvisoryTwoTrackPolicy(repeated_failure_threshold=3)),
            AdvisoryTwoTrackPolicy,
        )

    def test_threshold_must_be_positive(self):
        for cls in (SymbolicPrimaryPolicy, AdvisoryTwoTrackPolicy):
            with self.assertRaises(ValueError):
                cls(repeated_failure_threshold=0)


class TestPoliciesArePureDecisionTables(unittest.TestCase):
    """The frozen V1 routing, exercised on bare contexts — no loop, no environment."""

    def test_standing_recovery_preempts_everything(self):
        for policy in _policies():
            decision = policy.decide(_context(
                PlanFound(plan=(_GOTO,)), standing_recovery=_PUSH))
            self.assertIsInstance(decision, Execute)
            self.assertEqual(decision.call, _PUSH)
            self.assertIn("standing NL recovery advice", decision.reason)

    def test_noplan_halts_without_a_call(self):
        for policy in _policies():
            decision = policy.decide(_context(NoPlan(reason="unreachable")))
            self.assertIsInstance(decision, Halt)
            self.assertIsNone(decision.call)
            self.assertIn("semantic result", decision.reason)

    def test_planner_failure_never_reaches_a_decision(self):
        for policy in _policies():
            with self.assertRaises(TypeError):    # typed raise — holds under -O too
                policy.decide(_context(PlannerFailure(error="boom")))

    def test_empty_plan_halts(self):
        for policy in _policies():
            decision = policy.decide(_context(PlanFound(plan=())))
            self.assertIsInstance(decision, Halt)
            self.assertIn("goal already satisfied", decision.reason)

    def test_inapplicable_head_replans(self):
        for policy in _policies():
            decision = policy.decide(_context(
                PlanFound(plan=(_GOTO,)),
                head_validation=SymbolicallyInapplicable(reason="drift")))
            self.assertIsInstance(decision, Replan)

    def test_below_threshold_both_execute_the_head(self):
        for policy in _policies(threshold=3):
            decision = policy.decide(_context(
                PlanFound(plan=(_PUSH,)), head_validation=ValidatedCall(call=_PUSH),
                failure_count=2))
            self.assertIsInstance(decision, Execute)
            self.assertEqual(decision.call, _PUSH)

    def test_the_repeated_failure_escape_is_the_only_strategic_difference(self):
        primary, advisory = _policies(threshold=3)
        context = _context(PlanFound(plan=(_PUSH,)),
                           head_validation=ValidatedCall(call=_PUSH), failure_count=3)
        halt = primary.decide(context)
        self.assertIsInstance(halt, Halt)
        self.assertEqual(halt.call, _PUSH)        # the loop maps call-carrying Halt to
        # HALTED_REPEATED_FAILURE — and the reason is frozen baseline surface (R0 pin)
        self.assertEqual(
            halt.reason,
            "(pre-state, call) failed 3x under SYMBOLIC_PRIMARY — halting with the "
            "discrepancy history rather than strengthening the model",
        )
        request = advisory.decide(context)
        self.assertIsInstance(request, RequestProposal)
        self.assertEqual(request.call, _PUSH)

    def test_decisions_are_deterministic_and_stateless(self):
        """Same context in, same decision out — deciding leaves no residue in the policy."""
        for policy in _policies():
            context = _context(PlanFound(plan=(_GOTO,)),
                               head_validation=ValidatedCall(call=_GOTO))
            before = dict(vars(policy))
            first, second = policy.decide(context), policy.decide(context)
            self.assertEqual(type(first), type(second))
            self.assertEqual(first.call, second.call)
            self.assertEqual(vars(policy), before)


class TestRequiredInputsGovernNLAcquisition(unittest.TestCase):
    def test_symbolic_primary_declares_no_track_inputs(self):
        policy = SymbolicPrimaryPolicy(repeated_failure_threshold=3)
        request = policy.required_inputs(
            PreliminaryContext(state=None, planner_result=NoPlan(reason="x")))
        self.assertFalse(request.nl_proposal)

    def test_advisory_two_track_requests_the_nl_proposal_when_it_would_enact(self):
        """R3 refined the declaration: advisory's information need is NL evidence beside
        every call it ENACTS — requested on would-execute preliminaries (plan head, and
        standing recovery), declined where frozen V1 never consulted (a halting NoPlan)."""
        policy = AdvisoryTwoTrackPolicy(repeated_failure_threshold=3)
        self.assertTrue(policy.required_inputs(
            PreliminaryContext(state=None, planner_result=PlanFound(plan=(_PUSH,)),
                               head_validation=ValidatedCall(call=_PUSH))).nl_proposal)
        self.assertTrue(policy.required_inputs(
            PreliminaryContext(state=None, planner_result=PlanFound(plan=(_PUSH,)),
                               standing_recovery=_GOTO)).nl_proposal)
        self.assertFalse(policy.required_inputs(
            PreliminaryContext(state=None, planner_result=NoPlan(reason="x"))).nl_proposal)

    def test_the_loop_never_calls_propose_when_the_policy_declares_no_inputs(self):
        """Report Phase 2 item 5: the enum gate is gone; the POLICY'S declaration is what
        spares the NL model. A track whose propose() explodes proves the call never
        happens, while observe() still legitimately feeds it."""
        from box_push_v1_adapter import BoxPushV1Adapter
        from domain.box_push_v1 import TASK_DELIVER_BOTH
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager

        class _ProposeForbiddenTrack:
            def __init__(self):
                self.observed = 0

            def observe(self, snapshot, skill=None, outcome=None):
                self.observed += 1

            def propose(self, task):
                raise AssertionError("required_inputs() declared no NL proposal")

        track = _ProposeForbiddenTrack()
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY),
            nl_track=track,
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertGreater(track.observed, 0)

    def test_the_policy_declaration_governs_even_against_the_config_name(self):
        """Discriminates the R2 mechanism from the pre-R2 enum gate (reviewer WARN): the
        injected policy's declaration wins when it DISAGREES with `config.policy`. Under
        the old gate (`config.policy is not ADVISORY_TWO_TRACK`) both halves fail; they
        also fail if the loop rebuilds the policy from config instead of honoring the
        injected object. Kept at the observable seam (was propose() consulted), which
        survives R3 moving the acquisition before the decision."""
        from box_push_v1_adapter import BoxPushV1Adapter
        from domain.box_push_v1 import TASK_DELIVER_BOTH
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager

        class _CountingTrack:
            def __init__(self):
                self.proposed = 0

            def observe(self, snapshot, skill=None, outcome=None):
                pass

            def propose(self, task):
                self.proposed += 1
                return None                     # no proposal content; the call is the point

        class _RequestingPrimary(SymbolicPrimaryPolicy):
            def required_inputs(self, context, /):
                return TrackRequest(nl_proposal=True)

        track = _CountingTrack()
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY),
            nl_track=track,
            policy=_RequestingPrimary(repeated_failure_threshold=3),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertGreater(track.proposed, 0)

        class _DecliningAdvisory(AdvisoryTwoTrackPolicy):
            def required_inputs(self, context, /):
                return TrackRequest(nl_proposal=False)

        class _ProposeForbiddenTrack:
            def observe(self, snapshot, skill=None, outcome=None):
                pass

            def propose(self, task):
                raise AssertionError("the injected policy declined the NL proposal")

        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            nl_track=_ProposeForbiddenTrack(),
            policy=_DecliningAdvisory(repeated_failure_threshold=3),
        )
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.GOAL_REACHED)


class TestRegistryDispatch(unittest.TestCase):
    def test_both_configured_names_build_their_policy(self):
        primary = build_policy(OrchestrationConfig(
            policy=OrchestrationPolicy.SYMBOLIC_PRIMARY, repeated_failure_threshold=7))
        self.assertIsInstance(primary, SymbolicPrimaryPolicy)
        self.assertEqual(primary.repeated_failure_threshold, 7)
        advisory = build_policy(OrchestrationConfig(
            policy=OrchestrationPolicy.ADVISORY_TWO_TRACK))
        self.assertIsInstance(advisory, AdvisoryTwoTrackPolicy)

    def test_registry_keys_are_names_not_enum_members(self):
        self.assertEqual(set(POLICY_FACTORIES),
                         {"symbolic_primary", "advisory_two_track"})
        for key in POLICY_FACTORIES:
            # exact-type check: a StrEnum member would satisfy isinstance(key, str)
            self.assertIs(type(key), str)

    def test_registry_is_open_without_central_edits(self):
        """A new strategy is a registry entry, not an enum/orchestrator edit."""
        sentinel = object()
        POLICY_FACTORIES["r2_test_probe"] = lambda config: sentinel
        try:
            class _NamedConfig:
                policy = "r2_test_probe"
            self.assertIs(build_policy(_NamedConfig()), sentinel)
        finally:
            del POLICY_FACTORIES["r2_test_probe"]

    def test_unknown_name_is_refused_loudly(self):
        class _NamedConfig:
            policy = "no_such_policy"
        with self.assertRaises(LookupError):
            build_policy(_NamedConfig())


class TestLoopAcceptsAnInjectedPolicyObject(unittest.TestCase):
    """Phase 2 acceptance: adding a test policy requires no edits to runtime/loop.py —
    this novel class exists only here and drives a real episode via injection."""

    def test_an_injected_novel_policy_drives_the_episode(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from domain.box_push_v1 import TASK_DELIVER_BOTH
        from runtime.loop import EpisodeOutcome, ExecutiveLoopManager

        class _HaltImmediatelyPolicy:
            def __init__(self):
                self.consulted = 0

            def required_inputs(self, context):
                return TrackRequest()

            def decide(self, context):
                self.consulted += 1
                return Halt(reason="r2 injected test policy halts on sight")

        policy = _HaltImmediatelyPolicy()
        loop = build_loop(BoxPushV1Adapter(), TASK_DELIVER_BOTH, policy=policy)
        self.assertIs(loop.policy, policy)
        episode = loop.run()
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_NO_PLAN)
        self.assertEqual(episode.reason, "r2 injected test policy halts on sight")
        self.assertEqual(policy.consulted, 1)
        self.assertEqual(loop.executive_steps_charged, 0)     # nothing executed

    def test_omitting_the_policy_still_builds_from_the_config_name(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        from domain.box_push_v1 import TASK_DELIVER_BOTH
        from runtime.loop import ExecutiveLoopManager
        loop = build_loop(
            BoxPushV1Adapter(), TASK_DELIVER_BOTH,
            OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK))
        self.assertIsInstance(loop.policy, AdvisoryTwoTrackPolicy)
        loop.env.close()


class TestPolicyCannotReachTheEnvironment(unittest.TestCase):
    """Structural acceptance: no surface through which a policy could execute the backend."""

    def test_policies_module_imports_only_stdlib_and_shared(self):
        path = pathlib.Path(_REPO_ROOT) / "runtime" / "policies.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed = {"__future__", "typing", "dataclasses", "shared"}
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                self.assertIn(
                    root, allowed,
                    f"runtime/policies.py imports {root!r} — policies may depend only on "
                    f"stdlib typing machinery and shared (no backend, executor, or domain)",
                )

    def test_policy_state_is_only_its_configuration(self):
        for policy in _policies():
            self.assertEqual(vars(policy), {"repeated_failure_threshold": 3})


if __name__ == "__main__":
    unittest.main()
