"""R1 contract tests: the narrow typed contracts exist, are domain-neutral, immutable,
validated, and satisfied by the shipped components (report Phase 1).

The static half of the acceptance ("existing components satisfy the protocols under static
checking") lives in `tests/contract_conformance.py`, checked with mypy. Here the same
witnesses are exercised at runtime, and the phase's structural acceptance criteria are made
mechanical:

- no contract name/field/parameter uses BoxPush vocabulary;
- no speculative belief/probability/temporal surface;
- `shared.contracts` imports only stdlib + `shared` (dependency direction);
- contexts are immutable and validated;
- illegal decision states are unrepresentable (Execute without a call, etc.).

Offline and deterministic: the only environment touched is the local adapter, reset once.
"""
import ast
import dataclasses
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
    Environment,
    Execute,
    Halt,
    OrchestrationContext,
    OrchestrationPolicyContract,
    PreliminaryContext,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    Replan,
    RequestProposal,
    SymbolicTrack,
    TrackRequest,
)
from shared.ids import AgentId, BoxId, ZoneId
from shared.orchestration_config import ExecutiveDecision
from shared.planner_result import NoPlan
from shared.skills import GroundedSkillCall, SkillName

from tests import contract_conformance

_CONTRACTS_DIR = pathlib.Path(_REPO_ROOT) / "shared" / "contracts"

_CALL = GroundedSkillCall(
    SkillName.PUSH, (AgentId("agent_0"),), BoxId(1), ZoneId("delivery_zone")
)
_NOPLAN = NoPlan(reason="contract-test fixture")


class _SilentSeam:
    """LMSeam witness for constructing an NLTrack; never actually consulted here."""

    def complete(self, request):
        raise AssertionError("contract tests must not consult the seam")


def _snapshot():
    from domain.box_push_v1 import initial_state
    return initial_state()


class TestShippedComponentsSatisfyTheProtocols(unittest.TestCase):
    """Runtime half of the conformance witnesses (static half: contract_conformance.py)."""

    def test_the_adapter_satisfies_the_generic_environment_contract(self):
        from box_push_v1_adapter import BoxPushV1Adapter
        adapter = BoxPushV1Adapter()
        self.assertIsInstance(adapter, Environment)
        self.assertIs(contract_conformance.environment_conforms(adapter), adapter)

    def test_the_exact_belief_satisfies_the_symbolic_track_contract(self):
        from domain.box_push_v1 import DOMAIN_IR, PROJECTION, project
        from symbolic import ExactSymbolicBelief
        belief = ExactSymbolicBelief(DOMAIN_IR, PROJECTION, project)
        # frozen Python 3.12 (Decision 10): protocol isinstance uses getattr_static, so the
        # unsynced belief's raising `state` property is inspected, not invoked
        self.assertIsInstance(belief, SymbolicTrack)
        self.assertIs(contract_conformance.symbolic_track_conforms(belief), belief)

    def test_the_nl_track_satisfies_the_reasoning_track_contract(self):
        from nl.track import NLTrack
        track = NLTrack(_SilentSeam())
        self.assertIsInstance(track, ReasoningTrack)
        self.assertIs(contract_conformance.reasoning_track_conforms(track), track)

    def test_the_comparator_and_recovery_functions_satisfy_their_contracts(self):
        # R3 restructured the comparator seam: the report-shaped ProposalComparator is
        # satisfied by the scoped BoxPushActionComparator instance (the legacy
        # compare_tracks function remains only as a divergence-tuple wrapper over it).
        from nl.recovery import propose_recovery
        from app.comparator import DEFAULT_COMPARATOR
        self.assertIsInstance(DEFAULT_COMPARATOR, ProposalComparator)
        self.assertIsInstance(propose_recovery, RecoveryProvider)
        self.assertIs(contract_conformance.comparator_conforms, DEFAULT_COMPARATOR)
        self.assertIs(contract_conformance.recovery_conforms, propose_recovery)

    def test_the_policy_contract_is_implementable_and_pure_shaped(self):
        policy = contract_conformance.MinimalHaltPolicy()
        self.assertIsInstance(policy, OrchestrationPolicyContract)
        preliminary = PreliminaryContext(state=_snapshot(), planner_result=_NOPLAN)
        request = policy.required_inputs(preliminary)
        self.assertIsInstance(request, TrackRequest)
        self.assertFalse(request.nl_proposal)
        decision = policy.decide(OrchestrationContext(preliminary=preliminary))
        self.assertIsInstance(decision, Halt)
        self.assertIs(decision.decision, ExecutiveDecision.HALT)


class TestContextsAreImmutableAndValidated(unittest.TestCase):
    def test_preliminary_context_is_frozen(self):
        context = PreliminaryContext(state=_snapshot(), planner_result=_NOPLAN)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            context.failure_count = 1

    def test_preliminary_context_rejects_negative_failure_count(self):
        with self.assertRaises(ValueError):
            PreliminaryContext(
                state=_snapshot(), planner_result=_NOPLAN, failure_count=-1
            )

    def test_orchestration_context_is_frozen_with_empty_default_evidence(self):
        context = OrchestrationContext(
            preliminary=PreliminaryContext(state=_snapshot(), planner_result=_NOPLAN)
        )
        self.assertIsNone(context.nl_proposal)
        # R3: absence of a comparison is None (no proposal was compared), never a
        # manufactured empty report
        self.assertIsNone(context.comparison)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            context.nl_proposal = object()

    def test_track_request_is_frozen(self):
        request = TrackRequest(nl_proposal=True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.nl_proposal = False


class TestTypedDecisionVariantsMakeIllegalStatesUnrepresentable(unittest.TestCase):
    def test_execute_cannot_exist_without_an_executable_call(self):
        with self.assertRaises(ValueError):
            Execute(call=None)
        self.assertIs(Execute(call=_CALL).call, _CALL)

    def test_request_proposal_cannot_exist_without_its_call(self):
        with self.assertRaises(ValueError):
            RequestProposal(call=None)

    def test_halt_and_replan_require_reasons(self):
        with self.assertRaises(ValueError):
            Halt(reason="")
        with self.assertRaises(ValueError):
            Replan(reason="")
        self.assertIsNone(Halt(reason="done").call)

    def test_each_variant_carries_its_frozen_trace_decision(self):
        self.assertIs(Execute(call=_CALL).decision, ExecutiveDecision.EXECUTE)
        self.assertIs(Replan(reason="r").decision, ExecutiveDecision.REPLAN)
        self.assertIs(
            RequestProposal(call=_CALL).decision, ExecutiveDecision.REQUEST_PROPOSAL
        )
        self.assertIs(Halt(reason="r").decision, ExecutiveDecision.HALT)

    def test_variants_are_frozen(self):
        decision = Execute(call=_CALL)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.call = None


class TestContractSourceDiscipline(unittest.TestCase):
    """Mechanical acceptance: no BoxPush vocabulary, no speculative surface, and the
    dependency direction (contracts import only stdlib + shared)."""

    _BOXPUSH_TOKENS = (
        "box", "boxes", "agent", "agents", "zone", "zones", "grid", "push",
        "deliver", "delivered", "delivery", "pose",
    )
    _SPECULATIVE_TOKENS = (
        "belief", "probab", "stochastic", "temporal", "duration", "async", "concurrent",
    )
    # enum joined at R3: ComparedAspect/FindingSeverity are StrEnums, still stdlib-only
    _ALLOWED_IMPORT_ROOTS = {"__future__", "typing", "dataclasses", "enum", "shared"}

    def _contract_sources(self):
        files = sorted(_CONTRACTS_DIR.glob("*.py"))
        self.assertGreaterEqual(len(files), 5, "contracts package unexpectedly small")
        for path in files:
            yield path, ast.parse(path.read_text(encoding="utf-8"))

    def _defined_names(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node.name
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args
                    for arg in (args.posonlyargs + args.args + args.kwonlyargs):
                        yield arg.arg
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                yield node.target.id
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        yield target.id

    @staticmethod
    def _segments(name):
        """snake_case and CamelCase segments of an identifier, lowercased — whole-word
        matching, so `propose` does not trip on `pose`."""
        import re
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
        return [s for s in re.split(r"[_\d]+", spaced.lower()) if s]

    def test_no_boxpush_vocabulary_in_contract_names(self):
        for path, tree in self._contract_sources():
            for name in self._defined_names(tree):
                for segment in self._segments(name):
                    self.assertNotIn(
                        segment, self._BOXPUSH_TOKENS,
                        f"{path.name}: contract name {name!r} carries BoxPush "
                        f"vocabulary {segment!r}",
                    )

    def test_no_speculative_semantic_surface_in_contract_names(self):
        for path, tree in self._contract_sources():
            for name in self._defined_names(tree):
                for segment in self._segments(name):
                    for token in self._SPECULATIVE_TOKENS:
                        self.assertFalse(
                            segment.startswith(token),
                            f"{path.name}: contract name {name!r} suggests speculative "
                            f"semantics {token!r}",
                        )

    def test_contracts_import_only_stdlib_and_shared(self):
        for path, tree in self._contract_sources():
            for node in ast.walk(tree):
                roots = []
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = [node.module.split(".")[0]]
                for root in roots:
                    self.assertIn(
                        root, self._ALLOWED_IMPORT_ROOTS,
                        f"{path.name} imports {root!r} — contracts may depend only on "
                        f"stdlib typing machinery and shared",
                    )


if __name__ == "__main__":
    unittest.main()
