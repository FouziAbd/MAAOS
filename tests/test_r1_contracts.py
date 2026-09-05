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
        """Every identifier a contract source DEFINES or BINDS — class/function names, all
        parameter names (positional, keyword-only, `*args`, `**kwargs`, lambda parameters —
        R6 hardening of the R1 scan), assignment targets, every name that appears inside an
        annotation expression, and every name imported from `shared` (the allowlist admits
        `shared` wholesale, so a BoxPush-typed import such as `BoxId` must trip HERE)."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node.name
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                args = node.args
                for arg in (args.posonlyargs + args.args + args.kwonlyargs):
                    yield arg.arg
                    if arg.annotation is not None:
                        yield from self._annotation_names(arg.annotation)
                for extra in (args.vararg, args.kwarg):
                    if extra is not None:
                        yield extra.arg
                        if extra.annotation is not None:
                            yield from self._annotation_names(extra.annotation)
                returns = getattr(node, "returns", None)
                if returns is not None:
                    yield from self._annotation_names(returns)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    yield node.target.id
                yield from self._annotation_names(node.annotation)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        yield target.id
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    yield alias.name                      # the imported object's name ...
                    if alias.asname:
                        yield alias.asname                # ... and the local binding

    @staticmethod
    def _annotation_names(annotation):
        """Identifiers inside an annotation expression, including string annotations."""
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Name):
                yield sub.id
            elif isinstance(sub, ast.Attribute):
                yield sub.attr

    @staticmethod
    def _segments(name):
        """snake_case and CamelCase segments of an identifier, lowercased — whole-word
        matching, so `propose` does not trip on `pose`."""
        import re
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
        return [s for s in re.split(r"[_\d]+", spaced.lower()) if s]

    #: R6 hardening: morphological variants trip too (`pushed`, `boxed`, `zoned`, ...) —
    #: a segment that STARTS with one of these stems is BoxPush vocabulary. `pose` is kept
    #: whole-word above (`proposal`/`propose` are legitimate contract words).
    _BOXPUSH_STEMS = ("box", "agent", "zone", "grid", "push", "deliver")

    def _carries_boxpush_vocabulary(self, name):
        for segment in self._segments(name):
            if segment in self._BOXPUSH_TOKENS:
                return segment
            for stem in self._BOXPUSH_STEMS:
                if segment.startswith(stem):
                    return segment
        return None

    def test_no_boxpush_vocabulary_in_contract_names(self):
        for path, tree in self._contract_sources():
            for name in self._defined_names(tree):
                segment = self._carries_boxpush_vocabulary(name)
                self.assertIsNone(
                    segment,
                    f"{path.name}: contract name {name!r} carries BoxPush "
                    f"vocabulary {segment!r}",
                )

    def test_the_vocabulary_scan_sees_every_binding_site(self):
        """R6 hardening, non-vacuous: each binding site the R1 scan missed is now caught —
        `*args`/`**kwargs`, lambda parameters, annotation expressions (including string
        annotations), and names imported from `shared`; and a morphological variant trips."""
        probes = {
            "vararg": "def f(*boxes): ...",
            "kwarg": "def f(**agents): ...",
            "lambda": "g = lambda zone: zone",
            "param annotation": "def f(x: BoxId) -> None: ...",
            "return annotation": "def f() -> 'Optional[AgentId]': ...",
            "attribute annotation": "x: shared.ids.BoxId",
            "shared import": "from shared.ids import BoxId as _B",
            "morphology": "def f(pushed_call): ...",
        }
        for label, source in probes.items():
            with self.subTest(site=label):
                names = list(self._defined_names(ast.parse(source)))
                self.assertTrue(
                    any(self._carries_boxpush_vocabulary(n) for n in names),
                    f"{label}: scan saw {names}, none flagged",
                )
        # and the legitimate contract words still pass
        for clean in ("proposal", "propose", "PreliminaryContext", "RequestProposal",
                      "symbolic_call", "CallT_contra", "StateT"):
            with self.subTest(clean=clean):
                self.assertIsNone(self._carries_boxpush_vocabulary(clean))

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
