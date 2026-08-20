"""Frozen skill signatures, grounded calls, and cross-layer signature identity.

Covers P0_V1_DECISIONS Decision 11 and the project testing rule's requirement that every grounded
executive skill has aligned argument types across registry / model / backend.
"""
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    DOMAIN_IR,
)
from shared.ids import AgentId, BoxId, ZoneId, canonical_agent_pair
from shared.skills import (
    REGISTRY,
    GroundedSkillCall,
    MalformedCall,
    ParameterType,
    SkillName,
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)


class TestFrozenSignatures(unittest.TestCase):
    EXPECTED = {
        SkillName.GOTO_PUSH_POSE: (ParameterType.AGENT, ParameterType.BOX, ParameterType.ZONE),
        SkillName.PUSH: (ParameterType.AGENT, ParameterType.BOX, ParameterType.ZONE),
        SkillName.COOPERATIVE_PUSH: (ParameterType.AGENT_PAIR, ParameterType.BOX, ParameterType.ZONE),
        SkillName.EXPLORE: (ParameterType.AGENT,),
        SkillName.WAIT: (ParameterType.AGENT,),
    }

    def test_registry_holds_exactly_the_frozen_vocabulary(self):
        self.assertEqual(set(REGISTRY.names()), set(self.EXPECTED))

    def test_parameter_types_are_frozen(self):
        for name, types in self.EXPECTED.items():
            with self.subTest(skill=name):
                self.assertEqual(REGISTRY.get(name).parameter_types, types)

    def test_default_cost_is_one(self):
        for sig in REGISTRY:
            with self.subTest(skill=sig.name):
                self.assertEqual(sig.cost, 1)

    def test_every_skill_maps_to_a_backend_implementation(self):
        for sig in REGISTRY:
            with self.subTest(skill=sig.name):
                self.assertIn(".", sig.backend_mapping)   # module.Class, not a bare truthy string
                self.assertTrue(sig.backend_mapping)

    def test_symbolic_action_set_excludes_explore_and_wait(self):
        """Decision 5: full observability makes Explore symbolically inert; it stays in the
        registry as a backend/NL-track skill so the registry is a superset."""
        symbolic = set(REGISTRY.symbolic_action_set())
        self.assertNotIn(SkillName.EXPLORE, symbolic)
        self.assertNotIn(SkillName.WAIT, symbolic)
        self.assertEqual(
            symbolic,
            {SkillName.GOTO_PUSH_POSE, SkillName.PUSH, SkillName.COOPERATIVE_PUSH},
        )

    def test_registry_is_a_superset_of_the_symbolic_action_set(self):
        self.assertTrue(set(DOMAIN_IR.action_set()).issubset(set(REGISTRY.names())))


class TestCrossLayerIdentity(unittest.TestCase):
    """Registry signature, IR parameters and grounded call must agree, for every symbolic skill."""

    def test_ir_parameter_count_matches_expanded_signature_arity(self):
        for skill in DOMAIN_IR.skills:
            with self.subTest(skill=skill.name):
                self.assertEqual(len(skill.parameters), skill.signature.expanded_arity)

    def test_agent_pair_expands_to_exactly_two_planning_variables(self):
        coop = DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH)
        self.assertEqual(coop.signature.arity, 3)          # call-facing: agents, box, zone
        self.assertEqual(coop.signature.expanded_arity, 4)  # lifted: agent1, agent2, box, zone
        self.assertEqual(coop.parameters, ("agent1", "agent2", "box", "zone"))

    def test_binding_a_call_covers_every_ir_parameter(self):
        calls = {
            SkillName.GOTO_PUSH_POSE: GroundedSkillCall(
                SkillName.GOTO_PUSH_POSE, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE
            ),
            SkillName.PUSH: GroundedSkillCall(
                SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE
            ),
            SkillName.COOPERATIVE_PUSH: GroundedSkillCall(
                SkillName.COOPERATIVE_PUSH, (AGENT_1, AGENT_0), BOX_HEAVY, DELIVERY_ZONE
            ),
        }
        for name, call in calls.items():
            with self.subTest(skill=name):
                binding = DOMAIN_IR.skill(name).bind(call)
                self.assertEqual(set(binding), set(DOMAIN_IR.skill(name).parameters))

    def test_binding_rejects_a_call_for_a_different_skill(self):
        push_call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        with self.assertRaises(ValueError):
            DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE).bind(push_call)


class TestGroundedCallValidation(unittest.TestCase):
    def test_missing_box_argument_rejected(self):
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.PUSH, (AGENT_0,), None, DELIVERY_ZONE)

    def test_missing_zone_argument_rejected(self):
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, None)

    def test_extra_argument_rejected(self):
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.WAIT, (AGENT_0,), BOX_LIGHT, None)

    def test_wrong_agent_count_rejected(self):
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.PUSH, (AGENT_0, AGENT_1), BOX_LIGHT, DELIVERY_ZONE)
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.COOPERATIVE_PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)

    def test_cooperative_push_requires_distinct_agents(self):
        with self.assertRaises(ValueError):
            GroundedSkillCall(SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_0), BOX_HEAVY, DELIVERY_ZONE)


class TestCanonicalCallKey(unittest.TestCase):
    """The grounded-call key is half of the repeated-failure key (:118), so it must be
    order-independent and stable."""

    def test_agent_pair_is_canonically_ordered(self):
        a = GroundedSkillCall(SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE)
        b = GroundedSkillCall(SkillName.COOPERATIVE_PUSH, (AGENT_1, AGENT_0), BOX_HEAVY, DELIVERY_ZONE)
        self.assertEqual(a.agents, b.agents)
        self.assertEqual(a.key(), b.key())
        self.assertEqual(a, b)

    def test_canonical_agent_pair_helper_orders_and_rejects_duplicates(self):
        self.assertEqual(canonical_agent_pair(AGENT_1, AGENT_0), (AGENT_0, AGENT_1))
        with self.assertRaises(ValueError):
            canonical_agent_pair(AGENT_0, AGENT_0)

    def test_key_is_stable_and_round_trips(self):
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        self.assertEqual(call.key(), call.key())
        self.assertEqual(GroundedSkillCall.from_dict(call.canonical()), call)

    def test_different_boxes_produce_different_keys(self):
        a = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        b = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_HEAVY, DELIVERY_ZONE)
        self.assertNotEqual(a.key(), b.key())

    def test_a_raw_string_agent_is_rejected(self):
        """`.claude/rules/testing.md`'s FIRST required property is aligned argument types across
        registry/model/backend. `GroundedSkillCall.__post_init__` enforces it — but deleting the
        guard used to leave the whole suite green, because every existing test built a correct call
        and then asserted `isinstance` on it."""
        with self.assertRaises(TypeError):
            GroundedSkillCall(SkillName.PUSH, ("agent_0",), BoxId(1), ZoneId("delivery_zone"))

    def test_a_raw_int_box_is_rejected(self):
        with self.assertRaises(TypeError):
            GroundedSkillCall(SkillName.PUSH, (AgentId("agent_0"),), 1, ZoneId("delivery_zone"))

    def test_a_raw_string_zone_is_rejected(self):
        with self.assertRaises(TypeError):
            GroundedSkillCall(SkillName.PUSH, (AgentId("agent_0"),), BoxId(1), "delivery_zone")

    def test_a_mixed_agent_pair_is_rejected(self):
        with self.assertRaises(TypeError):
            GroundedSkillCall(
                SkillName.COOPERATIVE_PUSH, (AgentId("agent_0"), "agent_1"),
                BoxId(0), ZoneId("delivery_zone"),
            )

    def test_arguments_are_identities_not_cells(self):
        """Decision 11: a stale coordinate is indistinguishable from a valid one, which is how
        the backend's silent re-grounding hides. Identities make it detectable."""
        call = GroundedSkillCall(SkillName.PUSH, (AGENT_0,), BOX_LIGHT, DELIVERY_ZONE)
        self.assertIsInstance(call.box, BoxId)
        self.assertIsInstance(call.zone, ZoneId)
        self.assertIsInstance(call.agents[0], AgentId)


class TestRejectionTypes(unittest.TestCase):
    """Decision 7: rejection kinds are distinct types so they cannot be conflated."""

    def test_accepted_flag(self):
        call = GroundedSkillCall(SkillName.WAIT, (AGENT_0,))
        self.assertTrue(ValidatedCall(call).is_accepted)
        self.assertFalse(MalformedCall("unparseable").is_accepted)
        self.assertFalse(UngroundedCall("no such box").is_accepted)
        self.assertFalse(SymbolicallyInapplicable("light(box_0) is false").is_accepted)

    def test_rejection_kinds_are_distinct_types(self):
        self.assertNotIsInstance(MalformedCall("x"), UngroundedCall)
        self.assertNotIsInstance(UngroundedCall("x"), SymbolicallyInapplicable)
        self.assertNotIsInstance(SymbolicallyInapplicable("x"), MalformedCall)

    def test_registry_refuses_an_unknown_skill_name(self):
        """The registry has no default arm. The backend has two —
        `_skill_parser` falls back to `explore` (box_push_centralized.py:313-314) and `make_skill`
        to `WaitSkill` (skill_executor_push.py:386) — and neither may be reproduced here.

        NOTE: P0 ships no parser, so this pins the registry's behaviour only; the rejection of
        malformed INPUT becomes testable when the P1 wrapper adds a validator."""
        with self.assertRaises(KeyError):
            REGISTRY.get("NotASkill")
        with self.assertRaises(KeyError):
            REGISTRY.get(SkillName.PUSH.value + "_typo")


if __name__ == "__main__":
    unittest.main()
