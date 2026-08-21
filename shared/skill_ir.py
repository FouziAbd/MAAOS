"""Deterministic structured skill IR (SUPERVISOR_P0_P4_CONTRACT.md:72, :182).

The IR is authored in the structured shape a later probabilistic extension can grow into, but V1
is deterministic: `outcome_label` is a single scalar, so adding an outcome DISTRIBUTION will
require a schema change (a set of weighted outcomes) — the shape is prepared for it, not already
capable of it. Per the project symbolic-model rule
the IR carries: typed signature, declarative preconditions, explicit dependencies, one
deterministic success outcome, deterministic effects, implicit frame conditions for unmentioned
variables, observations, cost (default 1), and provenance/version metadata.

This module is env-agnostic. The frozen BoxPush V1 domain instance lives in `domain/box_push_v1.py`.

CRITICAL (P0_V1_DECISIONS Decision 6 / supervisor :55): PRECONDITIONS are DECLARATIVE symbolic
predicates only. Applicability and planning may never consult backend reachability, BFS,
occupancy, collision, feasibility predicates or procedural simulation. The IR is intentionally
optimistic; a skill may be symbolically applicable and still fail in the authoritative backend,
and that is an ExecutionDiscrepancy, not a modelling bug.

The prohibition is scoped to applicability/planning, NOT to effects (Decision 13). A deterministic
skill may declare the world effects its own success semantics imply — see
`SkillIR.predicted_world_effects` — and a P2 predictor may ground them arithmetically. Predicting
where success puts an agent is not the same act as deciding whether it can get there.

Frame conditions are IMPLICIT: any state variable not named in an effect is unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from shared.skills import (
    REGISTRY,
    GroundedSkillCall,
    OutsideSymbolicModel,
    ParameterType,
    SkillName,
    SkillSignature,
)
from shared.versioning import ModelVersion, Provenance


@dataclass(frozen=True, order=True, slots=True)
class PredicateName:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.replace("_", "").isalnum():
            raise ValueError(f"invalid predicate name {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Predicate:
    """A LIFTED predicate: `args` are skill parameter names, not concrete identities.

    e.g. Predicate("in_pose", ("agent", "box")) inside GotoPushPose's effects.
    For the two-agent skill, parameter names are "agent1"/"agent2" (positions within the pair).
    """
    name: PredicateName
    args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if isinstance(self.name, str):
            object.__setattr__(self, "name", PredicateName(self.name))
        object.__setattr__(self, "args", tuple(self.args))

    @property
    def arity(self) -> int:
        return len(self.args)

    def canonical(self) -> Dict[str, Any]:
        return {"name": str(self.name), "args": list(self.args)}

    def __str__(self) -> str:
        return f"{self.name}({', '.join(self.args)})" if self.args else str(self.name)


@dataclass(frozen=True, slots=True)
class Effect:
    """A deterministic add (positive) or delete (negative) effect."""
    predicate: Predicate
    positive: bool = True

    def canonical(self) -> Dict[str, Any]:
        return {"predicate": self.predicate.canonical(), "positive": self.positive}

    def __str__(self) -> str:
        return f"{'' if self.positive else 'not '}{self.predicate}"


@dataclass(frozen=True, slots=True)
class PredicateDecl:
    """Declaration of a predicate in the domain, with its parameter kinds."""
    name: PredicateName
    param_types: Tuple[str, ...]     # e.g. ("box",) or ("agent", "box")
    fluent: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.name, str):
            object.__setattr__(self, "name", PredicateName(self.name))
        object.__setattr__(self, "param_types", tuple(self.param_types))

    @property
    def arity(self) -> int:
        return len(self.param_types)


#: The V1 object/type universe (SUPERVISOR_P0_P4_CONTRACT.md:64 "objects/types").
#: Every lifted planning variable and every predicate argument carries one of these.
TYPE_AGENT = "agent"
TYPE_BOX = "box"
TYPE_ZONE = "zone"
TYPE_UNIVERSE: Tuple[str, ...] = (TYPE_AGENT, TYPE_BOX, TYPE_ZONE)

#: Call-facing parameter type -> lifted planning type(s).
_SIGNATURE_TO_IR_TYPES = {
    ParameterType.AGENT: (TYPE_AGENT,),
    ParameterType.AGENT_PAIR: (TYPE_AGENT, TYPE_AGENT),
    ParameterType.BOX: (TYPE_BOX,),
    ParameterType.ZONE: (TYPE_ZONE,),
}


@dataclass(frozen=True, slots=True)
class SkillIR:
    """One executive skill's deterministic V1 model."""
    signature: SkillSignature
    parameters: Tuple[str, ...]              # lifted variable names, e.g. ("agent", "box", "zone")
    parameter_types: Tuple[str, ...]         # parallel to `parameters`, drawn from TYPE_UNIVERSE
    preconditions: Tuple[Predicate, ...]
    effects: Tuple[Effect, ...]
    provenance: Provenance
    dependencies: Tuple[str, ...] = field(default_factory=tuple)
    observations: Tuple[str, ...] = field(default_factory=tuple)
    outcome_label: str = "success"           # exactly one deterministic outcome in V1
    #: Deterministic WORLD effects that belong to this skill's declared success semantics, written
    #: over the lifted parameters (P0_V1_DECISIONS Decision 13.2). These are what a P2 predictor
    #: may ground and hand to the monitor as `ExecutionDiscrepancy.predicted_world_key` evidence.
    #: They are ARITHMETIC on declared success semantics, never a feasibility query: declaring
    #: "the agent ends on the pose cell" says where success puts it, not whether it can get there.
    #: P2 must ground these WITHOUT BFS, reachability, occupancy, collision or backend simulation.
    predicted_world_effects: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.parameters) != len(self.parameter_types):
            raise ValueError(f"{self.name}: parameters and parameter_types must be parallel")
        if len(set(self.parameters)) != len(self.parameters):
            raise ValueError(f"{self.name}: duplicate lifted parameter names")
        bad = [t for t in self.parameter_types if t not in TYPE_UNIVERSE]
        if bad:
            raise ValueError(f"{self.name}: unknown parameter types {bad}")

        # Cross-layer arity: the IR must expand the call-facing signature exactly (Decision 11).
        if len(self.parameters) != self.signature.expanded_arity:
            raise ValueError(
                f"{self.name}: IR declares {len(self.parameters)} lifted parameters but the "
                f"registry signature expands to {self.signature.expanded_arity}"
            )
        expected: list[str] = []
        for p in self.signature.parameters:
            expected.extend(_SIGNATURE_TO_IR_TYPES[p.type])
        if list(self.parameter_types) != expected:
            raise ValueError(
                f"{self.name}: IR parameter types {list(self.parameter_types)} do not match the "
                f"registry signature expansion {expected}"
            )

        declared = set(self.parameters)
        for p in self.preconditions:
            unknown = set(p.args) - declared
            if unknown:
                raise ValueError(
                    f"{self.name}: precondition {p} references undeclared parameters {sorted(unknown)}"
                )
        for e in self.effects:
            unknown = set(e.predicate.args) - declared
            if unknown:
                raise ValueError(
                    f"{self.name}: effect {e} references undeclared parameters {sorted(unknown)}"
                )

    def type_of(self, parameter: str) -> str:
        try:
            return self.parameter_types[self.parameters.index(parameter)]
        except ValueError:
            raise KeyError(f"{self.name}: no lifted parameter {parameter!r}") from None

    @property
    def name(self) -> SkillName:
        return self.signature.name

    @property
    def cost(self) -> int:
        return self.signature.cost

    def bind(self, call: "GroundedSkillCall") -> Dict[str, str]:
        """Bind a grounded call's identities to this skill's lifted planning variables.

        The single place where the call-facing agent PAIR is expanded into two planning
        variables. Order within the pair is canonical (ascending AgentId), so binding is
        deterministic. Everything else maps positionally.
        """
        if call.skill is not self.name:
            raise ValueError(f"cannot bind a {call.skill} call to the {self.name} IR")
        values: list[str] = [a.value for a in call.agents]
        if call.box is not None:
            values.append(str(call.box))
        if call.zone is not None:
            values.append(call.zone.value)
        if len(values) != len(self.parameters):
            raise ValueError(
                f"{self.name}: cannot bind {len(values)} values to {len(self.parameters)} parameters"
            )
        return dict(zip(self.parameters, values))

    def unbind(self, binding: Mapping[str, str]) -> "GroundedSkillCall":
        """Inverse of `bind()`: lifted variable binding -> grounded call.

        A planner emits lifted actions, so P2 needs this direction. Round-tripping through
        `bind`/`unbind` re-canonicalizes the agent pair, which matters because the symbolic
        `different(?a1,?a2)` predicate is symmetric: a classical planner grounds both
        `(a0,a1)` and `(a1,a0)`, and both must collapse to the same `GroundedSkillCall`.
        """
        from shared.ids import AgentId, BoxId, ZoneId

        missing = set(self.parameters) - set(binding)
        if missing:
            raise ValueError(f"{self.name}: binding is missing {sorted(missing)}")
        agents, box, zone = [], None, None
        for name, kind in zip(self.parameters, self.parameter_types):
            value = binding[name]
            if kind == TYPE_AGENT:
                agents.append(AgentId(value))
            elif kind == TYPE_BOX:
                box = BoxId.parse(value)
            else:
                zone = ZoneId(value)
        return GroundedSkillCall(self.name, tuple(agents), box, zone)

    def canonical(self) -> Dict[str, Any]:
        return {
            "name": str(self.name),
            "parameters": list(self.parameters),
            "parameter_types": list(self.parameter_types),
            "preconditions": [p.canonical() for p in self.preconditions],
            "effects": [e.canonical() for e in self.effects],
            "cost": self.cost,
            "outcome_label": self.outcome_label,
            "dependencies": list(self.dependencies),
            "observations": list(self.observations),
            "predicted_world_effects": list(self.predicted_world_effects),
            "provenance": {
                "source": self.provenance.source,
                "model_version": str(self.provenance.model_version),
            },
        }


@dataclass(frozen=True, slots=True)
class DomainIR:
    """A frozen, deterministic domain: declared predicates + the symbolic action set."""
    name: str
    model_version: ModelVersion
    predicates: Tuple[PredicateDecl, ...]
    skills: Tuple[SkillIR, ...]
    provenance: Provenance
    types: Tuple[str, ...] = TYPE_UNIVERSE      # :64 objects/types

    def __post_init__(self) -> None:
        decl = {str(p.name): p for p in self.predicates}
        if len(decl) != len(self.predicates):
            raise ValueError("duplicate predicate declarations")
        if len({s.name for s in self.skills}) != len(self.skills):
            raise ValueError("duplicate skills in domain")
        # The IR must use the REGISTRY's signature object itself, not a look-alike. A hand-built
        # SkillSignature would let the IR drift from the call-facing contract undetected.
        for s in self.skills:
            if s.signature is not REGISTRY.get(s.name):
                raise ValueError(
                    f"{s.name}: IR signature is not the frozen registry signature object"
                )
        bad_types = [t for p in self.predicates for t in p.param_types if t not in TYPE_UNIVERSE]
        if bad_types:
            raise ValueError(f"predicate declarations use unknown types {sorted(set(bad_types))}")

        # Every predicate used by a skill must be declared, with matching arity AND argument TYPES.
        # The type check is what catches a swapped-argument bug such as in_pose(box, agent),
        # which an arity-only check accepts silently.
        for s in self.skills:
            for p in list(s.preconditions) + [e.predicate for e in s.effects]:
                d = decl.get(str(p.name))
                if d is None:
                    raise ValueError(f"{s.name}: undeclared predicate {p.name}")
                if d.arity != p.arity:
                    raise ValueError(
                        f"{s.name}: predicate {p.name} used with arity {p.arity}, declared {d.arity}"
                    )
                actual = tuple(s.type_of(arg) for arg in p.args)
                if actual != d.param_types:
                    raise ValueError(
                        f"{s.name}: predicate {p.name} applied to types {actual}, "
                        f"declared {d.param_types}"
                    )

    def skill(self, name: SkillName) -> SkillIR:
        """The IR for a skill in the symbolic action set. Raises otherwise — use `resolve()` when
        the name may legitimately be a registry-only skill."""
        for s in self.skills:
            if s.name == name:
                return s
        raise KeyError(f"skill {name} is not in the symbolic action set")

    def resolve(self, name: SkillName) -> "SkillIR | OutsideSymbolicModel":
        """Look up a skill, returning a TYPED result for the registry-only case.

        `Explore` and `Wait` are registry-valid and backend-mapped but deliberately absent from
        the V1 symbolic model (Decision 5). A bare `KeyError` forces the caller to invent a
        meaning for that, and the natural inventions are both wrong: `SymbolicallyInapplicable`
        asserts a precondition verdict the model cannot support, and `InfrastructureFault`
        short-circuits the cycle over a skill that is working exactly as designed.
        """
        for s in self.skills:
            if s.name == name:
                return s
        if name in REGISTRY:
            return OutsideSymbolicModel(
                reason=(
                    f"{name} is registry-valid but is not in the V1 symbolic action set; the "
                    f"symbolic track holds no model for it and predicts no effects"
                ),
                skill=name,
            )
        raise KeyError(f"unknown skill {name}")

    def has_skill(self, name: SkillName) -> bool:
        return any(s.name == name for s in self.skills)

    def action_set(self) -> Tuple[SkillName, ...]:
        return tuple(s.name for s in self.skills)

    def canonical(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "model_version": str(self.model_version),
            "types": list(self.types),
            "predicates": [
                {"name": str(p.name), "param_types": list(p.param_types), "fluent": p.fluent}
                for p in self.predicates
            ],
            "skills": [s.canonical() for s in self.skills],
        }

    def digest(self) -> str:
        import hashlib
        blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
