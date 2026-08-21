"""Invariants that adversarial mutation testing showed the first-pass suite did not catch.

Each test here names the mutation it exists to kill.
"""
import os
import pathlib
import subprocess
import sys
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    DOMAIN_IR,
    MODEL_VERSION,
    PREDICATES,
    PROJECTION,
    P_DELIVERED,
    P_DIFFERENT,
    P_HEAVY,
    P_IN_POSE,
    P_LIGHT,
    P_PENDING,
    TASK_DELIVER_LIGHT,
    initial_state,
    project,
)
from runtime.executive_history import ExecutiveHistory
from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.divergence import DivergenceKind, TrackDivergence
from shared.execution import (
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    RawLabel,
    StepAccounting,
)
from shared.faults import FaultKind, InfrastructureFault
from shared.ids import AgentId, BoxId, ZoneId
from shared.planner_result import NoPlan, PlanFound, PlannerFailure
from shared.reports import ConfidenceReport, CoverageReport
from shared.skill_ir import DomainIR, Effect, Predicate, PredicateDecl, SkillIR
from shared.skills import (
    REGISTRY,
    GroundedSkillCall,
    MalformedCall,
    ParameterType,
    SkillName,
    SkillSignature,
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)
from shared.state_snapshot import BoxSnapshot, EpisodeSnapshot, StateSnapshot
from shared.trace_schema import TraceEntry
from shared.versioning import Provenance

#: Pinned so the "freeze" is an actual freeze. Verified identical under PYTHONHASHSEED 0/1/12345.

def _moved(state=None):
    """A world that differs from `initial_state()` in exactly one box position."""
    s = state if state is not None else initial_state()
    b = s.box(BOX_LIGHT)
    return s.with_box(BoxSnapshot(b.box_id, (5, 4), b.required_agents, b.is_target, b.delivered))


GOLDEN_DOMAIN_DIGEST = "b41503536b3bcbe1"
GOLDEN_INITIAL_WORLD_KEY = "f7cf4105cddd127a"
GOLDEN_INITIAL_SYMBOLIC_KEY = "48b414cda26a60e3"


class TestGoldenFreeze(unittest.TestCase):
    """Kills mutation AC: `digest()` dropping the action model went undetected because the only
    assertion was `digest() == digest()` in one process."""

    def test_domain_digest_matches_the_pinned_value(self):
        self.assertEqual(DOMAIN_IR.digest()[:16], GOLDEN_DOMAIN_DIGEST)

    def test_initial_world_key_matches_the_pinned_value(self):
        self.assertEqual(initial_state().world_key()[:16], GOLDEN_INITIAL_WORLD_KEY)

    def test_initial_symbolic_projection_matches_the_pinned_value(self):
        self.assertEqual(project(initial_state()).key()[:16], GOLDEN_INITIAL_SYMBOLIC_KEY)

    def test_digests_are_stable_across_processes(self):
        """:88 requires these keys to work for replay, i.e. across runs — so a same-process
        equality check is not evidence."""
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        code = (
            f"import sys; sys.path.insert(0, {str(repo_root)!r});"
            "from domain.box_push_v1 import DOMAIN_IR, initial_state, project;"
            "print(DOMAIN_IR.digest()[:16], initial_state().world_key()[:16],"
            " project(initial_state()).key()[:16])"
        )
        out = subprocess.run(
            [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
            cwd=repo_root,          # the suite must not depend on the caller's cwd
            # `-B` + PYTHONDONTWRITEBYTECODE: without them this child repopulates `__pycache__`
            # inside the repository even when the parent ran under `python -B`, which is exactly
            # the stale-.pyc mechanism that makes same-length mutations report false SURVIVED.
            # Inherit the environment rather than replacing it, so an interpreter that needs
            # LD_LIBRARY_PATH/CONDA_PREFIX does not fail spuriously.
            env={**os.environ, "PYTHONHASHSEED": "12345", "PYTHONDONTWRITEBYTECODE": "1"},
        ).stdout.split()
        self.assertEqual(
            out,
            [GOLDEN_DOMAIN_DIGEST, GOLDEN_INITIAL_WORLD_KEY, GOLDEN_INITIAL_SYMBOLIC_KEY],
        )


class TestSnapshotEqualityDelegates(unittest.TestCase):
    """The generated dataclass equality would have included `episode`, so `predicted == observed`
    would have used a different criterion from `world_key()`."""

    def test_replace_episode_actually_replaces_the_episode(self):
        """Three equality tests below assert that episode bookkeeping is IGNORED. If
        `replace_episode` were a no-op they would all pass vacuously."""
        busy = initial_state().replace_episode(
            EpisodeSnapshot(step_count=42, terminated=True, truncated=False)
        )
        self.assertEqual(busy.episode.step_count, 42)
        self.assertTrue(busy.episode.terminated)
        self.assertNotEqual(busy.replay_key(), initial_state().replay_key())

    def test_equality_ignores_episode_bookkeeping(self):
        a = initial_state()
        b = a.replace_episode(EpisodeSnapshot(step_count=42, truncated=True))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)

    def test_equality_detects_a_world_change(self):
        a = initial_state()
        box = a.box(BOX_LIGHT)
        b = a.with_box(BoxSnapshot(box.box_id, (1, 4), box.required_agents, box.is_target, True))
        self.assertNotEqual(a, b)

    def test_dict_membership_uses_the_world_key(self):
        a = initial_state()
        self.assertEqual({a: "x"}[a.replace_episode(EpisodeSnapshot(step_count=9))], "x")

    def test_not_equal_to_other_types(self):
        self.assertNotEqual(initial_state(), "not a snapshot")


class TestCallKeyIncludesEverything(unittest.TestCase):
    """Kills mutation Z: `key()` omitting the skill name let two different skills share a
    repeated-failure bucket and trip the threshold together."""

    def test_different_skills_with_identical_arguments_have_different_keys(self):
        push = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        goto = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        self.assertNotEqual(push.key(), goto.key())

    def test_different_agents_have_different_keys(self):
        a = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        b = GroundedSkillCall(SkillName.PUSH, (AGENT_1,), BOX_LIGHT, DELIVERY_ZONE)
        self.assertNotEqual(a.key(), b.key())

    def test_repeated_failure_buckets_do_not_collide_across_skills(self):
        pre = initial_state()
        h = ExecutiveHistory()
        push = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        goto = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        h.append(_entry_with(pre, push))
        self.assertEqual(h.failure_count(pre, push), 1)
        self.assertEqual(h.failure_count(pre, goto), 0)


def _entry_with(pre, call, raw_label=RawLabel.TOO_HEAVY):
    return TraceEntry(
        executive_step=0,
        task=TASK_DELIVER_LIGHT,
        pre_state=pre,
        model_version=MODEL_VERSION,
        provenance=Provenance(source="tests", model_version=MODEL_VERSION),
        execution=ExecutionResult(
            call=call,
            outcome=ExecutionOutcome.FAILURE,
            pre_state=pre,
            post_state=pre,
            accounting=StepAccounting(1, 2),
            raw_label=raw_label,
            failure_class=FailureStateClass.UNCHANGED,
        ),
    )


class TestRawLabelIsNotAuthoritative(unittest.TestCase):
    """The BINDING RULE in shared/execution.py was documented but never enforced."""

    def test_bookkeeping_ignores_the_raw_label(self):
        """Two failures of the same call differing ONLY in raw_label must share one bucket —
        otherwise the belief-derived `too_heavy`/`blocked` distinction would leak into the
        repeated-failure threshold."""
        pre = initial_state()
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        h = ExecutiveHistory()
        h.append(_entry_with(pre, call, raw_label=RawLabel.TOO_HEAVY))
        h.append(_entry_with(pre, call, raw_label=RawLabel.BLOCKED))
        self.assertEqual(h.failure_count(pre, call), 2)

    def test_outcome_is_independent_of_raw_label(self):
        pre = initial_state()
        for raw in (RawLabel.TOO_HEAVY, RawLabel.BLOCKED, RawLabel.PUSHED):
            with self.subTest(raw=raw):
                r = ExecutionResult(
                    call=GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
                    outcome=ExecutionOutcome.FAILURE,
                    pre_state=pre,
                    post_state=pre,
                    accounting=StepAccounting(1, 2),
                    raw_label=raw,
                    failure_class=FailureStateClass.UNCHANGED,
                )
                self.assertIs(r.outcome, ExecutionOutcome.FAILURE)


class TestFailureClassIsChecked(unittest.TestCase):
    """A declared failure class must match the observed states, not merely be asserted."""

    def _result(self, failure_class, post):
        return ExecutionResult(
            call=GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
            outcome=ExecutionOutcome.PARTIAL,
            pre_state=initial_state(),
            post_state=post,
            accounting=StepAccounting(1, 5),
            failure_class=failure_class,
        )

    def _moved(self):
        return _moved()

    def test_partial_execution_requires_a_changed_world(self):
        with self.assertRaises(ValueError):
            self._result(FailureStateClass.PARTIAL_EXECUTION, initial_state())

    def test_unchanged_requires_an_unchanged_world(self):
        with self.assertRaises(ValueError):
            self._result(FailureStateClass.UNCHANGED, self._moved())

    def test_rejected_requires_an_unchanged_world(self):
        with self.assertRaises(ValueError):
            self._result(FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION, self._moved())

    def test_consistent_classifications_are_accepted(self):
        self._result(FailureStateClass.PARTIAL_EXECUTION, self._moved())
        self._result(FailureStateClass.UNCHANGED, initial_state())


class TestMutuallyExclusiveClassification(unittest.TestCase):
    """Kills mutation J. A 3-cycle of assertNotIsInstance covers only one direction per pair and
    is satisfiable under a conflating hierarchy."""

    def test_rejection_kinds_are_pairwise_unrelated(self):
        kinds = [
            ValidatedCall(GroundedSkillCall(SkillName.WAIT, (AGENT_0,))),
            MalformedCall("bad"),
            UngroundedCall("no such box"),
            SymbolicallyInapplicable("light(box_0) false"),
        ]
        for a in kinds:
            for b in kinds:
                if a is b:
                    continue
                with self.subTest(a=type(a).__name__, b=type(b).__name__):
                    self.assertNotIsInstance(a, type(b))

    def test_only_malformed_and_ungrounded_are_infrastructure_faults(self):
        """This is the routing that mutation J broke: promoting SymbolicallyInapplicable to a
        fault would make every inapplicable symbolic call short-circuit the cycle."""
        self.assertTrue(MalformedCall("x").is_infrastructure_fault)
        self.assertTrue(UngroundedCall("x").is_infrastructure_fault)
        self.assertFalse(SymbolicallyInapplicable("x").is_infrastructure_fault)
        self.assertFalse(
            ValidatedCall(GroundedSkillCall(SkillName.WAIT, (AGENT_0,))).is_infrastructure_fault
        )

    def test_rejection_conversions_use_the_right_fault_kinds(self):
        self.assertIs(
            MalformedCall("x").to_infrastructure_fault().kind, FaultKind.MALFORMED_SKILL_CALL
        )
        self.assertIs(
            UngroundedCall("x").to_infrastructure_fault().kind, FaultKind.MISSING_GROUNDING
        )
        self.assertFalse(hasattr(SymbolicallyInapplicable("x"), "to_infrastructure_fault"))

    def test_report_channels_are_pairwise_unrelated(self):
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        channels = [
            ExecutionDiscrepancy(kind=DiscrepancyKind.UNEXPECTED_OUTCOME, call=call),
            TrackDivergence(kind=DivergenceKind.COVERAGE_GAP),
            InfrastructureFault(kind=FaultKind.MISSING_GROUNDING, message="x"),
        ]
        for a in channels:
            for b in channels:
                if a is b:
                    continue
                with self.subTest(a=type(a).__name__, b=type(b).__name__):
                    self.assertNotIsInstance(a, type(b))

    def test_abstract_bases_cannot_be_instantiated(self):
        from shared.planner_result import PlannerResult
        from shared.skills import CallValidation
        for base in (PlannerResult, CallValidation):
            with self.subTest(base=base.__name__):
                with self.assertRaises(TypeError):
                    base()


class TestCrossLayerSignatureIdentity(unittest.TestCase):
    """Kills mutation H: a hand-built SkillSignature let the IR drift from the registry."""

    def test_ir_uses_the_registry_signature_object_itself(self):
        for skill in DOMAIN_IR.skills:
            with self.subTest(skill=skill.name):
                self.assertIs(skill.signature, REGISTRY.get(skill.name))

    def test_domain_rejects_a_look_alike_signature(self):
        fake = SkillSignature(
            name=SkillName.PUSH,
            parameters=REGISTRY.get(SkillName.PUSH).parameters,
            backend_mapping="fake",
            backend_dispatch_key="fake",
        )
        drifting = SkillIR(
            signature=fake,
            parameters=("agent", "box", "zone"),
            parameter_types=("agent", "box", "zone"),
            preconditions=(),
            effects=(Effect(Predicate(P_DELIVERED, ("box",))),),
            provenance=DOMAIN_IR.provenance,
        )
        with self.assertRaises(ValueError):
            DomainIR(
                name="drift",
                model_version=MODEL_VERSION,
                predicates=DOMAIN_IR.predicates,
                skills=(drifting,),
                provenance=DOMAIN_IR.provenance,
            )

    def test_ir_parameter_types_must_match_the_signature_expansion(self):
        with self.assertRaises(ValueError):
            SkillIR(
                signature=REGISTRY.get(SkillName.PUSH),
                parameters=("agent", "box", "zone"),
                parameter_types=("agent", "agent", "zone"),   # box mistyped
                preconditions=(),
                effects=(Effect(Predicate(P_DELIVERED, ("box",))),),
                provenance=DOMAIN_IR.provenance,
            )

    def test_predicate_argument_types_are_validated(self):
        """Kills the swapped-argument bug: in_pose(box, agent) passed an arity-only check."""
        swapped = SkillIR(
            signature=REGISTRY.get(SkillName.PUSH),
            parameters=("agent", "box", "zone"),
            parameter_types=("agent", "box", "zone"),
            preconditions=(Predicate(P_IN_POSE, ("box", "agent")),),   # swapped
            effects=(Effect(Predicate(P_DELIVERED, ("box",))),),
            provenance=DOMAIN_IR.provenance,
        )
        with self.assertRaises(ValueError):
            DomainIR(
                name="swapped",
                model_version=MODEL_VERSION,
                predicates=DOMAIN_IR.predicates,
                skills=(swapped,),
                provenance=DOMAIN_IR.provenance,
            )


class TestBindingValues(unittest.TestCase):
    """Kills mutation G: asserting only the KEY SET made a total argument scramble invisible."""

    def test_binding_values_are_exact(self):
        call = GroundedSkillCall(
            SkillName.COOPERATIVE_PUSH, (AGENT_1, AGENT_0), BOX_HEAVY, DELIVERY_ZONE
        )
        self.assertEqual(
            DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH).bind(call),
            {"agent1": "agent_0", "agent2": "agent_1", "box": "box_0", "zone": "delivery_zone"},
        )

    def test_single_agent_binding_values_are_exact(self):
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        self.assertEqual(
            DOMAIN_IR.skill(SkillName.PUSH).bind(call),
            {"agent": "agent_0", "box": "box_1", "zone": "delivery_zone"},
        )

    def test_bind_unbind_round_trips(self):
        for call in (
            GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
            GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_1,), BOX_HEAVY, DELIVERY_ZONE),
            GroundedSkillCall(SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE),
        ):
            with self.subTest(call=str(call)):
                ir = DOMAIN_IR.skill(call.skill)
                self.assertEqual(ir.unbind(ir.bind(call)), call)

    def test_unbind_recanonicalizes_the_symmetric_agent_pair(self):
        """`different(?a1,?a2)` is symmetric, so a planner grounds both orderings; both must
        collapse to the same GroundedSkillCall."""
        ir = DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH)
        forward = {"agent1": "agent_0", "agent2": "agent_1", "box": "box_0", "zone": "delivery_zone"}
        reverse = {"agent1": "agent_1", "agent2": "agent_0", "box": "box_0", "zone": "delivery_zone"}
        self.assertEqual(ir.unbind(forward), ir.unbind(reverse))

    def test_box_identity_round_trips_through_text(self):
        self.assertEqual(BoxId.parse(str(BOX_HEAVY)), BOX_HEAVY)
        with self.assertRaises(ValueError):
            BoxId.parse("agent_0")


class TestPreconditionLockdown(unittest.TestCase):
    """Kills mutation K: additive `assertIn` checks let a `push_feasible` precondition be added to
    Push and CooperativePush — the two skills that actually deliver boxes — without a failure."""

    EXPECTED = {
        SkillName.GOTO_PUSH_POSE: {"discovered", "pending"},
        SkillName.PUSH: {P_IN_POSE, P_LIGHT, P_PENDING},
        SkillName.COOPERATIVE_PUSH: {P_DIFFERENT, P_HEAVY, P_IN_POSE, P_PENDING},
    }

    def test_precondition_sets_are_exact_for_every_skill(self):
        for name, expected in self.EXPECTED.items():
            with self.subTest(skill=name):
                actual = {str(p.name) for p in DOMAIN_IR.skill(name).preconditions}
                self.assertEqual(actual, expected)

    def test_no_skill_may_use_a_predicate_outside_the_frozen_declarations(self):
        """An allowlist, not a substring blacklist: `feasible`, `can_push`, `navigable`, `route`
        and friends all passed the old token check."""
        allowed = {str(p.name) for p in PREDICATES}
        for skill in DOMAIN_IR.skills:
            used = {str(p.name) for p in skill.preconditions}
            used |= {str(e.predicate.name) for e in skill.effects}
            with self.subTest(skill=skill.name):
                self.assertTrue(used.issubset(allowed), f"{skill.name} uses {used - allowed}")

    def test_the_frozen_predicate_set_is_exactly_seven(self):
        self.assertEqual(
            {str(p.name) for p in PREDICATES},
            {"discovered", "delivered", "pending", "light", "heavy", "in_pose", "different"},
        )

    def test_adding_a_feasibility_predicate_to_the_domain_is_detectable(self):
        """The allowlist above is what makes this fail; the substring blacklist did not."""
        extended = PREDICATES + (PredicateDecl("push_feasible", ("agent", "box")),)
        feasible_push = SkillIR(
            signature=REGISTRY.get(SkillName.PUSH),
            parameters=("agent", "box", "zone"),
            parameter_types=("agent", "box", "zone"),
            preconditions=(Predicate("push_feasible", ("agent", "box")),),
            effects=(Effect(Predicate(P_DELIVERED, ("box",))),),
            provenance=DOMAIN_IR.provenance,
        )
        rogue = DomainIR(
            name="rogue", model_version=MODEL_VERSION, predicates=extended,
            skills=(feasible_push,), provenance=DOMAIN_IR.provenance,
        )
        allowed = {str(p.name) for p in PREDICATES}
        used = {str(p.name) for p in rogue.skill(SkillName.PUSH).preconditions}
        self.assertFalse(used.issubset(allowed))


class TestTraceCompleteness(unittest.TestCase):
    """Kills mutation V: `canonical()` silently dropping eight fields went undetected because no
    test ever populated a proposal, report, prediction or discrepancy."""

    REQUIRED = (
        "executive_step", "task", "pre_state", "post_state", "model_version", "provenance",
        "symbolic_result", "symbolic_proposal", "nl_proposal", "coverage", "confidence",
        "decision", "selected_call", "validation", "predicted_world_key", "predicted_symbolic_key", "execution",
        "discrepancies", "divergences", "faults",
    )

    def _populated_entry(self):
        pre = initial_state()
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        from shared.orchestration_config import ExecutiveDecision
        return TraceEntry(
            executive_step=3,
            task=TASK_DELIVER_LIGHT,
            pre_state=pre,
            model_version=MODEL_VERSION,
            provenance=Provenance(source="tests", model_version=MODEL_VERSION),
            symbolic_result=PlanFound(plan=(call,), model_version=MODEL_VERSION),
            symbolic_proposal=call,
            nl_proposal=GroundedSkillCall(SkillName.EXPLORE, (AGENT_1,)),
            coverage=CoverageReport(covered=("deliver box_1",), residual=("quickly",)),
            confidence=(ConfidenceReport(source="symbolic", confidence=0.9),),
            decision=ExecutiveDecision.EXECUTE,
            selected_call=call,
            validation=ValidatedCall(call=call),
            predicted_world_key=pre.world_key(),
            predicted_symbolic_key=PROJECTION.monitored_key(project(pre)),
            execution=ExecutionResult(
                call=call, outcome=ExecutionOutcome.PARTIAL, pre_state=pre, post_state=_moved(pre),
                accounting=StepAccounting(1, 4), raw_label=RawLabel.TOO_HEAVY,
                failure_class=FailureStateClass.PARTIAL_EXECUTION,
            ),
            post_state=_moved(pre),
            discrepancies=(ExecutionDiscrepancy(
                kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, call=call),),
            divergences=(TrackDivergence(kind=DivergenceKind.CONTRADICTION),),
            faults=(InfrastructureFault(kind=FaultKind.BACKEND_API_EXCEPTION, message="lm down"),),
        )

    def test_canonical_carries_every_required_field(self):
        blob = self._populated_entry().canonical()
        for key in self.REQUIRED:
            with self.subTest(field=key):
                self.assertIn(key, blob)

    def test_populated_fields_are_not_dropped(self):
        blob = self._populated_entry().canonical()
        for key in (
            "symbolic_result", "symbolic_proposal", "nl_proposal", "coverage",
            "decision", "selected_call", "validation", "predicted_world_key",
            "predicted_symbolic_key", "execution",
        ):
            with self.subTest(field=key):
                self.assertIsNotNone(blob[key], f"{key} was dropped from the trace")
        self.assertEqual(len(blob["confidence"]), 1)
        self.assertEqual(len(blob["discrepancies"]), 1)
        self.assertEqual(len(blob["divergences"]), 1)
        self.assertEqual(len(blob["faults"]), 1)

    def test_populated_fields_carry_the_RIGHT_VALUES_not_merely_a_value(self):
        """Presence checks miss the likelier regression: a field that is still emitted but now
        carries the wrong thing. Mutation testing showed nine such corruptions surviving — among
        them the failure POST-STATE and the STEP ACCOUNTING, the two records
        `.claude/rules/testing.md` names explicitly for a failed skill."""
        entry = self._populated_entry()
        blob = entry.canonical()

        # identity of the states, keyed on the world basis (not replay — that includes episode)
        self.assertEqual(blob["pre_state"], entry.pre_state.world_key())
        self.assertNotEqual(blob["pre_state"], entry.pre_state.replay_key())
        self.assertEqual(blob["post_state"], entry.post_state.world_key())
        self.assertEqual(
            blob["execution"]["post_state"], entry.execution.post_state.world_key()
        )
        self.assertNotEqual(
            blob["execution"]["pre_state"], blob["execution"]["post_state"],
            "the fixture must have a discriminative post-state or this proves nothing",
        )

        # step accounting, and that the two counters are not transposed
        self.assertEqual(
            blob["execution"]["accounting"],
            {"executive_steps": 1, "primitive_steps": 4},
        )

        # the two proposals must remain distinguishable — collapsing them destroys the evidence
        # TrackDivergence is built from
        self.assertEqual(blob["symbolic_proposal"], entry.symbolic_proposal.canonical())
        self.assertEqual(blob["nl_proposal"], entry.nl_proposal.canonical())
        self.assertNotEqual(blob["nl_proposal"], blob["symbolic_proposal"])

        # typed verdicts survive as their own names / values
        self.assertEqual(blob["selected_call"], entry.selected_call.canonical())
        self.assertEqual(blob["validation"], type(entry.validation).__name__)
        self.assertEqual(blob["decision"], str(entry.decision))
        self.assertEqual(blob["symbolic_result"], entry.symbolic_result.canonical())
        self.assertTrue(blob["symbolic_result"]["plan"], "the plan was emptied")
        self.assertEqual(blob["execution"]["raw_label"], str(entry.execution.raw_label))
        self.assertEqual(
            blob["execution"]["failure_class"], str(entry.execution.failure_class)
        )
        self.assertEqual(blob["faults"][0]["kind"], str(entry.faults[0].kind))
        self.assertEqual(
            blob["discrepancies"][0]["kind"], str(entry.discrepancies[0].kind)
        )
        self.assertEqual(blob["divergences"][0]["kind"], str(entry.divergences[0].kind))

        # the two prediction bases must stay distinct fields with distinct values
        self.assertEqual(blob["predicted_world_key"], entry.predicted_world_key)
        self.assertEqual(blob["predicted_symbolic_key"], entry.predicted_symbolic_key)
        self.assertNotEqual(blob["predicted_world_key"], blob["predicted_symbolic_key"])

    def test_the_three_channels_stay_separate_in_a_trace(self):
        blob = self._populated_entry().canonical()
        self.assertEqual(blob["discrepancies"][0]["channel"], "ExecutionDiscrepancy")
        self.assertEqual(blob["divergences"][0]["channel"], "TrackDivergence")
        self.assertEqual(blob["faults"][0]["channel"], "InfrastructureFault")


class TestValidatorsReject(unittest.TestCase):
    """The frozen schemas' raise-paths were entirely unexercised (:176 'validated ... schemas')."""

    def test_identity_validators(self):
        for bad in ("", None, 5):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    AgentId(bad)
        for bad in (-1, True, "0"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    BoxId(bad)
        with self.assertRaises(ValueError):
            ZoneId("")

    def test_state_validators(self):
        s = initial_state()
        with self.assertRaises(ValueError):
            BoxSnapshot(BOX_LIGHT, (1, 1), required_agents=0, is_target=True, delivered=False)
        with self.assertRaises(ValueError):
            EpisodeSnapshot(step_count=-1)
        with self.assertRaises(ValueError):
            type(s.static)(width=0, height=4, walls=(), delivery_zone=())

    def test_a_precondition_naming_an_undeclared_parameter_is_refused(self):
        """Only the EFFECTS loop was exercised; the precondition loop was deletable."""
        from shared.skill_ir import SkillIR
        base = DOMAIN_IR.skill(SkillName.PUSH)
        with self.assertRaises(ValueError):
            SkillIR(
                signature=base.signature, parameters=base.parameters,
                parameter_types=base.parameter_types,
                preconditions=(Predicate(P_PENDING, ("nonexistent",)),),
                effects=base.effects, provenance=base.provenance,
            )

    def test_registry_and_ir_validators(self):
        with self.assertRaises(ValueError):
            SkillSignature(name=SkillName.WAIT, parameters=(), cost=-1)
        with self.assertRaises(ValueError):
            PredicateDecl("bad name!", ("box",))
        with self.assertRaises(ValueError):
            InfrastructureFault(kind=FaultKind.BACKEND_API_EXCEPTION, message="")
        with self.assertRaises(ValueError):
            DomainIR(
                name="dup", model_version=MODEL_VERSION,
                predicates=PREDICATES + (PredicateDecl(P_LIGHT, ("box",)),),
                skills=(), provenance=DOMAIN_IR.provenance,
            )

    def test_predicate_arity_mismatch_is_rejected(self):
        wrong_arity = SkillIR(
            signature=REGISTRY.get(SkillName.PUSH),
            parameters=("agent", "box", "zone"),
            parameter_types=("agent", "box", "zone"),
            preconditions=(Predicate(P_LIGHT, ("box", "agent")),),   # declared arity 1
            effects=(Effect(Predicate(P_DELIVERED, ("box",))),),
            provenance=DOMAIN_IR.provenance,
        )
        with self.assertRaises(ValueError):
            DomainIR(
                name="arity", model_version=MODEL_VERSION, predicates=PREDICATES,
                skills=(wrong_arity,), provenance=DOMAIN_IR.provenance,
            )

    def test_versioning_validators(self):
        from shared.versioning import ModelVersion
        with self.assertRaises(ValueError):
            ModelVersion(revision=-1)
        with self.assertRaises(ValueError):
            Provenance(source="", model_version=MODEL_VERSION)

    def test_planner_result_and_report_validators(self):
        with self.assertRaises(ValueError):
            NoPlan(reason="")
        with self.assertRaises(ValueError):
            PlannerFailure(error="")
        with self.assertRaises(ValueError):
            ConfidenceReport(source="symbolic", confidence=-0.1)


class TestPublicSurface(unittest.TestCase):
    """`:82` makes the exported names part of the contract."""

    def test_every_exported_name_resolves(self):
        import shared
        for name in shared.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(shared, name), f"shared.__all__ lists missing {name}")

    def test_executive_history_is_not_exported_from_shared(self):
        """It is P4 runtime state and lives in `runtime/`, so symbolic code cannot reach it via
        the contract package."""
        import shared
        self.assertNotIn("ExecutiveHistory", shared.__all__)
        self.assertFalse(hasattr(shared, "ExecutiveHistory"))


if __name__ == "__main__":
    unittest.main()
