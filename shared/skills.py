"""Frozen executive skill vocabulary, signatures, grounded calls, and the skill registry.

P0_V1_DECISIONS Decision 11 (FROZEN):

    GotoPushPose   (agent: AgentId, box: BoxId, zone: ZoneId)
    Push           (agent: AgentId, box: BoxId, zone: ZoneId)
    CooperativePush(agents: tuple[AgentId, AgentId], box: BoxId, zone: ZoneId)  # canonically ordered
    Explore        (agent: AgentId)     # registry + backend only; NOT in the V1 symbolic action set
    Wait           (agent: AgentId)

These signatures are the single source of truth for every layer. As of P0 two consumers exist and
are checked mechanically: the registry (here) and the structured IR (`DomainIR` requires each
`SkillIR` to hold the registry's signature OBJECT, and validates the lifted expansion). The
symbolic planner and the backend wrapper do not exist yet — when they land, they must bind through
`SkillIR.bind`/`unbind` rather than re-declaring parameters.

Arguments are IDENTITIES, never grid cells. A stale coordinate is indistinguishable from a valid
one, which is exactly how the current backend's silent re-grounding hides
(`_resolve_box`, skill_executor_push.py:128-136 / :263-270). An unresolvable `BoxId` is a
detectable `UngroundedCall` — that is what makes Decision 7 enforceable.

Supervisor: :82 (names come from contracts, not ad hoc strings), :93-104 (stable name/signature,
typed parameters, backend mapping), :118 (deterministic grounded-call key for bookkeeping).
"""
from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, Mapping, Optional, Tuple

from shared.ids import AgentId, BoxId, ZoneId, canonical_agent_pair


class SkillName(StrEnum):
    """Stable executive skill names. The single source of truth for every layer."""
    GOTO_PUSH_POSE = "GotoPushPose"
    PUSH = "Push"
    COOPERATIVE_PUSH = "CooperativePush"
    EXPLORE = "Explore"
    WAIT = "Wait"


class ParameterType(StrEnum):
    AGENT = "AgentId"
    AGENT_PAIR = "tuple[AgentId, AgentId]"
    BOX = "BoxId"
    ZONE = "ZoneId"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    type: ParameterType


@dataclass(frozen=True, slots=True)
class SkillSignature:
    """Stable typed signature. `cost` defaults to 1 (:104: cost, default 1 unless specified)."""
    name: SkillName
    parameters: Tuple[ParameterSpec, ...]
    cost: int = 1
    in_symbolic_action_set: bool = True
    backend_mapping: str = ""        # exact backend implementation class this maps to (:104)
    backend_dispatch_key: str = ""   # exact adapter dispatch token (Decision 14)
    description: str = ""

    def __post_init__(self) -> None:
        if self.cost < 0:
            raise ValueError("skill cost must be non-negative")
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate parameter names in {self.name}")
        if not self.backend_mapping:
            raise ValueError(f"{self.name}: backend_mapping is part of the frozen signature (:104)")
        if not self.backend_dispatch_key:
            raise ValueError(
                f"{self.name}: backend_dispatch_key is frozen by Decision 14; a skill with no "
                f"dispatch token is exactly the hole that routes Wait through a fallback arm"
            )

    @property
    def arity(self) -> int:
        """Number of call-facing parameters (an agent pair counts as ONE)."""
        return len(self.parameters)

    @property
    def expanded_arity(self) -> int:
        """Number of lifted planning variables (an agent pair counts as TWO).

        The call-facing form carries `agents` as one canonically ordered pair; classical planning
        needs one variable per agent. The semantics are identical — only the packing differs — and
        `SkillIR.bind()` is the single place that expansion happens.
        """
        return sum(2 if p.type is ParameterType.AGENT_PAIR else 1 for p in self.parameters)

    @property
    def parameter_types(self) -> Tuple[ParameterType, ...]:
        return tuple(p.type for p in self.parameters)


# ── The frozen registry ────────────────────────────────────────────────────────────

_SIGNATURES: Tuple[SkillSignature, ...] = (
    SkillSignature(
        name=SkillName.GOTO_PUSH_POSE,
        parameters=(
            ParameterSpec("agent", ParameterType.AGENT),
            ParameterSpec("box", ParameterType.BOX),
            ParameterSpec("zone", ParameterType.ZONE),
        ),
        backend_mapping="skill_executor_push.GotoPushPoseSkill",
        backend_dispatch_key="goto_push_pose",
        description="Navigate behind `box` on the side away from `zone`, facing the push direction.",
    ),
    SkillSignature(
        name=SkillName.PUSH,
        parameters=(
            ParameterSpec("agent", ParameterType.AGENT),
            ParameterSpec("box", ParameterType.BOX),
            ParameterSpec("zone", ParameterType.ZONE),
        ),
        backend_mapping="skill_executor_push.PushSkill",
        backend_dispatch_key="push",
        description=(
            "Push-to-zone. Symbolic success is delivered(box). Cell-by-cell movement, blocking, "
            "partial movement and timeout are backend execution details, not symbolic outcomes."
        ),
    ),
    SkillSignature(
        name=SkillName.COOPERATIVE_PUSH,
        parameters=(
            ParameterSpec("agents", ParameterType.AGENT_PAIR),
            ParameterSpec("box", ParameterType.BOX),
            ParameterSpec("zone", ParameterType.ZONE),
        ),
        backend_mapping="skill_executor_push.CooperativePushSkill (both agent instances, wrapper-owned)",
        backend_dispatch_key="cooperate_push",
        description=(
            "ONE sequential executive skill that internally coordinates both agents using joint "
            "primitive backend actions. Push-to-zone; symbolic success is delivered(box)."
        ),
    ),
    SkillSignature(
        name=SkillName.EXPLORE,
        parameters=(ParameterSpec("agent", ParameterType.AGENT),),
        in_symbolic_action_set=False,
        backend_mapping="shared_skills.ExploreSkill",
        backend_dispatch_key="explore",
        description=(
            "Backend/NL-track only. V1 symbolic state is fully observable from initialization, so "
            "discovery is not required by the symbolic planner (Decision 5)."
        ),
    ),
    SkillSignature(
        name=SkillName.WAIT,
        parameters=(ParameterSpec("agent", ParameterType.AGENT),),
        in_symbolic_action_set=False,
        backend_mapping="shared_skills.WaitSkill",
        backend_dispatch_key="wait",
        description=(
            "Idle for one executive step. Completes immediately (consumes no primitive step). "
            "NOTE: the existing backend factory `skill_executor_push.make_skill` has NO 'wait' "
            "arm — it reaches WaitSkill only through its silent default. Decision 14 therefore "
            "obliges the P1 adapter to dispatch exhaustively on this key and to keep no fallback."
        ),
    ),
)


class SkillRegistry:
    """Frozen registry. The registry is a SUPERSET of the symbolic action set."""

    def __init__(self, signatures: Tuple[SkillSignature, ...] = _SIGNATURES) -> None:
        self._by_name: Dict[SkillName, SkillSignature] = {s.name: s for s in signatures}
        if len(self._by_name) != len(signatures):
            raise ValueError("duplicate skill names in registry")
        keys = [s.backend_dispatch_key for s in signatures]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate backend dispatch keys in registry")

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)

    def get(self, name: SkillName) -> SkillSignature:
        try:
            return self._by_name[name]
        except KeyError:
            raise KeyError(f"unknown skill {name!r}") from None

    def names(self) -> Tuple[SkillName, ...]:
        return tuple(self._by_name)

    def symbolic_action_set(self) -> Tuple[SkillName, ...]:
        return tuple(n for n, s in self._by_name.items() if s.in_symbolic_action_set)

    def dispatch_keys(self) -> Dict[str, SkillName]:
        """Frozen adapter dispatch table (Decision 14). Exhaustive over the registry."""
        return {s.backend_dispatch_key: s.name for s in self._by_name.values()}

    def by_dispatch_key(self, key: str) -> SkillSignature:
        """Resolve a dispatch token. Raises rather than falling back — the fallback IS the bug."""
        for s in self._by_name.values():
            if s.backend_dispatch_key == key:
                return s
        raise KeyError(
            f"no registry skill dispatches on {key!r}; an adapter must reject an unknown token as "
            f"a MalformedCall, never substitute a default skill"
        )


REGISTRY = SkillRegistry()


# ── Grounded calls ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class GroundedSkillCall:
    """A fully grounded executive skill invocation.

    Uniform shape across all skills so the executor, monitor, trace and bookkeeping handle one
    type. Field presence is validated against the frozen signature at construction.
    """
    skill: SkillName
    agents: Tuple[AgentId, ...]
    box: Optional[BoxId] = None
    zone: Optional[ZoneId] = None

    def __post_init__(self) -> None:
        sig = REGISTRY.get(self.skill)
        types = sig.parameter_types

        # Types, not just presence: Decision 11 says no layer sees a different type. Without this
        # a raw ("agent_0", 1, "delivery_zone") call constructs and only fails much later.
        object.__setattr__(self, "agents", tuple(self.agents))
        for a in self.agents:
            if not isinstance(a, AgentId):
                raise TypeError(f"{self.skill}: agents must be AgentId, got {type(a).__name__}")
        if self.box is not None and not isinstance(self.box, BoxId):
            raise TypeError(f"{self.skill}: box must be BoxId, got {type(self.box).__name__}")
        if self.zone is not None and not isinstance(self.zone, ZoneId):
            raise TypeError(f"{self.skill}: zone must be ZoneId, got {type(self.zone).__name__}")

        if ParameterType.AGENT_PAIR in types:
            if len(self.agents) != 2:
                raise ValueError(f"{self.skill} requires exactly 2 agents, got {len(self.agents)}")
            object.__setattr__(self, "agents", canonical_agent_pair(*self.agents))
        elif ParameterType.AGENT in types:
            if len(self.agents) != 1:
                raise ValueError(f"{self.skill} requires exactly 1 agent, got {len(self.agents)}")

        needs_box = ParameterType.BOX in types
        if needs_box and self.box is None:
            raise ValueError(f"{self.skill} requires a box argument")
        if not needs_box and self.box is not None:
            raise ValueError(f"{self.skill} does not take a box argument")

        needs_zone = ParameterType.ZONE in types
        if needs_zone and self.zone is None:
            raise ValueError(f"{self.skill} requires a zone argument")
        if not needs_zone and self.zone is not None:
            raise ValueError(f"{self.skill} does not take a zone argument")

    @property
    def signature(self) -> SkillSignature:
        return REGISTRY.get(self.skill)

    @property
    def cost(self) -> int:
        return self.signature.cost

    def canonical(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"skill": str(self.skill), "agents": [a.value for a in self.agents]}
        if self.box is not None:
            d["box"] = self.box.value
        if self.zone is not None:
            d["zone"] = self.zone.value
        return d

    def key(self) -> str:
        """Deterministic serialization — the grounded-skill half of the repeated-failure key (:118)."""
        return json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "GroundedSkillCall":
        return cls(
            skill=SkillName(d["skill"]),
            agents=tuple(AgentId(a) for a in d["agents"]),
            box=BoxId(d["box"]) if "box" in d and d["box"] is not None else None,
            zone=ZoneId(d["zone"]) if "zone" in d and d["zone"] is not None else None,
        )

    def __str__(self) -> str:
        parts = [",".join(a.value for a in self.agents)]
        if self.box is not None:
            parts.append(str(self.box))
        if self.zone is not None:
            parts.append(str(self.zone))
        return f"{self.skill}({'; '.join(parts)})"


# ── Call validation results (Decision 7) ───────────────────────────────────────────
#
# The three REJECTION kinds consume ZERO executive steps (Decision 2). Malformed and Ungrounded
# are InfrastructureFault material (:159 missing grounding, :156 malformed); SymbolicallyInapplicable
# is a legitimate symbolic-track result and must NOT be reported as an InfrastructureFault.
#
# `OutsideSymbolicModel` is NOT a rejection and is deliberately excluded from that sentence: it is
# a model-COVERAGE verdict, the call is executable, and executing it consumes one executive step
# like any other. Branch on `is_executable`, never on `is_accepted`, when deciding to execute.

@dataclass(frozen=True, slots=True)
class CallValidation(ABC):
    """Abstract base. NEVER dispatch on `is_accepted` alone.

    The three rejection kinds route differently and must not be collapsed into one boolean:
      MalformedCall / UngroundedCall  -> InfrastructureFault (:156, :159), short-circuits the cycle
      SymbolicallyInapplicable        -> a legitimate SYMBOLIC-track result, NOT a fault
    `is_accepted` is a convenience for the accept path only; rejection handling must branch on the
    concrete type (or use `is_infrastructure_fault`).
    """

    def __new__(cls, *args, **kwargs):
        if cls is CallValidation:
            raise TypeError(
                "CallValidation is abstract; construct one of its concrete subclasses so the "
                "distinction it exists to preserve cannot be lost"
            )
        return object.__new__(cls)

    @property
    def is_accepted(self) -> bool:
        return isinstance(self, ValidatedCall)

    @property
    def is_infrastructure_fault(self) -> bool:
        """True exactly for the rejection kinds Decision 7 maps to InfrastructureFault."""
        return isinstance(self, (MalformedCall, UngroundedCall))

    @property
    def is_pre_executor_rejection(self) -> bool:
        """True for the rejections that stop a call BEFORE the executor.

        Deliberately distinct from `FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION`, which
        describes a call that DID reach the executor (one executive step) and was then declined by
        the backend skill before any world transition. Both were called "rejected"; only this one
        means "never executed, zero executive steps, symbolic state untouched" (Decision 13.8).
        """
        return isinstance(self, (MalformedCall, UngroundedCall, SymbolicallyInapplicable))

    @property
    def is_executable(self) -> bool:
        """May the executor run this call?

        Distinct from `is_accepted`, which means "the symbolic track validated it". An
        `OutsideSymbolicModel` result is NOT accepted (the symbolic track has no model for the
        skill) yet the call IS executable — `Explore` and `Wait` are registry-valid and
        backend-mapped. Gating execution on `is_accepted` would refuse them, which is the opposite
        of Decision 15's intent, so the two properties are kept separate.
        """
        return isinstance(self, (ValidatedCall, OutsideSymbolicModel))


@dataclass(frozen=True, slots=True)
class ValidatedCall(CallValidation):
    call: GroundedSkillCall


@dataclass(frozen=True, slots=True)
class MalformedCall(CallValidation):
    """Unparseable / wrong arity / wrong types / unknown skill name.

    Never silently rewritten to another skill. The legacy backend does exactly that
    (box_push_centralized.py::_skill_parser → `explore`, banner-marked SUPERSEDED FOR V1;
    skill_executor_push.py:386 → `WaitSkill`).
    """
    reason: str
    raw: str = ""

    def to_infrastructure_fault(self):
        from shared.faults import FaultKind, InfrastructureFault
        return InfrastructureFault(
            kind=FaultKind.MALFORMED_SKILL_CALL, message=self.reason, detail=self.raw
        )


@dataclass(frozen=True, slots=True)
class UngroundedCall(CallValidation):
    """Well-formed but references an identity absent from the authoritative state.

    Never silently re-grounded onto a different object (skill_executor_push.py:128-136, :263-270).
    """
    reason: str
    call: Optional[GroundedSkillCall] = None

    def to_infrastructure_fault(self):
        from shared.faults import FaultKind, InfrastructureFault
        return InfrastructureFault(kind=FaultKind.MISSING_GROUNDING, message=self.reason)


@dataclass(frozen=True, slots=True)
class SymbolicallyInapplicable(CallValidation):
    """Well-formed and grounded, but symbolic preconditions do not hold.

    A symbolic-track result, NOT an infrastructure fault and NOT an execution discrepancy.
    """
    reason: str
    call: Optional[GroundedSkillCall] = None
    unsatisfied: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class OutsideSymbolicModel(CallValidation):
    """Registry-valid and grounded, but the skill is deliberately absent from the V1 symbolic
    model (`Explore`, `Wait` — Decision 5, Decision 14).

    This is a fourth, distinct outcome and must not be collapsed into either neighbour:

      * NOT `SymbolicallyInapplicable` — that asserts preconditions were evaluated and failed.
        Here there are no preconditions to evaluate; the symbolic track holds no model at all.
        Reporting it as inapplicable would state a symbolic verdict the model cannot support.
      * NOT an `InfrastructureFault` — nothing is broken. `is_infrastructure_fault` is False and
        the executive cycle is NOT short-circuited (:163).

    What it licenses and what it forbids:
      * the call MAY still be executed — it is registry-valid and backend-mapped. `is_accepted`
        is False (nothing validated it symbolically) but `is_executable` is True, and executing it
        consumes ONE executive step like any other invocation (Decision 2);
      * the symbolic track MUST NOT predict effects for it, and therefore
      * NO `STATE_EFFECT_MISMATCH` may ever be raised for it (there is no prediction to compare).
        An execution failure is still reportable as `EXECUTION_FAILURE_OF_APPLICABLE_SKILL`'s
        sibling `UNEXPECTED_OUTCOME` on the authoritative outcome alone (Decision 13.7).
    """
    reason: str
    call: Optional[GroundedSkillCall] = None
    skill: Optional[SkillName] = None

    def __post_init__(self) -> None:
        if self.skill is None and self.call is not None:
            object.__setattr__(self, "skill", self.call.skill)
        if self.skill is not None and REGISTRY.get(self.skill).in_symbolic_action_set:
            raise ValueError(
                f"{self.skill} IS in the V1 symbolic action set; a failed precondition check on "
                f"it is SymbolicallyInapplicable, not OutsideSymbolicModel"
            )
