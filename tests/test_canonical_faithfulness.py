"""`canonical()` must be FAITHFUL: every field it claims to carry must actually depend on the
source value.

WHY THIS MODULE EXISTS
----------------------
Serialization was tested field-by-field, and almost entirely for KEY PRESENCE. Adversarial
mutation showed the consequence: a `canonical()` that emits the right key carrying a constant, a
mirror of a neighbouring field, or an empty container passes a presence check unchanged. Roughly
thirty such corruptions survived the suite, including the ones that matter most —

    "post_state": self.pre_state.world_key()      # failure post-state erased
    "accounting": None                            # executive/primitive steps erased
    "outcome": "failure"                          # the authoritative typed outcome frozen
    "task": {}                                    # the task erased from the trace
    "observed_world_key": self.predicted_world_key  # a mismatch collapsed to "no mismatch"

— all of which `.claude/rules/testing.md` requires a trace to record.

Patching them one assertion at a time does not converge: the contract surface carries dozens of
canonical-bearing types and the next added field starts out unprotected again. So this module
states the general property instead.

THE PROPERTY
------------
For a type whose `canonical()` emits key K, there must exist two instances whose serialized K
DIFFERS. Stated per-key, not per-object: an earlier version compared whole dicts, so any single
differing key satisfied it and a variant that moved two fields proved nothing about either. And
the key list is derived from `canonical()` itself, so a NEWLY ADDED field is unprotected only
until the coverage test runs — which was the whole point and was not previously delivered.

Together these kill every corruption listed above: a constant cannot vary, a mirror varies with
the wrong key, an emptied container never varies, and a dropped key is absent from the reference.

It is deliberately a DIFFERENCE test, not an equality-to-a-literal test. Pinning literals would
re-freeze the same golden-value brittleness that made the domain digest an undifferentiated change
detector; pinning *sensitivity* survives legitimate reformatting while still catching erasure.

WHAT IT DOES NOT COVER
----------------------
Fields deliberately EXCLUDED from a canonical form — `EpisodeSnapshot` inside `canonical_world()`,
for instance — are the opposite property and are asserted where that exclusion is specified
(`tests/test_state_snapshot.py`, `tests/test_contract_invariants.py`). A field listed here as
excluded is checked to be insensitive, so the exclusion cannot silently reverse either.
"""
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    DOMAIN_IR,
    MODEL_VERSION,
    PROJECTION,
    TASK_DELIVER_BOTH,
    initial_state,
    project,
)
from shared.comparison_keys import SymbolicKey, WorldKey
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
from shared.observation import ExecutiveObservation
from shared.orchestration_config import (
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.planner_result import NoPlan, PlanFound, PlannerFailure
from shared.reports import ConfidenceReport, CoverageReport
from shared.skill_ir import Effect, Predicate
from shared.skills import GroundedSkillCall, SkillName, ValidatedCall
from shared.state_snapshot import (
    AgentSnapshot,
    BoxSnapshot,
    EpisodeSnapshot,
    StateSnapshot,
    StaticWorld,
)
from shared.task import Task
from shared.trace_schema import TraceEntry
from shared.versioning import ModelVersion, Provenance

PRE = initial_state()
CALL = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
PROV = Provenance(source="tests", model_version=MODEL_VERSION)


def _delivered(state=PRE):
    """Symbolically distinct. `_moved` changes only a position, which `project()` ignores BY
    DESIGN — so it cannot be used to vary a symbolic key."""
    b = state.box(BOX_LIGHT)
    return state.with_box(
        BoxSnapshot(b.box_id, (1, 4), b.required_agents, b.is_target, True)
    )


def _moved(state=PRE, cell=(5, 4)):
    b = state.box(BOX_LIGHT)
    return state.with_box(
        BoxSnapshot(b.box_id, cell, b.required_agents, b.is_target, b.delivered)
    )


def _execution(**overrides):
    kwargs = dict(
        call=CALL,
        outcome=ExecutionOutcome.PARTIAL,
        pre_state=PRE,
        post_state=_moved(),
        accounting=StepAccounting(1, 4),
        # `blocked` is producible by Push, GotoPushPose AND CooperativePush, so a variant may
        # change the CALL alone. A Push-only label here would make every call-variant also vary
        # `raw_label`, and a frozen `"call": {}` would still differ from the base.
        raw_label=RawLabel.BLOCKED,
        failure_class=FailureStateClass.PARTIAL_EXECUTION,
    )
    kwargs.update(overrides)
    return ExecutionResult(**kwargs)


def _trace(**overrides):
    kwargs = dict(
        executive_step=3,
        task=TASK_DELIVER_BOTH,
        pre_state=PRE,
        model_version=MODEL_VERSION,
        provenance=PROV,
        symbolic_result=PlanFound(plan=(CALL,), model_version=MODEL_VERSION),
        symbolic_proposal=CALL,
        nl_proposal=GroundedSkillCall(SkillName.EXPLORE, (AGENT_1,)),
        coverage=CoverageReport(covered=("deliver box_1",), residual=("quickly",)),
        confidence=(ConfidenceReport(source="symbolic", confidence=0.9),),
        decision=ExecutiveDecision.EXECUTE,
        selected_call=CALL,
        validation=ValidatedCall(call=CALL),
        predicted_world_key=_moved().world_key(),
        predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
        execution=_execution(),
        post_state=_moved(),
        discrepancies=(
            ExecutionDiscrepancy(
                kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, call=CALL
            ),
        ),
        divergences=(TrackDivergence(kind=DivergenceKind.CONTRADICTION),),
        faults=(InfrastructureFault(kind=FaultKind.BACKEND_API_EXCEPTION, message="lm down"),),
    )
    kwargs.update(overrides)
    return TraceEntry(**kwargs)


#: Types whose canonical form is pinned by a dedicated module, with the reason. Single source of
#: truth: both the coverage test and the honesty check read THIS, so they cannot drift apart.
VERIFIED_ELSEWHERE = {
    "StateSnapshot":       "tests/test_state_snapshot.py — world vs replay forms, field sensitivity",
    "SkillIR":             "tests/test_prediction_and_monitoring.py — FROZEN_EFFECTS, verbatim",
    "DomainIR":            "golden digest + tests/test_domain_freeze.py",
    "ProjectionContract":  "tests/test_symbolic_projection.py",
    "SymbolicState":       "tests/test_symbolic_projection.py — sorted canonical form",
    "GroundedLiteral":     "tests/test_symbolic_projection.py",
}


#: Keys that are DELIBERATELY constant — discriminator tags, not payload. Exempt from the
#: sensitivity property (they cannot vary by construction) and pinned by value instead.
CONSTANT_TAG_KEYS = {
    "channel": "the report-channel discriminator; asserted by value in test_constant_tags",
    "result": "the planner-result discriminator; asserted by value in test_constant_tags",
}

#: (label, base, {canonical key: an instance whose serialization of THAT key differs})
CASES = [
    (
        "StaticWorld",
        StaticWorld(width=4, height=6, walls=((0, 0),), delivery_zone=((1, 1),)),
        {
            # width/height must be independent: every StaticWorld in the suite used to be square,
            # so transposing them was invisible.
            "width": StaticWorld(width=5, height=6, walls=((0, 0),), delivery_zone=((1, 1),)),
            "height": StaticWorld(width=4, height=7, walls=((0, 0),), delivery_zone=((1, 1),)),
            "walls": StaticWorld(width=4, height=6, walls=((0, 1),), delivery_zone=((1, 1),)),
            "delivery_zone": StaticWorld(
                width=4, height=6, walls=((0, 0),), delivery_zone=((1, 2),)
            ),
        },
    ),
    (
        "EpisodeSnapshot",
        EpisodeSnapshot(step_count=3, terminated=False, truncated=False),
        {
            "step_count": EpisodeSnapshot(step_count=4, terminated=False, truncated=False),
            "terminated": EpisodeSnapshot(step_count=3, terminated=True, truncated=False),
            "truncated": EpisodeSnapshot(step_count=3, terminated=False, truncated=True),
        },
    ),
    (
        "BoxSnapshot",
        BoxSnapshot(BOX_LIGHT, (8, 4), required_agents=1, is_target=True, delivered=False),
        {
            "box_id": BoxSnapshot(BOX_HEAVY, (8, 4), 1, True, False),
            "position": BoxSnapshot(BOX_LIGHT, (7, 4), 1, True, False),
            "required_agents": BoxSnapshot(BOX_LIGHT, (8, 4), 2, True, False),
            "is_target": BoxSnapshot(BOX_LIGHT, (8, 4), 1, False, False),
            "delivered": BoxSnapshot(BOX_LIGHT, (8, 4), 1, True, True),
        },
    ),
    (
        "AgentSnapshot",
        AgentSnapshot(AGENT_0, (10, 10), 2),
        {
            "agent_id": AgentSnapshot(AGENT_1, (10, 10), 2),
            "position": AgentSnapshot(AGENT_0, (9, 10), 2),
            "direction": AgentSnapshot(AGENT_0, (10, 10), 3),
        },
    ),
    (
        "Task",
        Task(task_id="t", description="d", goal_delivered=(BOX_LIGHT,), zone=DELIVERY_ZONE),
        {
            "task_id": Task(
                task_id="u", description="d", goal_delivered=(BOX_LIGHT,), zone=DELIVERY_ZONE
            ),
            "goal_delivered": Task(
                task_id="t",
                description="d",
                goal_delivered=(BOX_LIGHT, BOX_HEAVY),
                zone=DELIVERY_ZONE,
            ),
            "zone": Task(
                task_id="t", description="d", goal_delivered=(BOX_LIGHT,), zone=ZoneId("other")
            ),
            "description": Task(
                task_id="t", description="other", goal_delivered=(BOX_LIGHT,), zone=DELIVERY_ZONE
            ),
        },
    ),
    (
        "GroundedSkillCall",
        CALL,
        {
            "skill": GroundedSkillCall(
                SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE
            ),
            "agents": GroundedSkillCall(SkillName.PUSH, (AGENT_1,), BOX_LIGHT, DELIVERY_ZONE),
            "box": GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE),
            "zone": GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, ZoneId("other")),
        },
    ),
    (
        "StepAccounting",
        StepAccounting(1, 4),
        {
            "executive_steps": StepAccounting(0, 4),
            "primitive_steps": StepAccounting(1, 5),
        },
    ),
    (
        "ExecutionResult",
        _execution(),
        {
            # `blocked` is producible by BOTH skills, so the call varies ALONE.
            "call": _execution(
                call=GroundedSkillCall(
                    SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE
                ),
            ),
            # TIMEOUT is legal with PARTIAL_EXECUTION and a changed world, so the outcome varies
            # ALONE. The previous variant also moved post_state and failure_class, which meant a
            # frozen `"outcome"` constant still produced a differing canonical form.
            "outcome": _execution(outcome=ExecutionOutcome.TIMEOUT),
            # pre and post BOTH non-initial, so only `pre_state` differs from the reference.
            "pre_state": _execution(pre_state=_moved(cell=(4, 4)), post_state=_moved()),
            "post_state": _execution(post_state=_moved(cell=(4, 4))),
            "accounting": _execution(accounting=StepAccounting(1, 9)),
            "raw_label": _execution(raw_label=RawLabel.TOO_HEAVY),
            "failure_class": _execution(
                post_state=PRE, outcome=ExecutionOutcome.FAILURE,
                failure_class=FailureStateClass.UNCHANGED,
            ),
        },
    ),
    (
        "ExecutionDiscrepancy",
        ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=CALL,
            predicted_world_key=_moved().world_key(),
            observed_world_key=PRE.world_key(),
            predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
            observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
            message="m",
        ),
        {
            "kind": ExecutionDiscrepancy(
                kind=DiscrepancyKind.UNEXPECTED_OUTCOME, call=CALL, message="m"
            ),
            "predicted_world_key": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=WorldKey("f" * 64), observed_world_key=PRE.world_key(),
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m",
            ),
            "observed_world_key": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=_moved().world_key(), observed_world_key=WorldKey("e" * 64),
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m",
            ),
            "observed_symbolic_key": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=_moved().world_key(), observed_world_key=PRE.world_key(),
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=SymbolicKey("d" * 64),
                message="m",
            ),
            "message": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=_moved().world_key(), observed_world_key=PRE.world_key(),
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="other",
            ),
            "call": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
                call=GroundedSkillCall(SkillName.WAIT, (AGENT_1,)),
                predicted_world_key=_moved().world_key(), observed_world_key=PRE.world_key(),
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m",
            ),
            "predicted_symbolic_key": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=_moved().world_key(), observed_world_key=PRE.world_key(),
                predicted_symbolic_key=SymbolicKey("c" * 64),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m",
            ),
            "model_version": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=_moved().world_key(), observed_world_key=PRE.world_key(),
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m", model_version=MODEL_VERSION,
            ),
            # The per-basis verdicts must reach the TRACE, not merely exist as properties: the
            # round-3 tests asserted `comparison_bases`/`mismatched_bases` on the object while
            # `"comparison_bases": []` in canonical() survived untouched.
            "comparison_bases": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m",
            ),
            "mismatched_bases": ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=CALL,
                predicted_world_key=_moved().world_key(),
                observed_world_key=_moved().world_key(),          # world basis AGREES
                predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
                observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),
                message="m",
            ),
        },
    ),
    (
        "InfrastructureFault",
        InfrastructureFault(
            kind=FaultKind.BACKEND_API_EXCEPTION, message="m", detail="d", source="s"
        ),
        {
            "kind": InfrastructureFault(
                kind=FaultKind.SERIALIZATION_FAILURE, message="m", detail="d", source="s"
            ),
            "message": InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION, message="other", detail="d", source="s"
            ),
            "detail": InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION, message="m", detail="x", source="s"
            ),
            "source": InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION, message="m", detail="d", source="x"
            ),
        },
    ),
    (
        "TrackDivergence",
        TrackDivergence(kind=DivergenceKind.TRANSLATION_RESIDUAL, residual=("quickly",)),
        {
            "kind": TrackDivergence(
                kind=DivergenceKind.CONTRADICTION, residual=("quickly",)
            ),
            "residual": TrackDivergence(
                kind=DivergenceKind.TRANSLATION_RESIDUAL, residual=("safely",)
            ),
            "message": TrackDivergence(
                kind=DivergenceKind.TRANSLATION_RESIDUAL, residual=("quickly",), message="m"
            ),
            "nl_view": TrackDivergence(
                kind=DivergenceKind.TRANSLATION_RESIDUAL, residual=("quickly",), nl_view="n"
            ),
            "symbolic_view": TrackDivergence(
                kind=DivergenceKind.TRANSLATION_RESIDUAL, residual=("quickly",),
                symbolic_view="s",
            ),
        },
    ),
    (
        "PlanFound",
        PlanFound(plan=(CALL,), model_version=MODEL_VERSION),
        {
            "plan": PlanFound(
                plan=(
                    CALL,
                    GroundedSkillCall(
                        SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE
                    ),
                ),
                model_version=MODEL_VERSION,
            ),
            "cost": PlanFound(
                plan=(CALL, GroundedSkillCall(SkillName.WAIT, (AGENT_0,))),
                model_version=MODEL_VERSION,
            ),
            "model_version": PlanFound(
                plan=(CALL,), model_version=ModelVersion(revision=9, label="boxpush-v1")
            ),
        },
    ),
    (
        "NoPlan",
        NoPlan(reason="goal unreachable"),
        {"reason": NoPlan(reason="no applicable action")},
    ),
    (
        "PlannerFailure",
        PlannerFailure(error="boom", timed_out=False),
        {
            "error": PlannerFailure(error="other", timed_out=False),
            "timed_out": PlannerFailure(error="boom", timed_out=True),
        },
    ),
    (
        "CoverageReport",
        CoverageReport(covered=("a",), residual=("b",)),
        {
            "covered": CoverageReport(covered=("c",), residual=("b",)),
            "residual": CoverageReport(covered=("a",), residual=("d",)),
            "is_complete": CoverageReport(covered=("a",), residual=()),   # derived from residual
            "note": CoverageReport(covered=("a",), residual=("b",), note="n"),
        },
    ),
    (
        "ConfidenceReport",
        ConfidenceReport(source="symbolic", confidence=0.9),
        {
            "source": ConfidenceReport(source="nl", confidence=0.9),
            "confidence": ConfidenceReport(source="symbolic", confidence=0.4),
            "rationale": ConfidenceReport(source="symbolic", confidence=0.9, rationale="r"),
        },
    ),
    (
        "ExecutiveObservation",
        ExecutiveObservation(
            state=PRE, outcome=ExecutionOutcome.PARTIAL, raw_label=RawLabel.TOO_HEAVY,
            primitive_steps=4, notes=("n",),
        ),
        {
            "state": ExecutiveObservation(
                state=_moved(), outcome=ExecutionOutcome.PARTIAL,
                raw_label=RawLabel.TOO_HEAVY, primitive_steps=4, notes=("n",),
            ),
            "outcome": ExecutiveObservation(
                state=PRE, outcome=ExecutionOutcome.FAILURE, raw_label=RawLabel.TOO_HEAVY,
                primitive_steps=4, notes=("n",),
            ),
            "raw_label": ExecutiveObservation(
                state=PRE, outcome=ExecutionOutcome.PARTIAL, raw_label=RawLabel.BLOCKED,
                primitive_steps=4, notes=("n",),
            ),
            "primitive_steps": ExecutiveObservation(
                state=PRE, outcome=ExecutionOutcome.PARTIAL, raw_label=RawLabel.TOO_HEAVY,
                primitive_steps=9, notes=("n",),
            ),
            "notes": ExecutiveObservation(
                state=PRE, outcome=ExecutionOutcome.PARTIAL, raw_label=RawLabel.TOO_HEAVY,
                primitive_steps=4, notes=("other",),
            ),
        },
    ),
    (
        "Predicate",
        Predicate("in_pose", ("agent", "box")),
        {
            "name": Predicate("delivered", ("agent", "box")),
            "args": Predicate("in_pose", ("agent", "zone")),
        },
    ),
    (
        "Effect",
        Effect(Predicate("in_pose", ("agent", "box")), positive=True),
        {
            "predicate": Effect(Predicate("delivered", ("box",)), positive=True),
            "positive": Effect(Predicate("in_pose", ("agent", "box")), positive=False),
        },
    ),
    (
        # Was exempted with no reason and verified nowhere — a frozen
        # `"halt_on_infrastructure_fault": True` or transposed budgets would have survived.
        "OrchestrationConfig",
        OrchestrationConfig(),
        {
            "policy": OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK),
            "executive_step_budget": OrchestrationConfig(executive_step_budget=11),
            "primitive_step_budget": OrchestrationConfig(primitive_step_budget=111),
            "repeated_failure_threshold": OrchestrationConfig(repeated_failure_threshold=9),
            "halt_on_infrastructure_fault": OrchestrationConfig(
                halt_on_infrastructure_fault=False
            ),
            "max_rejections_per_cycle": OrchestrationConfig(max_rejections_per_cycle=2),
        },
    ),
    (
        "TraceEntry",
        _trace(),
        {
            "executive_step": _trace(executive_step=4),
            "task": _trace(task=Task(
                task_id="other", description="d", goal_delivered=(BOX_LIGHT,), zone=DELIVERY_ZONE
            )),
            "pre_state": _trace(pre_state=_moved()),
            "post_state": _trace(post_state=PRE),
            "model_version": _trace(model_version=ModelVersion(revision=7, label="boxpush-v1")),
            "provenance": _trace(provenance=Provenance(
                source="elsewhere", model_version=MODEL_VERSION
            )),
            "symbolic_result": _trace(symbolic_result=NoPlan(reason="none")),
            "symbolic_proposal": _trace(symbolic_proposal=GroundedSkillCall(
                SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE
            )),
            "nl_proposal": _trace(nl_proposal=GroundedSkillCall(SkillName.WAIT, (AGENT_1,))),
            "coverage": _trace(coverage=CoverageReport(covered=("x",), residual=())),
            "confidence": _trace(
                confidence=(ConfidenceReport(source="nl", confidence=0.1),)
            ),
            "decision": _trace(decision=ExecutiveDecision.REPLAN),
            "selected_call": _trace(selected_call=GroundedSkillCall(SkillName.WAIT, (AGENT_0,))),
            "validation": _trace(validation=None),
            "predicted_world_key": _trace(predicted_world_key=PRE.world_key()),
            "predicted_symbolic_key": _trace(
                predicted_symbolic_key=PROJECTION.monitored_key(project(PRE))
            ),   # PRE is pending, _delivered() is delivered — a real symbolic difference
            "execution": _trace(execution=_execution(accounting=StepAccounting(1, 11))),
            "discrepancies": _trace(discrepancies=()),
            "divergences": _trace(divergences=()),
            "faults": _trace(faults=()),
        },
    ),
]


class TestCanonicalFormsAreFaithful(unittest.TestCase):
    def test_every_canonical_key_actually_varies(self):
        """PER KEY. Comparing whole dicts let a variant that moved two fields pass while proving
        nothing about either — `"pre_state": ""` and `"cost": 0` both survived that way."""
        for label, base, variants in CASES:
            reference = base.canonical()
            for key, variant in variants.items():
                with self.subTest(type=label, key=key):
                    self.assertIn(key, reference, f"{label}.canonical() emits no key {key!r}")
                    self.assertNotEqual(
                        reference[key], variant.canonical()[key],
                        f"{label}.canonical()[{key!r}] is insensitive to its own source: a "
                        f"constant, a mirror of another key, or an emptied container would "
                        f"serialize identically",
                    )

    def test_every_canonical_key_has_a_variant(self):
        """FIELD-level coverage, derived from `canonical()` itself. Type-level coverage was not
        enough: a newly ADDED field shipped unprotected, which is precisely what this module was
        written to prevent."""
        for label, base, variants in CASES:
            uncovered = set(base.canonical()) - set(variants) - set(CONSTANT_TAG_KEYS)
            with self.subTest(type=label):
                self.assertEqual(
                    uncovered, set(),
                    f"{label}.canonical() emits {sorted(uncovered)} with no variant — add one, or "
                    f"declare the key a constant discriminator tag",
                )

    def test_no_variant_names_a_key_the_type_does_not_emit(self):
        """A label like `"arity"` or `"transposed"` reads as a claimed canonical field. If it is
        not a key, the case documents something the type does not do."""
        for label, base, variants in CASES:
            unknown = set(variants) - set(base.canonical())
            with self.subTest(type=label):
                self.assertEqual(unknown, set())

    def test_the_trace_bearing_types_emit_every_field_they_declare(self):
        """Stronger than key-coverage, and only for the two types the testing rule enumerates: a
        field ADDED to `TraceEntry` or `ExecutionResult` but never emitted is silently missing
        from every trace, and key-coverage cannot see it because the key does not exist.

        `ExecutionResult.detail` is the one declared exemption: it is free-text provenance whose
        authoritative counterpart (`raw_label`, `outcome`, `failure_class`) is already emitted.
        """
        import dataclasses

        from shared.execution import ExecutionResult as _ER
        from shared.trace_schema import TraceEntry as _TE

        exempt = {"ExecutionResult": {"detail"}, "TraceEntry": set()}
        for cls, instance in ((_TE, _trace()), (_ER, _execution())):
            declared = {f.name for f in dataclasses.fields(cls)}
            emitted = set(instance.canonical())
            with self.subTest(type=cls.__name__):
                self.assertEqual(
                    declared - emitted - exempt[cls.__name__], set(),
                    f"{cls.__name__} declares fields its canonical form drops — a trace would "
                    f"silently lose them",
                )
                self.assertEqual(
                    exempt[cls.__name__] - declared, set(), "a stale exemption"
                )

    def test_constant_discriminator_tags_carry_their_expected_value(self):
        """`channel` and `result` are exempt from sensitivity because they cannot vary. Pin their
        VALUES instead, so the exemption is not a hole."""
        expected = {
            "ExecutionDiscrepancy": ("channel", "ExecutionDiscrepancy"),
            "TrackDivergence": ("channel", "TrackDivergence"),
            "InfrastructureFault": ("channel", "InfrastructureFault"),
            "PlanFound": ("result", "PlanFound"),
            "NoPlan": ("result", "NoPlan"),
            "PlannerFailure": ("result", "PlannerFailure"),
        }
        seen = set()
        for label, base, _ in CASES:
            blob = base.canonical()
            for key in CONSTANT_TAG_KEYS:
                if key in blob:
                    with self.subTest(type=label, key=key):
                        self.assertIn(label, expected, f"{label} emits {key} but is not pinned")
                        self.assertEqual((key, blob[key]), expected[label])
                        seen.add(label)
        self.assertEqual(seen, set(expected), "a pinned discriminator type left the case table")

    def test_transposition_vulnerable_pairs_are_pinned_by_value(self):
        """A consistent swap of two fields is a BIJECTION on canonical forms, so no difference
        test can detect it. `StaticWorld` width/height transposition survived everything because
        the frozen instance is 12x12; `StepAccounting` was rescued only by a literal elsewhere."""
        self.assertEqual(
            StaticWorld(width=4, height=6, walls=(), delivery_zone=()).canonical(),
            {"width": 4, "height": 6, "walls": [], "delivery_zone": []},
        )
        self.assertEqual(
            StepAccounting(1, 4).canonical(),
            {"executive_steps": 1, "primitive_steps": 4},
        )

    def test_the_case_table_covers_every_contract_type_with_a_canonical_form(self):
        """So a NEW contract type cannot ship with an unverified serialization."""
        import inspect
        import importlib
        import pkgutil

        import shared as package

        covered = {label for label, _, _ in CASES}
        missing = []
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"shared.{info.name}")
            for name, value in vars(module).items():
                if name.startswith("_") or not inspect.isclass(value):
                    continue
                if getattr(value, "__module__", None) != f"shared.{info.name}":
                    continue
                if not hasattr(value, "canonical"):
                    continue
                if name not in covered and name not in VERIFIED_ELSEWHERE:
                    missing.append(f"{name} ({module.__name__})")
        self.assertEqual(
            sorted(missing), [],
            "these contract types have a canonical() with no faithfulness case:\n"
            + "\n".join(sorted(missing)),
        )

    def test_the_exemption_list_is_honest(self):
        """An exemption must name a type that (a) still exists and (b) actually HAS a canonical
        form — otherwise it is exempting something from a property it does not have, and a real
        gap can hide behind it. `ModelPatch` was listed here and has no `canonical()` at all."""
        import importlib
        import pkgutil

        import shared as package

        found = {}
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"shared.{info.name}")
            found.update(vars(module))
        for name in sorted(VERIFIED_ELSEWHERE):
            with self.subTest(exempt=name):
                self.assertIn(name, found, "exemption names a type that no longer exists")
                # `canonical_world()` / `canonical_full()` count: `StateSnapshot` deliberately
                # has two canonical forms rather than one.
                forms = [a for a in dir(found[name]) if a.startswith("canonical")]
                self.assertTrue(
                    forms, f"{name} has no canonical form — exempting it is meaningless"
                )


class TestPerBasisVerdicts(unittest.TestCase):
    """`mismatched_bases` must be judged PER BASIS. Every existing case made both bases differ, so
    dropping the world-side `!=` comparison — which then reports WORLD_STATE even when the pair
    agrees — was invisible."""

    def test_a_basis_whose_pair_agrees_is_not_reported_as_mismatched(self):
        from shared.discrepancy import ComparisonBasis
        agreeing = PRE.world_key()
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=CALL,
            predicted_world_key=agreeing,
            observed_world_key=agreeing,                       # world basis AGREES
            predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered())),
            observed_symbolic_key=PROJECTION.monitored_key(project(PRE)),   # symbolic DIFFERS
        )
        self.assertEqual(
            d.comparison_bases,
            (ComparisonBasis.WORLD_STATE, ComparisonBasis.SYMBOLIC_PROJECTION),
        )
        self.assertEqual(d.mismatched_bases, (ComparisonBasis.SYMBOLIC_PROJECTION,))

    def test_the_mirror_case_world_differs_while_symbolic_agrees(self):
        from shared.discrepancy import ComparisonBasis
        agreeing = PROJECTION.monitored_key(project(PRE))
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=CALL,
            predicted_world_key=_moved().world_key(),
            observed_world_key=PRE.world_key(),                # world DIFFERS
            predicted_symbolic_key=agreeing,
            observed_symbolic_key=agreeing,                    # symbolic AGREES
        )
        self.assertEqual(d.mismatched_bases, (ComparisonBasis.WORLD_STATE,))

    def test_a_world_only_discrepancy_serializes_both_world_fields_distinctly(self):
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=CALL,
            predicted_world_key=_moved().world_key(),
            observed_world_key=PRE.world_key(),
        )
        blob = d.canonical()
        self.assertIsNotNone(blob["predicted_world_key"])
        self.assertNotEqual(blob["predicted_world_key"], blob["observed_world_key"])
        self.assertIsNone(blob["predicted_symbolic_key"])


class TestNormalizationAndDerivedFlags(unittest.TestCase):
    """Properties a difference test cannot express: normalization (many inputs -> one form) and
    derived booleans (which must actually discriminate)."""

    def test_task_goals_are_deduplicated_and_sorted(self):
        noisy = Task(
            task_id="t", description="d",
            goal_delivered=(BOX_LIGHT, BOX_HEAVY, BOX_LIGHT), zone=DELIVERY_ZONE,
        )
        tidy = Task(
            task_id="t", description="d",
            goal_delivered=(BOX_HEAVY, BOX_LIGHT), zone=DELIVERY_ZONE,
        )
        self.assertEqual(noisy.goal_delivered, tidy.goal_delivered)
        self.assertEqual(noisy.canonical(), tidy.canonical())
        self.assertEqual(len(noisy.goal_delivered), 2)

    def test_track_divergence_is_benign_discriminates(self):
        """`BENIGN_ABSTRACTION_MISMATCH` is a named contract kind; a constant `is_benign` would
        make the distinction unusable to the orchestrator."""
        benign = TrackDivergence(kind=DivergenceKind.BENIGN_ABSTRACTION_MISMATCH)
        self.assertTrue(benign.is_benign)
        for kind in set(DivergenceKind) - {DivergenceKind.BENIGN_ABSTRACTION_MISMATCH}:
            with self.subTest(kind=kind):
                self.assertFalse(TrackDivergence(kind=kind).is_benign)

    def test_coverage_is_complete_discriminates(self):
        self.assertTrue(CoverageReport(covered=("a",), residual=()).is_complete)
        self.assertFalse(CoverageReport(covered=("a",), residual=("b",)).is_complete)

    def test_duplicate_skill_names_are_refused_by_the_name_guard(self):
        """The duplicate-name and duplicate-dispatch-key guards are separate. Appending a verbatim
        copy triggers the KEY guard first, so the NAME guard could be deleted unnoticed — give the
        duplicate a distinct dispatch key."""
        from shared.skills import SkillRegistry, SkillSignature, _SIGNATURES
        first = _SIGNATURES[0]
        clash = SkillSignature(
            name=first.name, parameters=first.parameters, cost=first.cost,
            in_symbolic_action_set=first.in_symbolic_action_set,
            backend_mapping=first.backend_mapping,
            backend_dispatch_key="a_distinct_token",
        )
        with self.assertRaises(ValueError):
            SkillRegistry(_SIGNATURES + (clash,))

    def test_skill_dependencies_reach_the_canonical_form(self):
        """`dependencies` is `()` on all three frozen skills — the same information-free shape as
        `cost` — so an emptied list is invisible in the digest. Vary it explicitly."""
        from shared.skill_ir import SkillIR
        base = DOMAIN_IR.skill(SkillName.PUSH)
        with_deps = SkillIR(
            signature=base.signature, parameters=base.parameters,
            parameter_types=base.parameter_types, preconditions=base.preconditions,
            effects=base.effects, provenance=base.provenance,
            outcome_label=base.outcome_label,
            predicted_world_effects=base.predicted_world_effects,
            dependencies=("a_declared_dependency",),
        )
        self.assertEqual(with_deps.canonical()["dependencies"], ["a_declared_dependency"])
        self.assertEqual(base.canonical()["dependencies"], [])

    def test_skill_cost_reaches_the_canonical_form(self):
        """Every V1 skill costs 1, so cost carries no information in the frozen digest and a
        `"cost": 1` constant is invisible. Vary it explicitly."""
        from shared.skill_ir import SkillIR
        base = DOMAIN_IR.skill(SkillName.PUSH)
        from shared.skills import SkillSignature
        sig = base.signature
        pricey = SkillIR(
            signature=SkillSignature(
                name=sig.name, parameters=sig.parameters, cost=7,
                in_symbolic_action_set=sig.in_symbolic_action_set,
                backend_mapping=sig.backend_mapping,
                backend_dispatch_key=sig.backend_dispatch_key,
            ),
            parameters=base.parameters, parameter_types=base.parameter_types,
            preconditions=base.preconditions, effects=base.effects,
            provenance=base.provenance, outcome_label=base.outcome_label,
            predicted_world_effects=base.predicted_world_effects,
        )
        self.assertEqual(pricey.canonical()["cost"], 7)
        self.assertNotEqual(pricey.canonical(), base.canonical())

    def test_orchestration_defaults_express_the_short_circuit_rule(self):
        """:163 says a new fault aborts the cycle. `halt_on_infrastructure_fault` is the configured
        expression of that, and a flipped default would silently disable it (P4 consumes this)."""
        from shared.orchestration_config import OrchestrationConfig
        config = OrchestrationConfig()
        self.assertTrue(config.halt_on_infrastructure_fault)
        self.assertEqual(config.executive_step_budget, 50)
        self.assertEqual(config.primitive_step_budget, 600)
        self.assertEqual(config.repeated_failure_threshold, 3)


class TestExclusionsDoNotSilentlyReverse(unittest.TestCase):
    """The opposite property: a field deliberately EXCLUDED from a canonical form must stay out."""

    def test_episode_bookkeeping_stays_out_of_the_world_form(self):
        busy = PRE.replace_episode(EpisodeSnapshot(step_count=99, terminated=True, truncated=True))
        self.assertNotEqual(busy.episode, PRE.episode)          # the fixture really differs
        self.assertEqual(busy.canonical_world(), PRE.canonical_world())
        self.assertEqual(busy.world_key(), PRE.world_key())

    def test_episode_bookkeeping_is_carried_by_the_replay_form(self):
        busy = PRE.replace_episode(EpisodeSnapshot(step_count=99, terminated=True, truncated=True))
        self.assertNotEqual(busy.canonical_full(), PRE.canonical_full())
        self.assertNotEqual(busy.replay_key(), PRE.replay_key())

    def test_each_episode_field_is_independently_carried_by_the_replay_form(self):
        for episode in (
            EpisodeSnapshot(step_count=99, terminated=False, truncated=False),
            EpisodeSnapshot(step_count=0, terminated=True, truncated=False),
            EpisodeSnapshot(step_count=0, terminated=False, truncated=True),
        ):
            with self.subTest(episode=episode):
                self.assertNotEqual(PRE.replace_episode(episode).replay_key(), PRE.replay_key())


class TestNormalizationIsOrderIndependent(unittest.TestCase):
    """`StateSnapshot.__post_init__` sorts agents AND boxes. Only agents was tested, so dropping
    the box sort left two snapshots of the same world with different `world_key()`s — unequal,
    differently hashed, and splitting the repeated-failure bucket (:118)."""

    def _snapshot(self, boxes, agents):
        return StateSnapshot(
            agents=agents, boxes=boxes, static=PRE.static, episode=EpisodeSnapshot()
        )

    def test_box_order_does_not_affect_the_canonical_form(self):
        forward = self._snapshot(PRE.boxes, PRE.agents)
        reversed_ = self._snapshot(tuple(reversed(PRE.boxes)), PRE.agents)
        self.assertEqual(len(PRE.boxes), 2, "a one-box fixture cannot detect ordering")
        self.assertEqual(forward.canonical_world(), reversed_.canonical_world())
        self.assertEqual(forward.world_key(), reversed_.world_key())
        self.assertEqual(forward, reversed_)
        self.assertEqual(hash(forward), hash(reversed_))

    def test_agent_order_does_not_affect_the_canonical_form(self):
        forward = self._snapshot(PRE.boxes, PRE.agents)
        reversed_ = self._snapshot(PRE.boxes, tuple(reversed(PRE.agents)))
        self.assertEqual(len(PRE.agents), 2, "a one-agent fixture cannot detect ordering")
        self.assertEqual(forward.world_key(), reversed_.world_key())

    def test_both_reversed_is_still_the_same_world(self):
        self.assertEqual(
            self._snapshot(tuple(reversed(PRE.boxes)), tuple(reversed(PRE.agents))).world_key(),
            PRE.world_key(),
        )


if __name__ == "__main__":
    unittest.main()
