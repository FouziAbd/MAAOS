"""P3 NL baseline: typed modules, offline seam, and the peer-track guards.

Default tests are DETERMINISTIC AND OFFLINE (.claude/rules/testing.md): every LM interaction
goes through `RecordedLM` fixtures; nothing here imports dspy or touches a network. Live-model
coverage lives exclusively in tests/test_p3_live_lm.py behind MAAOS_LIVE_LM=1.
"""
import ast
import pathlib
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    TASK_DELIVER_BOTH,
    initial_state,
)
from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.execution import ExecutionOutcome
from shared.ids import AgentId
from shared.skills import GroundedSkillCall, MalformedCall, SkillName
from shared.symbolic_state import GroundedLiteral

from nl import (
    FORMAT_INSTRUCTIONS,
    NLProposal,
    NLRequest,
    NLTrack,
    PINNED_V1_NL_RUNTIME,
    NLRuntimeConfig,
    RecordedLM,
    RepairSkillCall,
    SemanticBelief,
    SkillSelector,
    UnrecordedRequestError,
    interpret_task,
    parse_skill_call,
    propose_recovery,
    translate_proposal,
    update_belief,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

GOTO = GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
PUSH = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
COOP = GroundedSkillCall(
    SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE
)
WAIT = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))
EXPLORE = GroundedSkillCall(SkillName.EXPLORE, (AGENT_0,))
ALL_CALLS = (GOTO, PUSH, COOP, WAIT, EXPLORE)


class _CountingSeam:
    """Wraps a RecordedLM and counts calls — pins 'exactly one repair attempt'."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def complete(self, request):
        self.calls += 1
        return self.inner.complete(request)


# ── parser ─────────────────────────────────────────────────────────────────────────

class TestParser(unittest.TestCase):
    def test_every_registry_skill_round_trips_through_its_frozen_rendering(self):
        for call in ALL_CALLS:
            with self.subTest(call=str(call)):
                parsed = parse_skill_call(str(call))
                self.assertIsInstance(parsed, GroundedSkillCall)
                self.assertEqual(parsed, call)

    def test_surrounding_whitespace_is_tolerated_nothing_else(self):
        self.assertEqual(parse_skill_call("  Push(agent_0; box_1; delivery_zone)  "), PUSH)
        verdict = parse_skill_call("I think: Push(agent_0; box_1; delivery_zone)")
        self.assertIsInstance(verdict, MalformedCall)

    def test_malformed_inputs_become_typed_malformed_calls_with_raw_preserved(self):
        cases = {
            "": "empty",
            "garbage": "no call syntax",
            "Fly(agent_0)": "unknown skill",
            "explore(agent_0)": "lowercase legacy name is NOT the frozen name",
            "Push(agent_0, agent_1; box_1; delivery_zone)": "wrong arity",
            "Push(agent_0; crate_1; delivery_zone)": "bad box identity",
            "CooperativePush(agent_0,agent_0; box_0; delivery_zone)": "same agent twice",
            "Wait(agent_0; box_0; delivery_zone)": "wait takes no box/zone",
            "Push(agent_0; box_1; delivery_zone)\nPush(agent_0; box_1; delivery_zone)":
                "two lines",
        }
        for raw, label in cases.items():
            with self.subTest(case=label):
                verdict = parse_skill_call(raw)
                self.assertIsInstance(verdict, MalformedCall)
                self.assertEqual(verdict.raw, raw)          # provenance travels
                self.assertTrue(verdict.reason)

    def test_box_and_zone_are_dispatched_by_prefix_not_position(self):
        """Documented tolerance: the frozen rendering is canonical, but a swapped box/zone
        order still parses to the SAME canonical call (prefix dispatch), never a different one.
        Grounding of unknown-but-well-typed identities is the P1 adapter's job
        (`_resolve_identities` → UngroundedCall), tested in the P1/P2 suites."""
        self.assertEqual(parse_skill_call("Push(agent_0; delivery_zone; box_1)"), PUSH)

    def test_the_legacy_fallback_carries_its_superseded_banner(self):
        """§18 item 9: the legacy runner's silent explore fallback is banner-marked, and the
        banner is PINNED like the PDDL banners — deleting it silently fails here."""
        legacy = (REPO_ROOT / "functional_layer" / "custom_env" / "box_push" / "env"
                  / "box_push_centralized.py").read_text(encoding="utf-8")
        self.assertIn("SUPERSEDED FOR V1 (Decision 7 / decisions §18 item 9)", legacy)
        self.assertIn("nl/parser.py", legacy)

    def test_no_silent_substitution_ever(self):
        """Decision 7 / §18 item 9: the legacy runner rewrote garbage to ('explore', None).
        The typed parser returns MalformedCall — asserting the TYPE is the whole point."""
        for raw in ("", "garbage", "do something useful", "explore", "wait"):
            with self.subTest(raw=raw):
                self.assertNotIsInstance(parse_skill_call(raw), GroundedSkillCall)


# ── seam + runtime config ──────────────────────────────────────────────────────────

class TestSeam(unittest.TestCase):
    def test_request_key_is_field_order_insensitive_and_deterministic(self):
        a = NLRequest.of("m", x="1", y="2")
        b = NLRequest(module="m", fields=(("y", "2"), ("x", "1")))
        self.assertEqual(a.key(), b.key())

    def test_request_key_distinguishes_modules_with_identical_fields(self):
        self.assertNotEqual(
            NLRequest.of("a", x="1").key(), NLRequest.of("b", x="1").key()
        )

    def test_recorded_lm_is_exact_match_with_a_typed_miss(self):
        req = NLRequest.of("m", q="hello")
        seam = RecordedLM.of({req: "answer"})
        self.assertEqual(seam.complete(NLRequest.of("m", q="hello")), "answer")
        with self.assertRaises(UnrecordedRequestError):
            seam.complete(NLRequest.of("m", q="other"))

    def test_pinned_runtime_is_temperature_zero_and_caching(self):
        self.assertEqual(PINNED_V1_NL_RUNTIME.temperature, 0.0)
        self.assertTrue(PINNED_V1_NL_RUNTIME.cache)
        self.assertEqual(PINNED_V1_NL_RUNTIME.model, "ollama_chat/gemma4:e4b")
        with self.assertRaises(ValueError):
            NLRuntimeConfig(
                provider="ollama", model="m", api_base="b", api_key="k",
                temperature=0.7, seed=1, cache=True,
            )


# ── task + observation interpretation, semantic belief ─────────────────────────────

class TestInterpretation(unittest.TestCase):
    def test_typed_goal_is_authoritative_and_fully_covered(self):
        interpreted = interpret_task(TASK_DELIVER_BOTH)
        self.assertEqual(
            interpreted.goal_literals,
            frozenset({
                GroundedLiteral("delivered", (str(BOX_HEAVY),)),
                GroundedLiteral("delivered", (str(BOX_LIGHT),)),
            }),
        )
        self.assertTrue(interpreted.coverage.is_complete)

    def test_unexpressible_clause_lands_in_the_residual_not_the_floor(self):
        from shared.task import Task
        task = Task(
            task_id="t", description="Deliver both boxes. Sing a song while doing it.",
            goal_delivered=TASK_DELIVER_BOTH.goal_delivered, zone=DELIVERY_ZONE,
        )
        coverage = interpret_task(task).coverage
        self.assertFalse(coverage.is_complete)
        self.assertEqual(len(coverage.residual), 1)
        self.assertIn("Sing a song", coverage.residual[0])

    def test_every_frozen_representative_task_classifies_fully_covered(self):
        """Consistency-check P3 WARN 7: TASK_DELIVER_HEAVY's requirement clause ('It needs both
        agents') IS expressible — `heavy(box)`/`required_agents` and the CooperativePush arity
        carry it — so no frozen task may feed spurious COVERAGE_GAP evidence to P4."""
        from domain.box_push_v1 import TASKS
        for task in TASKS:
            with self.subTest(task=task.task_id):
                coverage = interpret_task(task).coverage
                self.assertTrue(
                    coverage.is_complete,
                    f"{task.task_id}: spurious residual {coverage.residual}",
                )

    def test_requirement_rule_precision_boundary(self):
        """Consistency-check P3 round 2 (F1/F6): the requirement rule must not over-cover.
        Matching is token-based — substring hits like `"two" in "network"` were live defects —
        and bare counts are not requirement objects. "The agents need a break" is the RECORDED
        imprecision ceiling (see the module comment): pinned covered, deliberately."""
        from shared.task import Task
        task = Task(
            task_id="t",
            description=(
                "Deliver both boxes. You need two hours. The network needs repair. "
                "The agents need a break."
            ),
            goal_delivered=TASK_DELIVER_BOTH.goal_delivered, zone=DELIVERY_ZONE,
        )
        coverage = interpret_task(task).coverage
        residual_text = " ".join(coverage.residual)
        covered_text = " ".join(coverage.covered)
        self.assertIn("You need two hours", residual_text)
        self.assertIn("The network needs repair", residual_text)
        self.assertIn("The agents need a break", covered_text)   # the recorded ceiling
        self.assertIn("Deliver both boxes", covered_text)

    def test_object_stems_match_token_prefixes_not_interior_substrings(self):
        """Kills the substring-regression mutant (Q14): "mailbox" contains "box" but is not a
        box token — 'Push the mailbox flag' is NOT expressible and must be residual."""
        from shared.task import Task
        task = Task(
            task_id="t", description="Deliver both boxes. Push the mailbox flag.",
            goal_delivered=TASK_DELIVER_BOTH.goal_delivered, zone=DELIVERY_ZONE,
        )
        coverage = interpret_task(task).coverage
        self.assertIn("Push the mailbox flag", " ".join(coverage.residual))

    def test_keyword_bearing_but_unexpressible_clauses_are_residual(self):
        """Architecture review W3: bare keyword containment over-claimed coverage. Negation and
        verbless keyword mentions are OUTSIDE the V1 vocabulary and must reach the residual."""
        from shared.task import Task
        task = Task(
            task_id="t",
            description="Deliver both boxes. Do not push box_0 before box_1. Paint the zone red.",
            goal_delivered=TASK_DELIVER_BOTH.goal_delivered, zone=DELIVERY_ZONE,
        )
        coverage = interpret_task(task).coverage
        self.assertIn("Deliver both boxes", "".join(coverage.covered))
        residual_text = " ".join(coverage.residual)
        self.assertIn("Do not push box_0", residual_text)
        self.assertIn("Paint the zone red", residual_text)

    def test_every_negation_form_reaches_the_residual(self):
        """Round 3 (consistency check): "cannot" and bare "no" are single tokens the original
        set missed — a NEGATED delivery clause must never classify covered."""
        from shared.task import Task
        task = Task(
            task_id="t",
            description=(
                "Deliver both boxes. You cannot push the heavy box alone. "
                "No pushing boxes out of the zone. Don't move the target box yet. "
                "Never bring a box backwards. Avoid the goal zone at night."
            ),
            goal_delivered=TASK_DELIVER_BOTH.goal_delivered, zone=DELIVERY_ZONE,
        )
        coverage = interpret_task(task).coverage
        covered_clauses = [c for c in coverage.covered if not c.startswith("delivered(")]
        self.assertEqual(covered_clauses, ["Deliver both boxes"])
        self.assertEqual(len(coverage.residual), 5, coverage.residual)

    def test_belief_facts_are_exact_rederivations_not_dead_reckoning(self):
        snap = initial_state()
        belief = update_belief(SemanticBelief(), snap)
        self.assertIn("agent_0 is at (10, 10) facing left", belief.facts)
        moved = update_belief(belief, snap)                    # same world → same facts
        self.assertEqual(moved.facts, belief.facts)
        self.assertEqual(belief.facts, tuple(sorted(belief.facts)))

    def test_a_changed_world_changes_the_facts_no_stale_retention(self):
        """Kills the dead-reckoning mutant: the belief must re-derive from THIS snapshot,
        never keep yesterday's facts because they exist."""
        from shared.state_snapshot import AgentSnapshot, StateSnapshot
        snap = initial_state()
        belief = update_belief(SemanticBelief(), snap)
        relocated = StateSnapshot(
            agents=(AgentSnapshot(AGENT_0, (5, 5), 1),) + snap.agents[1:],
            boxes=snap.boxes, static=snap.static, episode=snap.episode,
        )
        updated = update_belief(belief, relocated)
        self.assertIn("agent_0 is at (5, 5) facing down", updated.facts)
        self.assertNotIn("agent_0 is at (10, 10) facing left", updated.facts)

    def test_attempt_history_is_bounded_and_typed_outcome_only(self):
        snap = initial_state()
        belief = SemanticBelief()
        for i in range(12):
            belief = update_belief(belief, snap, "Push", ExecutionOutcome.FAILURE)
        self.assertEqual(len(belief.attempt_history), 8)
        self.assertIn("typed outcome", belief.attempt_history[-1])


# ── selector, repair, translator, recovery ─────────────────────────────────────────

class TestSelectorAndRepair(unittest.TestCase):
    def _selector_fixture(self, response):
        selector = SkillSelector(RecordedLM())          # request built without a seam call
        request = selector.build_request(
            interpret_task(TASK_DELIVER_BOTH), update_belief(SemanticBelief(), initial_state())
        )
        return SkillSelector(RecordedLM.of({request: response}))

    def test_recorded_response_becomes_a_typed_call(self):
        selector = self._selector_fixture("GotoPushPose(agent_0; box_1; delivery_zone)")
        proposal = selector.propose(
            interpret_task(TASK_DELIVER_BOTH), update_belief(SemanticBelief(), initial_state())
        )
        self.assertEqual(proposal, GOTO.__class__(
            SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE
        ))

    def test_garbage_response_is_a_malformed_call_not_a_default(self):
        selector = self._selector_fixture("hmm, maybe explore around?")
        proposal = selector.propose(
            interpret_task(TASK_DELIVER_BOTH), update_belief(SemanticBelief(), initial_state())
        )
        self.assertIsInstance(proposal, MalformedCall)

    def test_repair_fixes_in_exactly_one_attempt(self):
        malformed = parse_skill_call("push box_1 please")
        repairer = RepairSkillCall(RecordedLM())
        request = repairer.build_request(malformed)
        seam = _CountingSeam(RecordedLM.of({request: "Push(agent_0; box_1; delivery_zone)"}))
        repaired = RepairSkillCall(seam).repair(malformed)
        self.assertEqual(repaired, PUSH)
        self.assertEqual(seam.calls, 1)

    def test_unrepairable_stays_a_typed_rejection_with_both_reasons(self):
        malformed = parse_skill_call("push box_1 please")
        repairer = RepairSkillCall(RecordedLM())
        request = repairer.build_request(malformed)
        seam = _CountingSeam(RecordedLM.of({request: "still garbage"}))
        verdict = RepairSkillCall(seam).repair(malformed)
        self.assertEqual(seam.calls, 1)                        # ONE attempt, then rejection
        self.assertIsInstance(verdict, MalformedCall)
        self.assertIn("unrepairable", verdict.reason)
        self.assertIn("original problem", verdict.reason)
        self.assertEqual(verdict.raw, "push box_1 please")


class TestRequestContent(unittest.TestCase):
    """The recorded-seam design is fail-closed on request DETERMINISM but blind to request
    CONTENT (test review FAIL-1/FAIL-2): these golden assertions pin what the model is TOLD."""

    def test_selector_request_carries_task_belief_menu_and_format(self):
        belief = update_belief(SemanticBelief(), initial_state())
        request = SkillSelector(RecordedLM()).build_request(
            interpret_task(TASK_DELIVER_BOTH), belief
        )
        fields = dict(request.fields)
        self.assertEqual(fields["objective"], TASK_DELIVER_BOTH.description)
        self.assertIn("delivered(box_0), delivered(box_1)", fields["goal"])
        self.assertIn("agent_0 is at (10, 10) facing left", fields["situation"])
        for name in SkillName:
            self.assertIn(name.value, fields["decision_space"])
        self.assertEqual(fields["format"], FORMAT_INSTRUCTIONS)

    def test_selector_situation_reflects_the_attempt_history(self):
        belief = update_belief(
            SemanticBelief(), initial_state(), "Push", ExecutionOutcome.FAILURE
        )
        request = SkillSelector(RecordedLM()).build_request(
            interpret_task(TASK_DELIVER_BOTH), belief
        )
        self.assertIn("typed outcome failure", dict(request.fields)["situation"])

    def test_repair_request_carries_the_raw_text_and_the_problem(self):
        malformed = parse_skill_call("push box_1 please")
        fields = dict(RepairSkillCall(RecordedLM()).build_request(malformed).fields)
        self.assertEqual(fields["raw"], "push box_1 please")
        self.assertEqual(fields["problem"], malformed.reason)
        self.assertEqual(fields["format"], FORMAT_INSTRUCTIONS)

    def test_format_instructions_pin_the_frozen_call_examples(self):
        self.assertIn("Push(agent_0; box_1; delivery_zone)", FORMAT_INSTRUCTIONS)
        self.assertIn("CooperativePush(agent_0,agent_1; box_0; delivery_zone)",
                      FORMAT_INSTRUCTIONS)
        self.assertIn("EXACTLY ONE skill call", FORMAT_INSTRUCTIONS)


class TestObservationInterpreter(unittest.TestCase):
    """Direct behavioural coverage (contract :223) — test review FAIL-3: the facts fed to the
    model must TELL THE TRUTH about directions, weights, and delivery status."""

    def _snap_with_agent0(self, direction):
        from shared.state_snapshot import AgentSnapshot, StateSnapshot
        snap = initial_state()
        return StateSnapshot(
            agents=(AgentSnapshot(AGENT_0, (5, 5), direction),) + snap.agents[1:],
            boxes=snap.boxes, static=snap.static, episode=snap.episode,
        )

    def test_all_four_direction_words(self):
        from nl.observation_interpreter import state_facts
        for direction, word in ((0, "right"), (1, "down"), (2, "left"), (3, "up")):
            with self.subTest(direction=direction):
                self.assertIn(
                    f"agent_0 is at (5, 5) facing {word}",
                    state_facts(self._snap_with_agent0(direction)),
                )

    def test_direction_words_match_the_backend_vector_convention(self):
        """The P2 predictor's _DIRECTION_VECTORS got a backend pin (W-2); the NL words get the
        same one: each word must describe the sign of the backend's vector for that index."""
        import sys
        cst = str(REPO_ROOT / "functional_layer" / "custom_env"
                  / "cooperative_search_transport" / "env")
        if cst not in sys.path:
            sys.path.insert(0, cst)
        from constants import DIRECTION_VECTORS
        from nl.observation_interpreter import _DIRECTION_WORDS
        expected = {(1, 0): "right", (0, 1): "down", (-1, 0): "left", (0, -1): "up"}
        for index, vector in DIRECTION_VECTORS.items():
            with self.subTest(index=index):
                self.assertEqual(_DIRECTION_WORDS[index], expected[tuple(vector)])

    def test_box_facts_state_weight_and_delivery_truthfully(self):
        from shared.state_snapshot import BoxSnapshot, StateSnapshot
        from nl.observation_interpreter import state_facts
        snap = initial_state()
        delivered_light = StateSnapshot(
            agents=snap.agents,
            boxes=tuple(
                BoxSnapshot(b.box_id, b.position, b.required_agents, b.is_target, True)
                if b.box_id == BOX_LIGHT else b
                for b in snap.boxes
            ),
            static=snap.static, episode=snap.episode,
        )
        facts = state_facts(delivered_light)
        light = next(f for f in facts if f.startswith("box_1"))
        heavy = next(f for f in facts if f.startswith("box_0"))
        self.assertIn("one agent can push it", light)
        self.assertIn("already delivered", light)
        self.assertIn("needs two agents", heavy)
        self.assertIn("not delivered yet", heavy)

    def test_outcome_fact_is_typed_outcome_only(self):
        from nl.observation_interpreter import outcome_fact
        self.assertIsNone(outcome_fact("Push", None))
        self.assertEqual(
            outcome_fact("Push", ExecutionOutcome.SUCCESS),
            "the last attempt (Push) ended with typed outcome success",
        )


class TestTranslatorAndRecovery(unittest.TestCase):
    def test_symbolic_skills_translate_completely(self):
        for call in (GOTO, PUSH, COOP):
            with self.subTest(call=str(call)):
                translated = translate_proposal(call)
                self.assertTrue(translated.coverage.is_complete)
                self.assertEqual(translated.symbolic_form, call.key())
                self.assertEqual(translated.confidence.source, "nl")
                self.assertEqual(translated.confidence.confidence, 1.0)

    def test_registry_only_skills_translate_with_an_explicit_residual(self):
        for call in (WAIT, EXPLORE):
            with self.subTest(call=str(call)):
                translated = translate_proposal(call)
                self.assertFalse(translated.coverage.is_complete)
                self.assertIn("outside the V1 symbolic model", translated.coverage.residual[0])

    def test_recovery_answers_the_livelock_with_reestablishment(self):
        failed = ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL,
            call=PUSH, message="designed failure",
        )
        (proposal,) = propose_recovery(failed)
        self.assertEqual(
            proposal,
            GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE),
        )

    def test_coop_failure_proposes_reestablishment_for_both_agents(self):
        failed = ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL,
            call=COOP, message="x",
        )
        proposals = propose_recovery(failed)
        self.assertEqual(len(proposals), 2)
        self.assertEqual({p.agents[0] for p in proposals}, {AGENT_0, AGENT_1})
        self.assertTrue(all(p.skill is SkillName.GOTO_PUSH_POSE for p in proposals))

    def test_everything_else_gets_no_proposal_never_an_invented_one(self):
        establishing = ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, call=GOTO, message="x",
        )
        from shared.comparison_keys import SymbolicKey
        mismatch = ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=PUSH, message="x",
            predicted_symbolic_key=SymbolicKey("a" * 16),
            observed_symbolic_key=SymbolicKey("b" * 16),
        )
        self.assertEqual(propose_recovery(establishing), ())
        self.assertEqual(propose_recovery(mismatch), ())


# ── the stub track ─────────────────────────────────────────────────────────────────

class TestNLTrack(unittest.TestCase):
    def _track_with(self, selector_response, repair_response=None):
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

    def test_clean_cycle_produces_a_typed_proposal_with_merged_coverage(self):
        track = self._track_with("CooperativePush(agent_0,agent_1; box_0; delivery_zone)")
        proposal = track.propose(TASK_DELIVER_BOTH)
        self.assertEqual(proposal.call, COOP)
        self.assertIsNone(proposal.malformed)
        self.assertFalse(proposal.repaired)
        self.assertTrue(proposal.coverage.is_complete)
        self.assertIn(COOP.key(), proposal.coverage.covered)   # translation evidence survives
        self.assertEqual(proposal.confidence.source, "nl")
        self.assertEqual(proposal.confidence.confidence, 1.0)

    def test_malformed_then_repaired_cycle_is_flagged_repaired(self):
        track = self._track_with(
            "let's push the light box", "Push(agent_0; box_1; delivery_zone)"
        )
        proposal = track.propose(TASK_DELIVER_BOTH)
        self.assertEqual(proposal.call, PUSH)
        self.assertTrue(proposal.repaired)

    def test_unrepairable_cycle_surfaces_the_standing_malformed_call(self):
        track = self._track_with("let's push the light box", "nope, still chatting")
        proposal = track.propose(TASK_DELIVER_BOTH)
        self.assertIsNone(proposal.call)
        self.assertIsInstance(proposal.malformed, MalformedCall)
        self.assertIn("unrepairable", proposal.malformed.reason)

    def test_registry_only_proposal_keeps_the_translation_residual_in_the_merge(self):
        track = self._track_with("Wait(agent_0)")
        proposal = track.propose(TASK_DELIVER_BOTH)
        self.assertEqual(proposal.call, WAIT)
        self.assertFalse(proposal.coverage.is_complete)
        self.assertTrue(any(
            "outside the V1 symbolic model" in item for item in proposal.coverage.residual
        ))
        self.assertEqual(proposal.confidence.confidence, 0.5)

    def test_proposals_are_deterministic(self):
        a = self._track_with("Push(agent_0; box_1; delivery_zone)").propose(TASK_DELIVER_BOTH)
        b = self._track_with("Push(agent_0; box_1; delivery_zone)").propose(TASK_DELIVER_BOTH)
        self.assertEqual(a, b)

    def test_observe_plumbs_the_typed_outcome_into_the_belief(self):
        track = NLTrack(RecordedLM())
        track.observe(initial_state(), "Push", ExecutionOutcome.FAILURE)
        self.assertTrue(track.belief.attempt_history)
        self.assertIn("typed outcome failure", track.belief.attempt_history[-1])

    def test_propose_before_observe_is_a_typed_precondition_error(self):
        with self.assertRaises(RuntimeError):
            NLTrack(RecordedLM()).propose(TASK_DELIVER_BOTH)

    def test_a_proposal_carries_exactly_one_of_call_or_malformed(self):
        from shared.reports import CoverageReport
        with self.assertRaises(ValueError):
            NLProposal(call=None, malformed=None, coverage=CoverageReport(),
                       confidence=None, repaired=False)
        with self.assertRaises(ValueError):
            NLProposal(call=PUSH, malformed=MalformedCall("r"), coverage=CoverageReport(),
                       confidence=None, repaired=False)


# ── structural guards ──────────────────────────────────────────────────────────────

class TestPeerTrackGuards(unittest.TestCase):
    NL_DIR = REPO_ROOT / "nl"
    SYMBOLIC_DIR = REPO_ROOT / "symbolic"

    @staticmethod
    def _imports(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
        return found

    def test_nl_is_discovered_by_the_fail_closed_import_guard(self):
        """The auto-discovered guard bans backend/dspy/runtime imports from nl/ — the NL track
        structurally CANNOT execute skills or bind a framework outside the seam."""
        from tests.test_no_backend_imports import discovered_guarded_packages
        self.assertIn("nl", discovered_guarded_packages())

    def test_peer_tracks_cannot_import_each_other(self):
        """The NL track must not become the symbolic planner, and the symbolic track must not
        consult the NL track (CLAUDE.md NL/DSPy policy; contract :238)."""
        for source in sorted(self.NL_DIR.glob("*.py")):
            with self.subTest(module=f"nl/{source.name}"):
                self.assertNotIn("symbolic", self._imports(source))
        for source in sorted(self.SYMBOLIC_DIR.glob("*.py")):
            with self.subTest(module=f"symbolic/{source.name}"):
                self.assertNotIn("nl", self._imports(source))

    def test_nl_never_touches_provenance_or_reward_channels(self):
        """The binding rule on ExecutiveObservation: raw_label/notes/primitive_steps are
        provenance; reward and belief grids are invisible to the NL track (V1_VISIBILITY).
        Enforced at the AST attribute level over the whole package."""
        forbidden = {"raw_label", "notes", "reward", "belief_grid", "primitive_steps"}
        for source in sorted(self.NL_DIR.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            attributes = {
                node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            }
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            strings = {
                node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            with self.subTest(module=f"nl/{source.name}"):
                self.assertEqual(attributes & forbidden, set())
                # getattr/attrgetter would make the attribute scan blind — banned outright
                self.assertNotIn("getattr", names)
                self.assertNotIn("attrgetter", names)
                self.assertEqual(strings & forbidden, set())

    def test_default_tests_have_no_dspy_anywhere_in_the_import_closure(self):
        import sys
        self.assertNotIn("dspy", sys.modules)

    def test_no_default_test_module_imports_dspy_or_the_live_seam_at_module_scope(self):
        """The sys.modules check above is ordering-dependent (a later module could import dspy
        undetected under alphabetical discovery). This AST scan is not."""
        for source in sorted((REPO_ROOT / "tests").glob("*.py")):
            if source.name == "test_p3_live_lm.py":
                continue                       # the marked live module guards itself by env
            with self.subTest(module=f"tests/{source.name}"):
                found = self._imports(source)
                self.assertNotIn("dspy", found)
                self.assertNotIn("model_layer", found)

    def test_live_seam_module_is_not_imported_by_the_nl_package(self):
        for source in sorted(self.NL_DIR.glob("*.py")):
            with self.subTest(module=f"nl/{source.name}"):
                self.assertNotIn("model_layer", self._imports(source))


if __name__ == "__main__":
    unittest.main()
