"""V1 observation contract (supervisor :68, :285; section18.md §F)."""
import types
import unittest

import shared.observation as observation_module

from domain.box_push_v1 import initial_state
from shared.execution import ExecutionOutcome, RawLabel
from shared.observation import (
    V1_NOT_TRACK_VISIBLE,
    V1_VISIBILITY,
    ExecutiveObservation,
    ObservationChannel,
    Track,
    is_visible,
)


class TestVisibilityMatrix(unittest.TestCase):
    def test_symbolic_track_reads_exact_state(self):
        """:167 — symbolic state is exact/fully observable after wrapper normalization."""
        self.assertTrue(is_visible(Track.SYMBOLIC, ObservationChannel.EXACT_STATE))

    def test_neither_track_reads_the_partial_local_view(self):
        """The 3x3 egocentric view is preserved for later milestones, not consumed by V1."""
        for track in Track:
            with self.subTest(track=track):
                self.assertFalse(
                    is_visible(track, ObservationChannel.BACKEND_LOCAL_OBSERVATION)
                )

    def test_neither_track_reads_debug_channels(self):
        for track in Track:
            with self.subTest(track=track):
                self.assertFalse(is_visible(track, ObservationChannel.DEBUG_FULL))

    def test_nl_track_reads_typed_state_not_the_belief_grid(self):
        """:169 — V1 NL input is text/typed data only. A NL track reading the belief grid would
        inherit the defects Decision 9 deferred."""
        self.assertTrue(is_visible(Track.NL, ObservationChannel.EXACT_STATE))
        self.assertNotIn(
            ObservationChannel.BACKEND_LOCAL_OBSERVATION, V1_VISIBILITY[Track.NL]
        )

    def test_both_tracks_see_the_public_execution_result(self):
        for track in Track:
            with self.subTest(track=track):
                self.assertTrue(
                    is_visible(track, ObservationChannel.PUBLIC_EXECUTION_RESULT)
                )

    def test_visibility_partitions_the_channel_set(self):
        visible = set().union(*V1_VISIBILITY.values())
        self.assertEqual(visible | set(V1_NOT_TRACK_VISIBLE), set(ObservationChannel))
        self.assertEqual(visible & set(V1_NOT_TRACK_VISIBLE), set())

    def test_every_track_has_an_explicit_entry(self):
        self.assertEqual(set(V1_VISIBILITY), set(Track))


class TestExecutiveObservation(unittest.TestCase):
    def test_carries_typed_outcome_and_exact_state(self):
        obs = ExecutiveObservation(
            outcome=ExecutionOutcome.SUCCESS, state=initial_state(), primitive_steps=7
        )
        self.assertIs(obs.outcome, ExecutionOutcome.SUCCESS)
        self.assertEqual(obs.canonical()["state"], initial_state().world_key())

    def test_does_not_expose_reward_or_local_view(self):
        """The reward channel is multiplexed and provably corruptible as a state signal.

        Substring matching, not set membership: `env_reward` would sail past an exact-name check.
        """
        fields = [f.lower() for f in ExecutiveObservation.__slots__]
        for forbidden in ("reward", "image", "belief", "grid", "obs", "view", "local"):
            for field in fields:
                with self.subTest(field=field, token=forbidden):
                    self.assertNotIn(forbidden, field)

    def test_raw_label_is_provenance_only_and_optional(self):
        plain = ExecutiveObservation(outcome=ExecutionOutcome.TIMEOUT, state=initial_state())
        self.assertIsNone(plain.raw_label)
        stamped = ExecutiveObservation(
            outcome=ExecutionOutcome.TIMEOUT,
            state=initial_state(),
            raw_label=RawLabel.PUSHED,
        )
        self.assertIs(stamped.outcome, ExecutionOutcome.TIMEOUT)
        self.assertIs(stamped.raw_label, RawLabel.PUSHED)

    def test_negative_primitive_steps_rejected(self):
        with self.assertRaises(ValueError):
            ExecutiveObservation(
                outcome=ExecutionOutcome.SUCCESS, state=initial_state(), primitive_steps=-1
            )


class TestObservationContractIsExported(unittest.TestCase):
    """`shared/__init__.py` states that every exported name is part of the frozen contract, and
    `section18.md` lists `observation.py` as a P0 contract module — but none of its names were
    exported, and nothing noticed."""

    NAMES = (
        "ObservationChannel", "Track", "V1_VISIBILITY", "V1_NOT_TRACK_VISIBLE",
        "is_visible", "ExecutiveObservation",
    )

    def test_the_whole_observation_surface_is_exported(self):
        import shared
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertIn(name, shared.__all__)
                self.assertIs(getattr(shared, name), getattr(observation_module, name))

    def test_no_public_observation_name_is_left_unexported(self):
        """Derived from the module, so a NEW public name must be exported or explicitly excluded."""
        import shared
        public = {
            name for name, value in vars(observation_module).items()
            if not name.startswith("_")
            and getattr(value, "__module__", "shared.observation") == "shared.observation"
        }
        self.assertTrue(public)
        self.assertEqual(public - set(shared.__all__), set())


class TestTheWholeContractSurfaceIsExported(unittest.TestCase):
    """`shared/__init__.py` states that every exported name is part of the frozen contract (:82).
    Completeness was previously enforced for `observation.py` alone, so several frozen names in
    sibling modules were unexported while the claim stood."""

    #: Deliberately module-local, with a reason each. Everything else must be exported.
    NOT_EXPORTED = {
        # Lifted planning type tags. They ARE part of the frozen contract (`DomainIR.canonical()`
        # puts them in the digest, and `domain/box_push_v1.py` imports them), but layers bind to
        # them via `shared.skill_ir` where they are declared — not via the top-level re-export.
        "TYPE_UNIVERSE", "TYPE_AGENT", "TYPE_BOX", "TYPE_ZONE",
    }

    def _public_names(self):
        import importlib, pkgutil
        import shared as package
        found = {}
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"shared.{info.name}")
            for name, value in vars(module).items():
                if name.startswith("_") or isinstance(value, types.ModuleType):
                    continue          # imported stdlib modules are not contract names
                if getattr(value, "__module__", f"shared.{info.name}") != f"shared.{info.name}":
                    continue          # re-export from another shared module; counted at its source
                found.setdefault(name, f"shared.{info.name}")
        return found

    def test_every_public_contract_name_is_exported_or_explicitly_excluded(self):
        import shared
        missing = {
            name: where for name, where in self._public_names().items()
            if name not in shared.__all__ and name not in self.NOT_EXPORTED
        }
        self.assertEqual(
            missing, {},
            "these frozen-contract names are not in shared.__all__:\n"
            + "\n".join(f"  {n}  ({w})" for n, w in sorted(missing.items())),
        )

    def test_the_exclusion_list_has_no_stale_entries(self):
        """An excluded name that no longer exists hides a real gap behind a dead exemption."""
        self.assertEqual(self.NOT_EXPORTED - set(self._public_names()), set())

    def test_every_exported_name_resolves(self):
        import shared
        self.assertEqual([n for n in shared.__all__ if not hasattr(shared, n)], [])


class TestChannelDocumentationMatchesTheEnum(unittest.TestCase):
    def test_the_docstring_channel_count_matches_the_enum(self):
        """The docstring said "Three channels:" and then listed four."""
        words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}
        expected = words[len(ObservationChannel)]
        self.assertIn(f"{expected} channels:", observation_module.__doc__ or "")

    def test_every_enum_member_is_described_in_the_docstring(self):
        doc = observation_module.__doc__ or ""
        for channel in ObservationChannel:
            with self.subTest(channel=channel):
                self.assertIn(channel.name, doc)


if __name__ == "__main__":
    unittest.main()
