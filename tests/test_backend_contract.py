"""The frozen V1 environment interface (supervisor :185, :192-198).

P0 freezes the interface only; P1 implements it. These tests pin the method set and — more
importantly — pin what the interface must NOT offer, since the contract's own docstring claims it
exposes no feasibility query and that claim was previously untested.
"""
import inspect
import unittest

from shared.backend_contract import V1Environment
from shared.execution import ExecutionResult
from shared.skills import MalformedCall, SymbolicallyInapplicable, UngroundedCall
from shared.state_snapshot import StateSnapshot

REQUIRED_METHODS = ("reset", "observe", "export_full_state", "execute_skill", "is_terminal", "render")


class _Conforming:
    def reset(self, *, seed=None): ...
    def observe(self): ...
    def export_full_state(self): ...
    def execute_skill(self, call): ...
    def is_terminal(self): ...
    def render(self): ...


class _MissingExport:
    def reset(self, *, seed=None): ...
    def observe(self): ...
    def execute_skill(self, call): ...
    def is_terminal(self): ...
    def render(self): ...


class TestFrozenMethodSet(unittest.TestCase):
    def test_protocol_declares_exactly_the_frozen_methods(self):
        declared = {
            name for name, _ in inspect.getmembers(V1Environment, inspect.isfunction)
            if not name.startswith("_")
        }
        self.assertEqual(declared, set(REQUIRED_METHODS))

    def test_a_conforming_implementation_satisfies_the_protocol(self):
        self.assertIsInstance(_Conforming(), V1Environment)

    def test_an_implementation_missing_export_full_state_is_rejected(self):
        """`export_full_state` is the Decision 4 seam — the whole point of the interface."""
        self.assertNotIsInstance(_MissingExport(), V1Environment)


class TestInterfaceExposesNoOracle(unittest.TestCase):
    """Decision 6 / :55. Symbolic applicability must not be able to ask the backend whether
    something will work, so the surface must offer nothing to ask with."""

    FORBIDDEN_TOKENS = (
        "reach", "path", "bfs", "feasib", "occupan", "collision", "navig",
        "free", "adjacent", "distance", "can_", "route", "los", "connected",
    )

    @staticmethod
    def _declared_methods():
        """From the protocol itself. Scanning `REQUIRED_METHODS` only re-checked the fixture."""
        return {
            name for name, _ in inspect.getmembers(V1Environment, inspect.isfunction)
            if not name.startswith("_")
        }

    def test_no_method_name_suggests_a_feasibility_query(self):
        for name in self._declared_methods():
            lowered = name.lower()
            for token in self.FORBIDDEN_TOKENS:
                with self.subTest(method=name, token=token):
                    self.assertNotIn(token, lowered)

    def test_state_and_execution_are_the_only_information_channels(self):
        """Everything the executive learns comes from a snapshot or an execution result — never
        from a predictive query. Compared against the PROTOCOL, not against `REQUIRED_METHODS`;
        the old form compared the test constant to a copy of itself."""
        self.assertEqual(
            self._declared_methods(),
            {"reset", "observe", "export_full_state", "execute_skill", "is_terminal", "render"},
        )


class TestExecuteSkillReturnType(unittest.TestCase):
    """The environment surface must not admit a SYMBOLIC verdict."""

    def _return_annotation(self):
        return inspect.signature(V1Environment.execute_skill).return_annotation

    def test_returns_execution_result_or_an_infrastructure_rejection(self):
        text = str(self._return_annotation())
        for expected in ("ExecutionResult", "MalformedCall", "UngroundedCall"):
            with self.subTest(kind=expected):
                self.assertIn(expected, text)

    def test_symbolically_inapplicable_is_not_on_the_environment_surface(self):
        """Admitting it would invite the wrapper — which sits on the geometry-bearing backend — to
        evaluate symbolic preconditions."""
        self.assertNotIn("SymbolicallyInapplicable", str(self._return_annotation()))

    def test_export_full_state_returns_the_canonical_snapshot(self):
        # `from __future__ import annotations` keeps annotations as strings.
        self.assertEqual(
            str(inspect.signature(V1Environment.export_full_state).return_annotation),
            StateSnapshot.__name__,
        )

    def test_reset_returns_the_canonical_snapshot(self):
        self.assertEqual(
            str(inspect.signature(V1Environment.reset).return_annotation), StateSnapshot.__name__
        )


class TestObligationsAreDocumented(unittest.TestCase):
    """The interface carries obligations P1 must satisfy; they are part of the freeze."""

    def test_docstring_pins_the_decisions_p1_must_honour(self):
        import shared.backend_contract as module
        text = module.__doc__ or ""
        # Word-boundary, not substring: "D1" is satisfied by "D14" and "D3" by "D13", so the
        # plain `assertIn` passed even for obligations that were never documented.
        for obligation in ("D1", "D2", "D3", "D4", "D7", "D8", "D14", "D16"):
            with self.subTest(obligation=obligation):
                self.assertRegex(text, rf"\b{obligation}\b")

    def test_reset_documents_the_reset_before_use_hazard(self):
        """`assertIn("reset", ...)` on a method named `reset` is satisfied by accident. The hazard
        is specific: `world.agents` changes type during reset, so stepping first raises."""
        doc = (V1Environment.reset.__doc__ or "").lower()
        self.assertIn("must be called before any other method", doc)
        self.assertIn("world.agents", doc)


class TestAdapterArgumentTranslationIsFrozen(unittest.TestCase):
    """Decision 16. The legacy factory's single `arg` means three different things; the obligation
    is that the adapter never touches it."""

    def _text(self):
        import shared.backend_contract as module
        return module.__doc__ or ""

    def test_the_factory_is_explicitly_out_of_bounds(self):
        self.assertIn("never calls", self._text())
        self.assertIn("make_skill", self._text())

    def test_each_skill_names_its_own_backend_construction(self):
        text = self._text()
        for construction in (
            "GotoPushPoseSkill(agent_id, box=",
            "CooperativePushSkill(agent_id, partner_id, box=",
            "PushSkill(agent_id, dest=None)",
        ):
            with self.subTest(construction=construction):
                self.assertIn(construction, text)

    def test_the_silent_regrounding_fallback_is_named(self):
        """`_resolve_box` falling back to `_nearest_undelivered_target` is the exact hole; naming
        it is what makes the obligation checkable in review."""
        text = self._text()
        self.assertIn("_nearest_undelivered_target", text)
        self.assertIn("_resolve_box", text)

    def test_cells_are_derived_not_supplied(self):
        self.assertIn("never taken from a caller-supplied tuple", self._text())

    def test_the_legacy_overload_still_exists_so_the_obligation_still_applies(self):
        """If the backend ever un-overloads `arg`, this fails and Decision 16 should be re-read."""
        import pathlib as _p
        factory = (
            _p.Path(__file__).resolve().parents[1]
            / "functional_layer/custom_env/box_push/env/skill_executor_push.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "the box cell for goto_push_pose/cooperate_push,\n    the destination cell for push",
            factory,
        )
        self.assertIn("return GotoPushPoseSkill(agent_id, arg)", factory)
        self.assertIn("return PushSkill(agent_id, arg)", factory)


if __name__ == "__main__":
    unittest.main()
