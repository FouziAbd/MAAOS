"""Domain `cooperative_grid` — two agents, a heavy door that opens only when both pull it
together, and a designed hidden physical condition (the door starts JAMMED) that the
optimistic symbolic model never sees.

What is proven here (the numbering follows the experiment's required list):

  1  validate-domain has no FAIL            10  three repeated discrepancies are recorded
  2  the authoritative state has two agents 11  advisory_two_track invokes recovery
  3  ... and the hidden jam                 12  recovery passes the normal gates
  4  the projection drops the jam           13  CooperateOpen succeeds after recovery
  5  CooperateOpen is applicable first      14  advisory_two_track reaches GOAL_REACHED
  6  the environment rejects it physically  15  both agents reach the goal
  7  as an ExecutionDiscrepancy             16  the original discrepancies stay recorded
  8  of kind EXECUTION_FAILURE_OF_APPLICABLE_SKILL
  9  symbolic_primary halts                 17  rendering is optional; tests are headless
                                            18  BoxPush is unchanged

Offline and deterministic: no window, no network, no model. The backend (a PettingZoo
ParallelEnv with a MiniGrid-style renderer) is exercised headless; pygame is only imported
by the one test that draws an off-screen frame.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import pathlib
import subprocess
import sys
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.assembly import assemble_loop                          # noqa: E402
from app.validation import Status, validate_domain               # noqa: E402
from runtime.loop import EpisodeOutcome                          # noqa: E402
from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy   # noqa: E402
from shared.execution import ExecutionOutcome, ExecutionResult, FailureStateClass  # noqa: E402
from shared.orchestration_config import (                        # noqa: E402
    ExecutiveDecision,
    OrchestrationConfig,
    OrchestrationPolicy,
)
from shared.faults import InfrastructureFault                    # noqa: E402
from shared.skills import (                                      # noqa: E402
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)
from domains.cooperative_grid import DOMAIN, recover              # noqa: E402
from domains.cooperative_grid.environment import make_environment  # noqa: E402
from domains.cooperative_grid.model import MODEL                  # noqa: E402
from domains.cooperative_grid.types import (                      # noqa: E402
    DOOR,
    GOAL,
    HALL,
    HANDLE_LEFT,
    HANDLE_RIGHT,
    Call,
    Op,
)
from domains.registry import REGISTRY                             # noqa: E402

THRESHOLD = OrchestrationConfig().repeated_failure_threshold
COOPERATE = Call(Op.COOPERATE_OPEN, "A", DOOR, partner="B")
CLEAR_JAM = Call(Op.CLEAR_JAM, "A", DOOR)


def _run(policy: OrchestrationPolicy, **overrides):
    config = OrchestrationConfig(policy=policy)
    return assemble_loop(DOMAIN, config=config, **overrides).run()


def _executed(episode):
    return [e for e in episode.history.entries if e.execution is not None]


def _positioned_environment():
    """A fresh headless environment with both agents already on the handles."""
    env = make_environment()
    env.reset()
    for call in (Call(Op.GOTO, "A", HANDLE_LEFT), Call(Op.GOTO, "B", HANDLE_RIGHT)):
        result = env.execute_skill(call)
        if not isinstance(result, ExecutionResult) or result.outcome is not ExecutionOutcome.SUCCESS:
            raise AssertionError(f"positioning failed: {call} -> {result}")
    return env


class TestValidation(unittest.TestCase):
    def test_1_validate_domain_has_no_fail(self):
        report = validate_domain(DOMAIN)
        self.assertTrue(report.ok, report.render())
        self.assertEqual([f.code for f in report.findings if f.status is Status.FAIL], [])


class TestAuthoritativeStateAndProjection(unittest.TestCase):
    def test_2_the_authoritative_state_contains_two_agents(self):
        env = make_environment()
        state = env.reset()
        self.assertEqual(tuple(a.name for a in state.agents), ("A", "B"))
        self.assertEqual(len({a.cell for a in state.agents}), 2)
        self.assertEqual({"A", "B", DOOR, HANDLE_LEFT, HANDLE_RIGHT, GOAL}, set(state.identities()))

    def test_3_the_authoritative_state_contains_the_hidden_condition(self):
        state = make_environment().reset()
        self.assertTrue(state.door.jammed)
        self.assertFalse(state.door.is_open)
        self.assertIs(state.canonical()["door"]["jammed"], True)   # world content, not hidden

    def test_4_the_projection_does_not_contain_the_hidden_condition(self):
        state = make_environment().reset()
        sym = MODEL.project(state)
        text = json.dumps(sym.canonical())
        self.assertNotIn("jam", text.lower())
        self.assertNotIn('"x"', text)                                 # no coordinates either
        self.assertEqual(sym.canonical()["at"], {"A": HALL, "B": HALL})
        self.assertFalse(sym.door_open)
        # the projection of a jammed and an unjammed world is the same symbolic state
        free = make_environment(jammed_at_start=False).reset()
        self.assertEqual(MODEL.project(free).symbolic_key(), sym.symbolic_key())

    def test_the_jam_is_the_only_world_difference(self):
        jammed = make_environment().reset().canonical()
        free = make_environment(jammed_at_start=False).reset().canonical()
        jammed["door"]["jammed"] = False
        self.assertEqual(jammed, free)


class TestDesignedPhysicalFailure(unittest.TestCase):
    def test_5_the_cooperative_action_is_symbolically_applicable_before_the_failure(self):
        env = _positioned_environment()
        state = env.export_full_state()
        self.assertTrue(state.door.jammed)                           # the trap is armed
        verdict = MODEL.applicable(MODEL.project(state), COOPERATE)
        self.assertIsInstance(verdict, ValidatedCall)
        services = DOMAIN.services(DOMAIN.tasks[DOMAIN.default_task])
        self.assertIsInstance(services.evaluate(MODEL.project(state), COOPERATE), ValidatedCall)

    def test_6_the_environment_physically_rejects_the_applicable_action(self):
        env = _positioned_environment()
        result = env.execute_skill(COOPERATE)
        self.assertIsInstance(result, ExecutionResult)
        self.assertIs(result.outcome, ExecutionOutcome.FAILURE)
        self.assertIs(result.failure_class, FailureStateClass.UNCHANGED)
        self.assertFalse(result.post_state.door.is_open)
        self.assertTrue(result.post_state.same_world(result.pre_state))
        self.assertEqual(result.accounting.primitive_steps, 1)      # the pull was attempted

    def test_the_same_action_succeeds_when_the_hidden_condition_is_absent(self):
        env = make_environment(jammed_at_start=False)
        env.reset()
        for call in (Call(Op.GOTO, "A", HANDLE_LEFT), Call(Op.GOTO, "B", HANDLE_RIGHT)):
            env.execute_skill(call)
        result = env.execute_skill(COOPERATE)
        self.assertIsInstance(result, ExecutionResult)
        self.assertIs(result.outcome, ExecutionOutcome.SUCCESS)
        self.assertTrue(result.post_state.door.is_open)

    def test_7_8_the_failure_is_an_execution_discrepancy_of_the_expected_kind(self):
        episode = _run(OrchestrationPolicy.SYMBOLIC_PRIMARY)
        self.assertTrue(episode.discrepancies)
        for discrepancy in episode.discrepancies:
            self.assertIsInstance(discrepancy, ExecutionDiscrepancy)
            self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)
            self.assertEqual(discrepancy.call, COOPERATE)
        # evidence channels stay separate: no infrastructure fault anywhere in the history
        self.assertEqual([f for e in episode.history.entries for f in e.faults], [])
        self.assertEqual([d for e in episode.history.entries for d in e.divergences], [])


class TestSymbolicPrimary(unittest.TestCase):
    def test_9_10_halts_after_the_repeated_failure_threshold(self):
        episode = _run(OrchestrationPolicy.SYMBOLIC_PRIMARY)
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE, episode.reason)
        self.assertEqual(THRESHOLD, 3)                              # the frozen default
        self.assertEqual(len(episode.discrepancies), THRESHOLD)
        self.assertEqual(
            [str(e.selected_call) for e in _executed(episode)],
            ["Goto(A, handle_left)", "Goto(B, handle_right)"] + [str(COOPERATE)] * THRESHOLD,
        )
        decisions = [e.decision for e in episode.history.entries]
        self.assertEqual(decisions, [ExecutiveDecision.EXECUTE] * (2 + THRESHOLD)
                         + [ExecutiveDecision.HALT])
        self.assertIsNone(episode.history.entries[-1].execution)
        last = _executed(episode)[-1].execution
        self.assertFalse(last.post_state.door.is_open)
        self.assertTrue(last.post_state.door.jammed)               # never patched, never cleared


class TestAdvisoryTwoTrack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episode = _run(OrchestrationPolicy.ADVISORY_TWO_TRACK)
        cls.entries = cls.episode.history.entries

    def test_11_recovery_is_invoked_after_the_threshold(self):
        request = [e for e in self.entries if e.decision is ExecutiveDecision.REQUEST_PROPOSAL]
        self.assertEqual(len(request), 1)
        self.assertEqual(request[0].selected_call, COOPERATE)
        self.assertEqual(request[0].executive_step, 2 + THRESHOLD)
        following = self.entries[self.entries.index(request[0]) + 1]
        self.assertEqual(following.selected_call, CLEAR_JAM)
        self.assertEqual(recover(self.episode.discrepancies[-1]), (CLEAR_JAM,))
        other = dataclasses.replace(self.episode.discrepancies[-1], call=CLEAR_JAM)
        self.assertEqual(recover(other), ())                          # advice only for the pull

    def test_12_recovery_calls_pass_through_the_normal_execution_gates(self):
        advised = [e for e in self.entries if e.selected_call == CLEAR_JAM]
        self.assertEqual(len(advised), 1)
        entry = advised[0]
        self.assertIs(entry.decision, ExecutiveDecision.EXECUTE)
        self.assertEqual(entry.nl_proposal, CLEAR_JAM)               # enacted as ADVICE ...
        self.assertTrue(all(e.nl_proposal is None for e in self.entries if e is not entry))
        self.assertIsInstance(entry.validation, ValidatedCall)      # the applicability gate
        self.assertIsNotNone(entry.predicted_symbolic_key)           # the prediction gate
        self.assertIsNone(entry.predicted_world_key)                 # no apply_world declared:
        # the monitor compares the symbolic basis only; the physical effect is checked below
        self.assertIsNotNone(entry.execution)                        # the executor
        self.assertIs(entry.execution.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(entry.execution.accounting.executive_steps, 1)
        self.assertEqual(entry.execution.accounting.primitive_steps, 1)
        self.assertEqual(entry.discrepancies, ())                    # the monitor ran, cleanly
        self.assertFalse(entry.execution.post_state.door.jammed)     # the physical effect
        self.assertFalse(entry.execution.post_state.door.is_open)    # and only that

    def test_12b_ungrounded_advice_is_refused_by_the_grounding_gate(self):
        ghost = Call(Op.CLEAR_JAM, "C", DOOR)
        episode = _run(OrchestrationPolicy.ADVISORY_TWO_TRACK, recovery_provider=lambda d: (ghost,))
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("unknown identity C", episode.reason)
        self.assertNotIn(ghost, [e.selected_call for e in _executed(episode)])
        refused = episode.history.entries[-1]
        self.assertEqual(refused.selected_call, ghost)
        self.assertIsInstance(refused.validation, UngroundedCall)    # the grounding gate
        self.assertEqual([type(f) for f in refused.faults], [InfrastructureFault])
        self.assertEqual(refused.discrepancies, ())                  # a fault, not evidence
        self.assertIsNone(refused.execution)
        self.assertEqual(len(episode.discrepancies), THRESHOLD)

    def test_12c_inapplicable_advice_is_rejected_by_the_applicability_gate(self):
        early = Call(Op.GOTO, "A", GOAL)                             # the door is closed
        episode = _run(OrchestrationPolicy.ADVISORY_TWO_TRACK, recovery_provider=lambda d: (early,))
        self.assertNotIn(early, [e.selected_call for e in _executed(episode)])
        rejected = [e for e in episode.history.entries if e.selected_call == early]
        self.assertTrue(rejected)
        for entry in rejected:
            self.assertIsInstance(entry.validation, SymbolicallyInapplicable)
            self.assertIsNone(entry.execution)
            self.assertEqual(entry.discrepancies, ())
        # the loop keeps asking for advice, gets the same rejected call, and its liveness
        # guard ends the episode as a typed fault — never as progress
        self.assertIs(episode.outcome, EpisodeOutcome.FAULTED)
        self.assertIn("liveness guard", episode.reason)
        self.assertEqual(len(episode.discrepancies), THRESHOLD)

    def test_no_advice_halts_like_symbolic_primary(self):
        episode = _run(OrchestrationPolicy.ADVISORY_TWO_TRACK, recovery_provider=lambda d: ())
        self.assertIs(episode.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertEqual(len(episode.discrepancies), THRESHOLD)

    def test_13_the_cooperative_action_succeeds_after_recovery(self):
        calls = [e.selected_call for e in _executed(self.episode)]
        after = calls[calls.index(CLEAR_JAM) + 1:]
        self.assertEqual(after[0], COOPERATE)
        success = [e for e in _executed(self.episode)
                   if e.selected_call == COOPERATE and e.execution.outcome is ExecutionOutcome.SUCCESS]
        self.assertEqual(len(success), 1)
        self.assertTrue(success[0].execution.post_state.door.is_open)
        self.assertEqual(success[0].discrepancies, ())

    def test_14_reaches_goal(self):
        self.assertIs(self.episode.outcome, EpisodeOutcome.GOAL_REACHED, self.episode.reason)
        self.assertEqual(
            [str(e.selected_call) for e in _executed(self.episode)],
            ["Goto(A, handle_left)", "Goto(B, handle_right)"] + [str(COOPERATE)] * THRESHOLD
            + [str(CLEAR_JAM), str(COOPERATE), "Goto(A, goal)", "Goto(B, goal)"],
        )

    def test_15_both_agents_reach_the_goal(self):
        final = _executed(self.episode)[-1].execution.post_state
        task = DOMAIN.tasks[DOMAIN.default_task]
        self.assertTrue(task.is_satisfied_by(final))
        for agent in final.agents:
            self.assertEqual(final.place_of(agent.name), GOAL)
            self.assertIn(agent.cell, final.cells_of(GOAL))
        self.assertEqual(len({a.cell for a in final.agents}), 2)
        self.assertTrue(final.episode_over)                          # the backend terminated

    def test_16_the_original_discrepancies_remain_recorded(self):
        self.assertEqual(len(self.episode.discrepancies), THRESHOLD)
        for discrepancy in self.episode.discrepancies:
            self.assertIsInstance(discrepancy, ExecutionDiscrepancy)
            self.assertIs(discrepancy.kind, DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL)
            self.assertEqual(discrepancy.call, COOPERATE)
        failed = [e for e in self.entries if e.discrepancies]
        self.assertEqual([e.executive_step for e in failed], [2, 3, 4])
        self.assertEqual([f for e in self.entries for f in e.faults], [])

    def test_the_episode_is_deterministic(self):
        again = _run(OrchestrationPolicy.ADVISORY_TWO_TRACK)
        self.assertEqual(
            [(e.executive_step, e.decision, e.selected_call, e.post_state) for e in self.entries],
            [(e.executive_step, e.decision, e.selected_call, e.post_state)
             for e in again.history.entries],
        )


class TestRenderingIsOptional(unittest.TestCase):
    def test_17_headless_by_default(self):
        env = make_environment()
        env.reset()
        self.assertIsNone(env.render())                              # nothing to draw
        env.close()                                                  # nothing to release

    def test_17b_a_headless_episode_never_imports_pygame(self):
        code = (
            "import sys\n"
            "from app.assembly import assemble_loop\n"
            "from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy\n"
            "from domains.cooperative_grid import DOMAIN\n"
            "ep = assemble_loop(DOMAIN, config=OrchestrationConfig("
            "policy=OrchestrationPolicy.ADVISORY_TWO_TRACK)).run()\n"
            "print(ep.outcome.value, 'pygame' in sys.modules)\n"
        )
        out = subprocess.run([sys.executable, "-B", "-c", code], cwd=_REPO_ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["goal_reached", "False"])

    def test_17c_an_offscreen_frame_can_be_drawn_without_a_display(self):
        env = make_environment(render_mode="rgb_array")
        env.reset()
        frame = env.render()
        self.assertEqual(frame.ndim, 3)
        self.assertEqual(frame.shape[2], 3)
        self.assertEqual(frame.dtype.name, "uint8")
        # the frame changes when the world does (the jam wedge and the door)
        env.execute_skill(Call(Op.GOTO, "A", HANDLE_LEFT))
        self.assertFalse((env.render() == frame).all())

    def test_17d_the_demo_runs_headless(self):
        out = subprocess.run(
            [sys.executable, "-B", "-m", "functional_layer.custom_env.cooperative_grid.demo",
             "--headless", "--policy", "advisory_two_track"],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=True).stdout
        self.assertIn("outcome: goal_reached", out)
        self.assertIn("discrepancies recorded: 3", out)
        self.assertIn("ClearJam(A, door)", out)


class TestBackend(unittest.TestCase):
    def test_the_backend_satisfies_the_pettingzoo_parallel_api(self):
        from pettingzoo.test import parallel_api_test
        from functional_layer.custom_env.cooperative_grid.grid_env import CooperativeGridEnv
        with contextlib.redirect_stdout(io.StringIO()):
            parallel_api_test(CooperativeGridEnv(), num_cycles=30)

    def test_a_lone_pull_never_opens_the_door(self):
        from functional_layer.custom_env.cooperative_grid.grid_env import (
            NOOP, PULL, CooperativeGridEnv)
        env = CooperativeGridEnv(jammed_at_start=False)
        env.reset()
        for agent, place in (("A", "handle_left"), ("B", "handle_right")):
            for move in env.route(agent, (env.handle_cells[place],)):
                env.step({agent: move})
        env.step({"A": PULL, "B": NOOP})
        self.assertFalse(env.door_open)
        env.step({"A": PULL, "B": PULL})
        self.assertTrue(env.door_open)


class TestBoxPushIsUnchanged(unittest.TestCase):
    """A smoke check from the registry; the authority for "unchanged" is the existing suite
    (the R0 baseline-transcript tests) and an empty `git diff` over the frozen trees."""

    def test_18_box_push_still_validates_and_behaves_as_accepted(self):
        box_push = REGISTRY["box_push"]
        report = validate_domain(box_push)
        self.assertEqual([f.code for f in report.findings if f.status is Status.FAIL], [])
        primary = assemble_loop(box_push, config=OrchestrationConfig(
            policy=OrchestrationPolicy.SYMBOLIC_PRIMARY)).run()
        advisory = assemble_loop(box_push, config=OrchestrationConfig(
            policy=OrchestrationPolicy.ADVISORY_TWO_TRACK)).run()
        self.assertIs(primary.outcome, EpisodeOutcome.HALTED_REPEATED_FAILURE)
        self.assertIs(advisory.outcome, EpisodeOutcome.GOAL_REACHED)
        self.assertEqual(len(primary.discrepancies), 3)
        self.assertEqual(len(advisory.discrepancies), 3)

    def test_18b_the_new_domain_shares_no_module_with_box_push(self):
        code = (
            "import sys\n"
            "import domains.cooperative_grid\n"
            "from app.assembly import assemble_loop\n"
            "from domains.cooperative_grid import DOMAIN\n"
            "assemble_loop(DOMAIN).run()\n"
            "print(sorted(m for m in sys.modules if 'box_push' in m or m.startswith('domain.')"
            " or m.startswith('symbolic') or m.startswith('nl.')))\n"
        )
        out = subprocess.run([sys.executable, "-B", "-c", code], cwd=_REPO_ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "[]")


if __name__ == "__main__":
    unittest.main()
