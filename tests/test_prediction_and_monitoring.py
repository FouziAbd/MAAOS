"""Decision 13 (prediction/monitoring boundary) and Decision 14 (frozen adapter dispatch).

The defect this module was written for: the monitor's comparison criterion moved to the symbolic
projection while `ExecutionDiscrepancy` still demanded a `predicted_world_key`/`observed_world_key`
pair. A compliant symbolic predictor produces neither, so `STATE_EFFECT_MISMATCH` — the one
discrepancy kind the projection exists to raise — could not be legally constructed at all. The
only two escapes were both wrong: write a symbolic key into a field named `*_world_key` (erasing
the boundary), or build the geometric predictor Decision 6 forbids.

The fix is not to weaken the monitor to symbolic-only comparison. BOTH bases are live, each with
its own correctly named pair, and the tests below pin both directions.
"""
import re
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    DOMAIN_IR,
    PROJECTION,
    P_DELIVERED,
    P_IN_POSE,
    initial_state,
    project,
)
from shared.comparison_keys import SymbolicKey, WorldKey
from shared.discrepancy import ComparisonBasis, DiscrepancyKind, ExecutionDiscrepancy
from shared.skill_ir import SkillIR
from shared.skills import (
    REGISTRY,
    GroundedSkillCall,
    OutsideSymbolicModel,
    SkillName,
    SkillSignature,
    SymbolicallyInapplicable,
)
from shared.state_snapshot import AgentSnapshot, BoxSnapshot
from shared.symbolic_state import GroundedLiteral
from shared.trace_schema import TraceEntry

PUSH_CALL = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
GOTO_CALL = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)

FORBIDDEN_ORACLE_TOKENS = (
    "bfs", "reachab", "occupan", "collision", "feasib", "navigat", "search",
    "path", "is_free", "can_reach", "simulate", "rollout",
)


def _delivered(state, box_id):
    b = state.box(box_id)
    return state.with_box(BoxSnapshot(b.box_id, (1, 4), b.required_agents, b.is_target, True))


def _moved_agent(state, agent_id, position):
    return state.__class__(
        agents=tuple(
            AgentSnapshot(a.agent_id, position, a.direction) if a.agent_id == agent_id else a
            for a in state.agents
        ),
        boxes=state.boxes,
        static=state.static,
        episode=state.episode,
    )


# ── F1: the mismatch a compliant symbolic monitor actually produces ────────────────

class TestSymbolicOnlyMismatchIsConstructible(unittest.TestCase):
    """The regression that motivated Decision 13. Before the fix every test here raised."""

    def test_a_monitor_with_only_symbolic_keys_can_report_a_mismatch(self):
        pre = initial_state()
        predicted = _delivered(pre, BOX_LIGHT)      # Push success
        observed = pre                              # push failed; nothing moved

        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=PUSH_CALL,
            predicted_symbolic_key=PROJECTION.monitored_key(project(predicted)),
            observed_symbolic_key=PROJECTION.monitored_key(project(observed)),
        )
        self.assertEqual(d.comparison_bases, (ComparisonBasis.SYMBOLIC_PROJECTION,))
        self.assertEqual(d.mismatched_bases, (ComparisonBasis.SYMBOLIC_PROJECTION,))
        self.assertIsNone(d.predicted_world_key)    # never smuggled into the world field

    def test_a_monitor_with_only_world_keys_can_report_a_mismatch(self):
        pre = initial_state()
        predicted = _moved_agent(pre, AGENT_0, (9, 4))
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=GOTO_CALL,
            predicted_world_key=predicted.world_key(),
            observed_world_key=pre.world_key(),
        )
        self.assertEqual(d.comparison_bases, (ComparisonBasis.WORLD_STATE,))
        self.assertIsNone(d.predicted_symbolic_key)

    def test_both_bases_can_be_recorded_together(self):
        pre = initial_state()
        predicted = _delivered(pre, BOX_LIGHT)
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=PUSH_CALL,
            predicted_world_key=predicted.world_key(),
            observed_world_key=pre.world_key(),
            predicted_symbolic_key=PROJECTION.monitored_key(project(predicted)),
            observed_symbolic_key=PROJECTION.monitored_key(project(pre)),
        )
        self.assertEqual(
            d.comparison_bases,
            (ComparisonBasis.WORLD_STATE, ComparisonBasis.SYMBOLIC_PROJECTION),
        )
        self.assertEqual(len(d.mismatched_bases), 2)

    def test_the_two_bases_are_distinct_fields_in_the_serialized_form(self):
        """A symbolic key written into `predicted_world_key` would erase the distinction the whole
        decision draws, and a shared field name is how that happens by accident."""
        pre = initial_state()
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=PUSH_CALL,
            predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered(pre, BOX_LIGHT))),
            observed_symbolic_key=PROJECTION.monitored_key(project(pre)),
        )
        blob = d.canonical()
        for key in (
            "predicted_world_key", "observed_world_key",
            "predicted_symbolic_key", "observed_symbolic_key",
            "comparison_bases", "mismatched_bases",
        ):
            with self.subTest(field=key):
                self.assertIn(key, blob)
        # Values, not just presence: serializing the world key into the symbolic slot would keep
        # every field name intact while erasing the distinction.
        self.assertIsNone(blob["predicted_world_key"])
        self.assertIsNone(blob["observed_world_key"])
        self.assertEqual(blob["predicted_symbolic_key"], d.predicted_symbolic_key)
        self.assertEqual(blob["observed_symbolic_key"], d.observed_symbolic_key)
        self.assertIsNotNone(blob["predicted_symbolic_key"])
        self.assertNotEqual(blob["predicted_symbolic_key"], blob["observed_symbolic_key"])


class TestMismatchEvidenceInvariants(unittest.TestCase):
    def test_a_mismatch_with_no_comparison_pair_is_refused(self):
        with self.assertRaises(ValueError):
            ExecutionDiscrepancy(DiscrepancyKind.STATE_EFFECT_MISMATCH, PUSH_CALL)

    def test_a_mismatch_whose_every_recorded_basis_agrees_is_refused(self):
        """Reporting a mismatch while every pair matches is a false report, not a weak one."""
        key = PROJECTION.monitored_key(project(initial_state()))
        with self.assertRaises(ValueError):
            ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
                call=PUSH_CALL,
                predicted_symbolic_key=key,
                observed_symbolic_key=key,
            )

    def test_a_half_world_pair_is_refused_on_any_kind(self):
        for kind in DiscrepancyKind:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                ExecutionDiscrepancy(kind, PUSH_CALL, predicted_world_key=WorldKey("abc"))

    def test_a_half_symbolic_pair_is_refused_on_any_kind(self):
        for kind in DiscrepancyKind:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                ExecutionDiscrepancy(kind, PUSH_CALL, observed_symbolic_key=SymbolicKey("abc"))

    def test_a_symbolic_key_cannot_be_written_into_a_world_field(self):
        """The failure mode the whole decision exists to prevent, now type-enforced rather than
        merely documented: both keys are sha256 hex and were interchangeable as plain `str`."""
        pre = initial_state()
        symbolic = PROJECTION.monitored_key(project(pre))
        with self.assertRaises(TypeError):
            ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
                call=PUSH_CALL,
                predicted_world_key=symbolic,
                observed_world_key=PROJECTION.monitored_key(project(_delivered(pre, BOX_LIGHT))),
            )

    def test_a_world_key_cannot_be_written_into_a_symbolic_field(self):
        pre = initial_state()
        with self.assertRaises(TypeError):
            ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
                call=PUSH_CALL,
                predicted_symbolic_key=_delivered(pre, BOX_LIGHT).world_key(),
                observed_symbolic_key=pre.world_key(),
            )

    def test_a_bare_string_is_refused_in_either_field(self):
        """Guards against a caller that hand-rolls a digest instead of using the producers."""
        for field in ("predicted_world_key", "predicted_symbolic_key"):
            with self.subTest(field=field), self.assertRaises(TypeError):
                ExecutionDiscrepancy(
                    DiscrepancyKind.UNEXPECTED_OUTCOME, PUSH_CALL,
                    **{field: "0" * 64, field.replace("predicted", "observed"): "1" * 64},
                )

    def test_the_key_producers_return_the_typed_keys(self):
        self.assertIsInstance(initial_state().world_key(), WorldKey)
        self.assertIsInstance(PROJECTION.monitored_key(project(initial_state())), SymbolicKey)
        self.assertNotIsInstance(initial_state().world_key(), SymbolicKey)
        self.assertNotIsInstance(PROJECTION.monitored_key(project(initial_state())), WorldKey)

    def test_trace_entry_enforces_the_symbolic_key_type_too(self):
        from domain.box_push_v1 import MODEL_VERSION, TASK_DELIVER_LIGHT, _PROVENANCE
        pre = initial_state()
        with self.assertRaises(TypeError):
            TraceEntry(
                executive_step=0, task=TASK_DELIVER_LIGHT, pre_state=pre,
                model_version=MODEL_VERSION, provenance=_PROVENANCE,
                predicted_symbolic_key=pre.world_key(),     # a WorldKey in the symbolic field
            )

    def test_trace_entry_enforces_the_key_types_too(self):
        from domain.box_push_v1 import MODEL_VERSION, TASK_DELIVER_LIGHT, _PROVENANCE
        pre = initial_state()
        with self.assertRaises(TypeError):
            TraceEntry(
                executive_step=0, task=TASK_DELIVER_LIGHT, pre_state=pre,
                model_version=MODEL_VERSION, provenance=_PROVENANCE,
                predicted_world_key=PROJECTION.monitored_key(project(pre)),
            )

    def test_execution_failure_needs_no_comparison_pair(self):
        """Decision 13.7 — an ExecutionFailure stands on the authoritative typed outcome alone.
        This is the ONLY discrepancy available for GotoPushPose until P2's predictor lands."""
        d = ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL,
            call=GOTO_CALL,
            message="blocked",
        )
        self.assertEqual(d.comparison_bases, ())


class TestGotoPushPoseIsNotMonitoringBlind(unittest.TestCase):
    """Decision 13.3. `in_pose` is excluded from the SYMBOLIC basis — that must not be read as
    'GotoPushPose is unmonitored'."""

    def test_goto_push_pose_success_and_failure_project_identically(self):
        """Stated so it cannot be discovered by surprise in P2."""
        pre = initial_state()
        success = _moved_agent(pre, AGENT_0, (9, 4))
        self.assertEqual(
            PROJECTION.monitored_key(project(success)), PROJECTION.monitored_key(project(pre))
        )

    def test_but_the_world_basis_does_separate_them(self):
        pre = initial_state()
        success = _moved_agent(pre, AGENT_0, (9, 4))
        self.assertNotEqual(success.world_key(), pre.world_key())

    def test_every_symbolic_skill_declares_deterministic_world_effects(self):
        for skill in DOMAIN_IR.skills:
            with self.subTest(skill=skill.name):
                self.assertTrue(
                    skill.predicted_world_effects,
                    f"{skill.name} declares no world effect, so P2 has nothing to predict and the "
                    f"world basis silently disappears for it",
                )

    def test_goto_push_pose_declares_an_agent_position_effect(self):
        effects = DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE).predicted_world_effects
        self.assertTrue(any("agent.position" in e for e in effects))
        self.assertTrue(any("agent.direction" in e for e in effects))

    def test_declared_world_effects_invoke_no_feasibility_oracle(self):
        """ADVISORY, not a proof. Decision 13.2 permits effect arithmetic and forbids smuggling a
        search in — but these effects are free-form pseudo-code that nothing parses or executes, so
        a substring scan cannot stop a P2 predictor from running BFS behind an innocent-looking
        string. The binding guarantee is Decision 13 clause 9 (the predictor is monitor-side
        only, with bounded inputs) plus the import guard; this check only keeps the DECLARATIONS
        honest, which matters because `DomainIR.canonical()` freezes them into the domain digest.
        """
        for skill in DOMAIN_IR.skills:
            for effect in skill.predicted_world_effects:
                for token in FORBIDDEN_ORACLE_TOKENS:
                    with self.subTest(skill=skill.name, token=token):
                        self.assertNotIn(token, effect.lower())

    def test_world_effects_reference_only_that_skill_s_lifted_parameters(self):
        """Roots are DERIVED from the text, not intersected with a hardcoded vocabulary.

        The earlier version computed `used` as the intersection of a fixed name list with the
        effect string, so any name outside that list — `pusher.position`, say — was simply
        invisible and the assertion could never fire. Adversarial review demonstrated exactly that.
        """
        # A parameter may appear two ways: as an attribute OWNER (`agent1.position_post`) or as a
        # FUNCTION ARGUMENT (`push_dir(box, zone)`). Both are checked; neither is intersected with
        # a hardcoded name list, so a name outside the vocabulary cannot hide.
        NON_PARAMETER_ROOTS = {"direction_vector", "first_zone_cell_along", "push_dir"}
        for skill in DOMAIN_IR.skills:
            allowed = set(skill.parameters) | NON_PARAMETER_ROOTS
            for effect in skill.predicted_world_effects:
                owners = set(re.findall(r"\b([A-Za-z_]\w*)\s*\.", effect))
                mentioned = {p for p in skill.parameters if re.search(rf"\b{p}\b", effect)}
                with self.subTest(skill=skill.name, effect=effect):
                    self.assertEqual(
                        owners - allowed, set(),
                        f"{skill.name} effect owns an attribute on a name that is not one of its "
                        f"lifted parameters {sorted(skill.parameters)}",
                    )
                    self.assertTrue(
                        owners or mentioned, "effect references no lifted parameter at all"
                    )

    def test_every_lifted_parameter_that_can_move_is_named_by_some_effect(self):
        """Catches a silently DELETED effect — e.g. dropping agent2 from CooperativePush."""
        for skill in DOMAIN_IR.skills:
            blob = " ".join(skill.predicted_world_effects)
            for parameter, kind in zip(skill.parameters, skill.parameter_types):
                if kind == "zone":          # the zone is an identity, it has no world state
                    continue
                with self.subTest(skill=skill.name, parameter=parameter):
                    self.assertRegex(blob, rf"\b{parameter}\s*\.")

    def test_a_skill_that_turns_its_agents_declares_their_terminal_direction(self):
        """CooperativePush computes the push direction from the box/zone and TURNS both agents onto
        it, so both terminal directions are real world effects. Implicit frame conditions would
        otherwise predict unchanged facing and mismatch on every successful cooperative push that
        required a turn. Push, by contrast, only ever moves forward — its facing is frame."""
        coop = DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH).predicted_world_effects
        for parameter in ("agent1", "agent2"):
            with self.subTest(agent=parameter):
                self.assertIn(f"{parameter}.direction_post == push_dir(box, zone)", coop)
        self.assertIn("D == direction_vector(push_dir(box, zone))", coop)
        # and it must NOT be sourced from an agent's pre-direction
        self.assertNotIn("D == direction_vector(agent1.direction_pre)", coop)

    #: The frozen declarations, verbatim. Every earlier check was a substring or "names a
    #: parameter" test, so a sign flip, a swapped operand, a dropped clause or a collapsed slot set
    #: was caught only by the domain digest — and the digest is an undifferentiated change detector
    #: that gets re-pinned by hand the moment any legitimate edit lands. These tuples are the
    #: semantic pin.
    FROZEN_EFFECTS = {
        SkillName.GOTO_PUSH_POSE: (
            "agent.position_post == box.position_pre - direction_vector(push_dir(box, zone))",
            "agent.direction_post == push_dir(box, zone)",
        ),
        SkillName.PUSH: (
            "D == direction_vector(agent.direction_pre)",
            "box.position_post == first_zone_cell_along(box.position_pre, D)",
            "box.delivered_post is True",
            "agent.position_post == box.position_post - D",
        ),
        SkillName.COOPERATIVE_PUSH: (
            "D == direction_vector(push_dir(box, zone))",
            "box.position_post == first_zone_cell_along(box.position_pre, D)",
            "box.delivered_post is True",
            "agent1.direction_post == push_dir(box, zone)",
            "agent2.direction_post == push_dir(box, zone)",
            "{agent1.position_post, agent2.position_post} == "
            "{box.position_post - D, box.position_post - 2*D}",
        ),
    }

    def test_the_declared_world_effects_are_exactly_these(self):
        for skill, expected in self.FROZEN_EFFECTS.items():
            with self.subTest(skill=skill):
                self.assertEqual(DOMAIN_IR.skill(skill).predicted_world_effects, expected)

    def test_the_cooperative_slot_set_names_two_distinct_cells(self):
        """The collapsed-slot regression specifically: `{B-D, B-D}` is a state the backend can
        never produce, and it reads almost identically to the correct form."""
        slot = next(
            e for e in DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH).predicted_world_effects
            if e.startswith("{agent1.position_post")
        )
        offsets = re.findall(r"box\.position_post\s*-\s*(2\*)?D", slot)
        self.assertEqual(len(offsets), 2, "the slot set must name two cells")
        self.assertEqual(set(offsets), {"", "2*"}, "the two slots collapsed onto one cell")
        self.assertIn("agent1.position_post", slot)
        self.assertIn("agent2.position_post", slot)

    def test_the_pose_cell_offset_sign_is_pinned(self):
        """`box - D` is behind the box; `box + D` is in front of it, i.e. where the box is going."""
        goto = DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE).predicted_world_effects
        self.assertIn(
            "agent.position_post == box.position_pre - direction_vector(push_dir(box, zone))", goto
        )
        self.assertNotIn(
            "agent.position_post == box.position_pre + direction_vector(push_dir(box, zone))", goto
        )

    def test_every_skill_declares_its_terminal_box_state(self):
        """Dropping `box.delivered_post` or the terminal box position left the other clauses in
        place, so the "names a parameter" check stayed green."""
        for skill in (SkillName.PUSH, SkillName.COOPERATIVE_PUSH):
            effects = DOMAIN_IR.skill(skill).predicted_world_effects
            with self.subTest(skill=skill):
                self.assertIn("box.delivered_post is True", effects)
                self.assertIn(
                    "box.position_post == first_zone_cell_along(box.position_pre, D)", effects
                )

    def test_push_and_cooperative_push_source_their_direction_differently(self):
        """Not an accident: `PushSkill` reads the agent's facing, `CooperativePushSkill` computes
        the direction from the box and turns the agents onto it. Swapping either is a real defect
        and both were previously digest-only."""
        push = DOMAIN_IR.skill(SkillName.PUSH).predicted_world_effects
        coop = DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH).predicted_world_effects
        self.assertIn("D == direction_vector(agent.direction_pre)", push)
        self.assertNotIn("D == direction_vector(push_dir(box, zone))", push)
        self.assertIn("D == direction_vector(push_dir(box, zone))", coop)
        self.assertNotIn("D == direction_vector(agent1.direction_pre)", coop)

    def test_push_terminal_agent_position_is_relative_to_the_terminal_box(self):
        """`Push` is a multi-cell loop, so the agent ends one cell behind wherever the box STOPPED,
        never on the box's pre-state cell."""
        push = DOMAIN_IR.skill(SkillName.PUSH).predicted_world_effects
        self.assertIn("agent.position_post == box.position_post - D", push)
        self.assertNotIn("agent.position_post == box.position_pre", push)

    def test_effects_are_part_of_the_frozen_domain_canonical_form(self):
        blob = DOMAIN_IR.canonical()
        goto = next(s for s in blob["skills"] if s["name"] == str(SkillName.GOTO_PUSH_POSE))
        self.assertIn("predicted_world_effects", goto)
        self.assertEqual(
            tuple(goto["predicted_world_effects"]),
            DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE).predicted_world_effects,
        )
        # `digest()` hashes `canonical()`, so being in the canonical form IS being in the digest.
        # Demonstrate the dependency instead of asserting `digest() == digest()`, which cannot fail.
        import copy, hashlib, json
        mutated = copy.deepcopy(blob)
        mutated["skills"][0]["predicted_world_effects"] = []
        digest_of = lambda b: hashlib.sha256(
            json.dumps(b, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest_of(blob), DOMAIN_IR.digest())
        self.assertNotEqual(digest_of(mutated), DOMAIN_IR.digest())


# ── Decision 13.8: executive-tracked literal maintenance ──────────────────────────

class TestExecutiveTrackedOutcomeRule(unittest.TestCase):
    def setUp(self):
        self.base = project(initial_state())
        self.a0b1 = GroundedLiteral(P_IN_POSE, (AGENT_0.value, str(BOX_LIGHT)))
        self.a0b0 = GroundedLiteral(P_IN_POSE, (AGENT_0.value, str(BOX_HEAVY)))
        self.a1b1 = GroundedLiteral(P_IN_POSE, (AGENT_1.value, str(BOX_LIGHT)))

    def test_success_establishes_the_grounded_literal(self):
        after = PROJECTION.apply_outcome(
            self.base, self.a0b1, succeeded=True, world_changed=True
        )
        self.assertTrue(after.holds(self.a0b1))

    def test_failure_never_applies_the_success_effect(self):
        for world_changed in (True, False):
            with self.subTest(world_changed=world_changed):
                after = PROJECTION.apply_outcome(
                    self.base, self.a0b1, succeeded=False, world_changed=world_changed
                )
                self.assertFalse(after.holds(self.a0b1))

    def test_a_failure_that_moved_the_world_invalidates_the_attempted_literal(self):
        held = PROJECTION.establish(self.base, self.a0b1)
        after = PROJECTION.apply_outcome(
            held, self.a0b1, succeeded=False, world_changed=True
        )
        self.assertFalse(after.holds(self.a0b1))

    def test_a_failure_that_moved_nothing_preserves_a_literal_that_was_already_true(self):
        """Decision 13.8: invalidate only when the attempt could have disturbed the prior truth.
        `UNCHANGED` and `BACKEND_REJECTED_BEFORE_TRANSITION` both imply the world did not move, so
        `in_pose` is exactly as guaranteed as it was — discarding it would throw away a fact the
        executive still knows."""
        held = PROJECTION.establish(self.base, self.a0b1)
        after = PROJECTION.apply_outcome(
            held, self.a0b1, succeeded=False, world_changed=False
        )
        self.assertTrue(after.holds(self.a0b1))
        self.assertEqual(after.literals, held.literals)

    def test_world_changed_is_required_so_no_call_site_can_forget_it(self):
        with self.assertRaises(TypeError):
            PROJECTION.apply_outcome(self.base, self.a0b1, succeeded=False)

    def test_failure_touches_no_other_grounding_of_the_same_predicate(self):
        """V1 does not infer global exclusivity (Decision 6 keeps `in_pose` non-exclusive), so a
        failure on one grounding must not be used to clean up the others."""
        state = self.base
        for lit in (self.a0b0, self.a0b1, self.a1b1):
            state = PROJECTION.establish(state, lit)
        after = PROJECTION.apply_outcome(
            state, self.a0b1, succeeded=False, world_changed=True
        )
        self.assertFalse(after.holds(self.a0b1))
        self.assertTrue(after.holds(self.a0b0))
        self.assertTrue(after.holds(self.a1b1))

    def test_success_does_not_retract_a_sibling_grounding_either(self):
        state = PROJECTION.apply_outcome(
            self.base, self.a0b0, succeeded=True, world_changed=True
        )
        state = PROJECTION.apply_outcome(state, self.a0b1, succeeded=True, world_changed=True)
        self.assertTrue(state.holds(self.a0b0))
        self.assertTrue(state.holds(self.a0b1))

    @staticmethod
    def _execution(failure_class):
        """A REAL `ExecutionResult` for the given class. `ExecutionResult.__post_init__` already
        enforces the failure_class <-> world_changed consistency, so the post-state cannot lie."""
        from shared.execution import (
            ExecutionOutcome, ExecutionResult, FailureStateClass, StepAccounting,
        )
        from shared.state_snapshot import BoxSnapshot
        pre = initial_state()
        if failure_class is FailureStateClass.PARTIAL_EXECUTION:
            b = pre.box(BOX_LIGHT)
            post = pre.with_box(
                BoxSnapshot(b.box_id, (5, 4), b.required_agents, b.is_target, b.delivered)
            )
            outcome = ExecutionOutcome.PARTIAL
        else:
            post = pre
            outcome = ExecutionOutcome.FAILURE
        return ExecutionResult(
            call=PUSH_CALL, outcome=outcome, pre_state=pre, post_state=post,
            accounting=StepAccounting(1, 3), failure_class=failure_class,
        )

    def test_the_rule_is_driven_by_a_real_execution_result_not_a_loose_boolean(self):
        """`shared/symbolic_state.py` states the call-site contract: the caller holds the
        `ExecutionResult` and passes `result.world_changed`. Exercise exactly that, per typed
        failure class — an earlier version of this test looped over the classes without ever using
        the loop variable, so it proved nothing about any of them."""
        from shared.execution import FailureStateClass
        held = PROJECTION.establish(self.base, self.a0b1)
        expected_retained = {
            FailureStateClass.UNCHANGED: True,
            FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION: True,
            FailureStateClass.PARTIAL_EXECUTION: False,
        }
        self.assertEqual(set(expected_retained), set(FailureStateClass),
                         "a failure class was added without deciding its in_pose behaviour")
        for failure_class, retained in expected_retained.items():
            with self.subTest(failure_class=failure_class):
                result = self._execution(failure_class)
                self.assertEqual(
                    result.world_changed,
                    failure_class is FailureStateClass.PARTIAL_EXECUTION,
                    "fixture does not match the class it claims",
                )
                after = PROJECTION.apply_outcome(
                    held, self.a0b1, succeeded=False, world_changed=result.world_changed
                )
                self.assertEqual(after.holds(self.a0b1), retained)

    def test_a_pre_executor_rejection_leaves_symbolic_state_untouched(self):
        """No attempt occurred, so nothing is applied and nothing is retracted — the rule is that
        `apply_outcome` is not called at all."""
        from shared.skills import MalformedCall, SymbolicallyInapplicable, UngroundedCall
        held = PROJECTION.establish(self.base, self.a0b1)
        for rejection in (
            MalformedCall(reason="r"), UngroundedCall(reason="r"),
            SymbolicallyInapplicable(reason="r"),
        ):
            with self.subTest(kind=type(rejection).__name__):
                self.assertTrue(rejection.is_pre_executor_rejection)
                self.assertFalse(rejection.is_executable)
        # The rule is "apply_outcome is not called at all", so the state a caller holds is the
        # state it keeps — identical object contents, not merely still-true.
        self.assertEqual(held.literals, PROJECTION.establish(self.base, self.a0b1).literals)
        self.assertTrue(held.holds(self.a0b1))

    def test_a_successful_skill_can_apply_a_negative_effect(self):
        """`Push` deletes `in_pose(agent, box)` on SUCCESS. Expressing that through
        `apply_outcome(succeeded=False)` would conflate effect polarity with execution outcome, so
        `retract` exists as its own operation."""
        self.assertIn(
            (P_IN_POSE, False),
            [(str(e.predicate.name), e.positive) for e in DOMAIN_IR.skill(SkillName.PUSH).effects],
        )
        held = PROJECTION.establish(self.base, self.a0b1)
        after = PROJECTION.retract(held, self.a0b1)
        self.assertFalse(after.holds(self.a0b1))

    def test_retract_removes_exactly_one_grounding(self):
        state = PROJECTION.establish(PROJECTION.establish(self.base, self.a0b0), self.a0b1)
        after = PROJECTION.retract(state, self.a0b1)
        self.assertTrue(after.holds(self.a0b0))
        self.assertFalse(after.holds(self.a0b1))

    def test_retract_of_an_absent_literal_is_a_no_op(self):
        self.assertEqual(PROJECTION.retract(self.base, self.a0b1).literals, self.base.literals)

    def test_apply_outcome_is_exactly_establish_or_retract(self):
        for succeeded in (True, False):
            with self.subTest(succeeded=succeeded):
                expected = (
                    PROJECTION.establish(self.base, self.a0b1) if succeeded
                    else PROJECTION.retract(self.base, self.a0b1)
                )
                self.assertEqual(
                    PROJECTION.apply_outcome(
                        self.base, self.a0b1, succeeded=succeeded, world_changed=True
                    ).literals,
                    expected.literals,
                )

    def test_establish_and_retract_also_refuse_projectable_predicates(self):
        delivered = GroundedLiteral(P_DELIVERED, (str(BOX_LIGHT),))
        for op in (PROJECTION.establish, PROJECTION.retract):
            with self.subTest(op=op.__name__), self.assertRaises(ValueError):
                op(self.base, delivered)

    def test_a_projectable_predicate_cannot_be_patched_from_an_outcome(self):
        """`delivered` comes from the authoritative state; patching it from an outcome is exactly
        how a model starts believing its own predictions."""
        with self.assertRaises(ValueError):
            PROJECTION.apply_outcome(
                self.base, GroundedLiteral(P_DELIVERED, (str(BOX_LIGHT),)),
                succeeded=True, world_changed=True,
            )

    def test_executive_tracked_updates_never_move_the_monitored_key(self):
        before = PROJECTION.monitored_key(self.base)
        after = PROJECTION.apply_outcome(
            self.base, self.a0b1, succeeded=True, world_changed=True
        )
        self.assertEqual(PROJECTION.monitored_key(after), before)


# ── Decision 14: frozen adapter dispatch ──────────────────────────────────────────

class TestBackendDispatchKeysAreFrozen(unittest.TestCase):
    def test_every_registry_skill_has_a_distinct_snake_case_dispatch_key(self):
        """`assertTrue(sig.backend_dispatch_key)` cannot fail while `__post_init__` rejects empty
        (tested separately), so assert something the constructor does NOT already guarantee."""
        seen = set()
        for sig in REGISTRY:
            key = sig.backend_dispatch_key
            with self.subTest(skill=sig.name):
                self.assertRegex(key, r"^[a-z][a-z_]*$")
                self.assertNotIn(key, seen)
                self.assertNotEqual(key, str(sig.name))    # not just the CamelCase name reused
                seen.add(key)

    def test_dispatch_keys_are_exhaustive_over_the_registry(self):
        """Uniqueness is enforced at construction (`SkillRegistry.__init__`) and tested at
        `test_duplicate_dispatch_keys_are_refused`; this checks only coverage."""
        table = REGISTRY.dispatch_keys()
        self.assertEqual(len(table), len(REGISTRY))
        self.assertEqual(set(table.values()), set(REGISTRY.names()))

    def test_duplicate_skill_names_are_refused(self):
        from shared.skills import SkillRegistry, _SIGNATURES
        with self.assertRaises(ValueError):
            SkillRegistry(_SIGNATURES + (_SIGNATURES[0],))

    def test_duplicate_dispatch_keys_are_refused(self):
        from shared.skills import SkillRegistry, _SIGNATURES
        clash = tuple(
            SkillSignature(
                name=sig.name, parameters=sig.parameters, cost=sig.cost,
                in_symbolic_action_set=sig.in_symbolic_action_set,
                backend_mapping=sig.backend_mapping, backend_dispatch_key="same",
            )
            for sig in _SIGNATURES
        )
        with self.assertRaises(ValueError):
            SkillRegistry(clash)

    def test_the_frozen_tokens_are_exactly_these(self):
        self.assertEqual(
            REGISTRY.dispatch_keys(),
            {
                "goto_push_pose": SkillName.GOTO_PUSH_POSE,
                "push": SkillName.PUSH,
                "cooperate_push": SkillName.COOPERATIVE_PUSH,
                "explore": SkillName.EXPLORE,
                "wait": SkillName.WAIT,
            },
        )

    def test_wait_has_its_own_token(self):
        """The W1 defect: `make_skill` has no 'wait' arm, so 'wait', 'Push' and '' all reach
        WaitSkill through the default. P1 must route Wait explicitly."""
        self.assertIs(REGISTRY.by_dispatch_key("wait").name, SkillName.WAIT)

    def test_an_unknown_token_raises_instead_of_falling_back(self):
        for token in ("", "Push", "garbage", "WAIT"):
            with self.subTest(token=token), self.assertRaises(KeyError):
                REGISTRY.by_dispatch_key(token)

    def test_a_signature_without_a_dispatch_key_is_refused(self):
        with self.assertRaises(ValueError):
            SkillSignature(name=SkillName.WAIT, parameters=(), backend_mapping="x")

    def test_a_signature_without_a_backend_mapping_is_refused(self):
        with self.assertRaises(ValueError):
            SkillSignature(name=SkillName.WAIT, parameters=(), backend_dispatch_key="x")


# ── W8: OutsideSymbolicModel ──────────────────────────────────────────────────────

class TestOutsideSymbolicModel(unittest.TestCase):
    def test_registry_only_skills_resolve_to_a_typed_non_fault_result(self):
        for name in (SkillName.EXPLORE, SkillName.WAIT):
            with self.subTest(skill=name):
                result = DOMAIN_IR.resolve(name)
                self.assertIsInstance(result, OutsideSymbolicModel)
                self.assertFalse(result.is_infrastructure_fault)
                self.assertFalse(result.is_accepted)
                self.assertIs(result.skill, name)

    def test_it_is_not_symbolically_inapplicable(self):
        """Inapplicable asserts preconditions were evaluated and failed. Here there is no model to
        evaluate, so that verdict would be a claim the symbolic track cannot support."""
        self.assertNotIsInstance(DOMAIN_IR.resolve(SkillName.EXPLORE), SymbolicallyInapplicable)

    def test_symbolic_skills_still_resolve_to_their_ir(self):
        for name in (SkillName.PUSH, SkillName.GOTO_PUSH_POSE, SkillName.COOPERATIVE_PUSH):
            with self.subTest(skill=name):
                self.assertIsInstance(DOMAIN_IR.resolve(name), SkillIR)

    def test_skill_still_raises_for_the_registry_only_case(self):
        """`resolve` is the typed door; `skill` stays strict so a planner cannot silently plan
        with Explore."""
        with self.assertRaises(KeyError):
            DOMAIN_IR.skill(SkillName.EXPLORE)

    def test_the_registry_and_the_domain_agree_on_the_symbolic_action_set(self):
        """`DomainIR.resolve` decides from `DOMAIN_IR.skills`; `OutsideSymbolicModel.__post_init__`
        cross-checks `SkillSignature.in_symbolic_action_set`. If those two ever disagree, `resolve`
        raises `ValueError` instead of returning the typed result it exists to return."""
        self.assertEqual(set(REGISTRY.symbolic_action_set()), set(DOMAIN_IR.action_set()))

    def test_it_cannot_be_constructed_for_a_skill_that_is_in_the_symbolic_model(self):
        with self.assertRaises(ValueError):
            OutsideSymbolicModel(reason="wrong", skill=SkillName.PUSH)

    def test_it_is_executable_even_though_it_is_not_accepted(self):
        """Gating execution on `is_accepted` would refuse Explore/Wait — the opposite of the
        intent. `is_executable` is the correct gate."""
        result = DOMAIN_IR.resolve(SkillName.EXPLORE)
        self.assertFalse(result.is_accepted)
        self.assertTrue(result.is_executable)

    def test_the_genuine_rejections_are_not_executable(self):
        from shared.skills import MalformedCall, UngroundedCall
        for rejection in (
            MalformedCall(reason="r"), UngroundedCall(reason="r"),
            SymbolicallyInapplicable(reason="r"),
        ):
            with self.subTest(kind=type(rejection).__name__):
                self.assertFalse(rejection.is_executable)

    def test_a_validated_call_is_executable(self):
        from shared.skills import ValidatedCall
        self.assertTrue(ValidatedCall(call=PUSH_CALL).is_executable)

    def test_it_infers_the_skill_from_the_call(self):
        call = GroundedSkillCall(SkillName.EXPLORE, (AGENT_0,))
        self.assertIs(OutsideSymbolicModel(reason="r", call=call).skill, SkillName.EXPLORE)

    def test_the_five_validation_outcomes_are_distinct_types(self):
        from shared.skills import MalformedCall, UngroundedCall, ValidatedCall
        kinds = {ValidatedCall, MalformedCall, UngroundedCall, SymbolicallyInapplicable,
                 OutsideSymbolicModel}
        self.assertEqual(len(kinds), 5)
        for a in kinds:
            for b in kinds:
                if a is not b:
                    with self.subTest(a=a.__name__, b=b.__name__):
                        self.assertFalse(issubclass(a, b))


# ── Trace carries both prediction bases ───────────────────────────────────────────

class TestTraceRecordsBothBases(unittest.TestCase):
    def test_trace_entry_carries_a_separate_field_per_basis(self):
        from domain.box_push_v1 import MODEL_VERSION, TASK_DELIVER_LIGHT, _PROVENANCE
        pre = initial_state()
        entry = TraceEntry(
            executive_step=0,
            task=TASK_DELIVER_LIGHT,
            pre_state=pre,
            model_version=MODEL_VERSION,
            provenance=_PROVENANCE,
            predicted_world_key=_delivered(pre, BOX_LIGHT).world_key(),
            predicted_symbolic_key=PROJECTION.monitored_key(project(_delivered(pre, BOX_LIGHT))),
        )
        blob = entry.canonical()
        self.assertNotEqual(blob["predicted_world_key"], blob["predicted_symbolic_key"])
        self.assertIsNotNone(blob["predicted_symbolic_key"])


# ── W11: the contract surface is exported ─────────────────────────────────────────

class TestContractSurfaceIsExported(unittest.TestCase):
    def test_symbolic_contract_names_are_exported(self):
        import shared
        for name in (
            "SymbolicState", "GroundedLiteral", "ProjectionContract", "REGISTRY",
            "OutsideSymbolicModel", "ComparisonBasis",
        ):
            with self.subTest(name=name):
                self.assertIn(name, shared.__all__)
                self.assertTrue(hasattr(shared, name))

    def test_every_exported_name_resolves(self):
        import shared
        self.assertEqual([n for n in shared.__all__ if not hasattr(shared, n)], [])


if __name__ == "__main__":
    unittest.main()
