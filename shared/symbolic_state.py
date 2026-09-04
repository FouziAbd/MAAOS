"""Symbolic projection, and the SYMBOLIC HALF of the monitor's comparison criterion.

WHY THIS EXISTS
---------------
`StateSnapshot` is the canonical, authoritative *world* state and stays that way (Decision 4). But
the symbolic model's vocabulary is `delivered/pending/light/heavy/discovered/in_pose/different`,
so comparing two whole `StateSnapshot`s is the wrong criterion on its own: a successful
`GotoPushPose` moves an agent (world changes) while its declared symbolic effect adds only
`in_pose` (no symbolic literal about position changes). A raw world comparison would report a
mismatch on the happy path.

The projection gives the monitor a second, correctly-scoped basis:

    symbolic basis:   PROJECTION.agrees(project(predicted), project(observed))
    world basis:      predicted world effect  vs  StateSnapshot.world_key()   (Decision 13.2)
    bookkeeping key:  StateSnapshot.world_key()          (repeated-failure keying, :118)
    replay key:       StateSnapshot.replay_key()

BOTH bases are live in V1 (P0_V1_DECISIONS Decision 13). The projection is NOT a replacement for
world-state evidence and this module must not be read as weakening the monitor to symbolic-only
comparison. `ExecutionDiscrepancy` carries a separate, correctly named key pair for each.

WHAT THE ORACLE PROHIBITION ACTUALLY FORBIDS
--------------------------------------------
It forbids symbolic APPLICABILITY and PLANNING from deciding whether a skill can succeed using
backend feasibility predicates, BFS, reachability, occupancy, collision or procedural simulation
(Decision 6, supervisor :55).

It does NOT forbid predicting effects. A deterministic skill may declare and ground the world
effect that belongs to its own success semantics — an intended agent pose cell, an intended box
target position. That is arithmetic on declared success semantics, not a search for whether the
agent can get there. `SkillIR.predicted_world_effects` declares those effects; P2 grounds them.

PROJECTABLE vs EXECUTIVE-TRACKED
--------------------------------
A predicate is *world-projectable* when it can be read from a `StateSnapshot` by inspection, with
no derivation at all. In BoxPush V1 exactly one predicate fails that test: `in_pose(agent, box)`,
whose truth would have to be derived from the pose cell `B - D`.

`in_pose` is therefore declared **executive-tracked**: maintained by the symbolic track from its
own deterministic effects and the executor's typed outcome, and excluded from the monitored
symbolic subset — comparing it there would compare the model against itself.

This is emphatically NOT a decision to leave `GotoPushPose` unmonitored. Decision 13.3 freezes
that P2 may predict the intended successful pose POSITION as a world effect and compare it against
the authoritative post-state, with no reachability or feasibility oracle involved. Until that
predictor exists, `GotoPushPose` failure is detected through the authoritative typed
`ExecutionOutcome` — always available, never optional (:139).

`ProjectionContract.apply_outcome` implements the Decision 13.8 maintenance rule for
executive-tracked literals.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, Tuple

from shared.comparison_keys import SymbolicKey


@dataclass(frozen=True, order=True, slots=True)
class GroundedLiteral:
    """A predicate applied to concrete identity strings. Hashable and totally ordered."""
    predicate: str
    args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.predicate:
            raise ValueError("GroundedLiteral requires a predicate name")
        object.__setattr__(self, "args", tuple(self.args))
        for a in self.args:
            if not isinstance(a, str) or not a:
                raise ValueError(f"literal arguments must be non-empty strings, got {a!r}")

    def canonical(self) -> str:
        return f"{self.predicate}({','.join(self.args)})" if self.args else self.predicate

    def __str__(self) -> str:
        return self.canonical()


@dataclass(frozen=True, slots=True)
class SymbolicState:
    """A set of true grounded literals. Closed-world: absent literals are false."""
    literals: FrozenSet[GroundedLiteral]

    def __post_init__(self) -> None:
        object.__setattr__(self, "literals", frozenset(self.literals))

    @classmethod
    def of(cls, literals: Iterable[GroundedLiteral]) -> "SymbolicState":
        return cls(frozenset(literals))

    def holds(self, literal: GroundedLiteral) -> bool:
        return literal in self.literals

    def restricted_to(self, predicates: Iterable[str]) -> "SymbolicState":
        keep = set(predicates)
        return SymbolicState.of(
            literal for literal in self.literals if literal.predicate in keep
        )

    def canonical(self) -> Tuple[str, ...]:
        return tuple(sorted(literal.canonical() for literal in self.literals))

    def key(self) -> SymbolicKey:
        """Typed so it cannot be written into a world-key field (Decision 13.6)."""
        blob = json.dumps(self.canonical(), separators=(",", ":"))
        return SymbolicKey(hashlib.sha256(blob.encode("utf-8")).hexdigest())

    def difference(self, other: "SymbolicState") -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        """(present-here-only, present-there-only) — the monitor's mismatch detail."""
        mine = {literal.canonical() for literal in self.literals}
        theirs = {literal.canonical() for literal in other.literals}
        return tuple(sorted(mine - theirs)), tuple(sorted(theirs - mine))

    def __len__(self) -> int:
        return len(self.literals)


@dataclass(frozen=True, slots=True)
class ProjectionContract:
    """Declares, per domain, which predicates are world-projectable and which are not.

    `monitored` is the subset the monitor may compare SYMBOLICALLY. It is exactly the projectable
    set: an executive-tracked predicate has no authoritative world counterpart readable by
    inspection, so comparing it here would compare the model against itself. Excluding a predicate
    from `monitored` removes it from the SYMBOLIC basis only — the world basis is unaffected
    (Decision 13.3).
    """
    projectable: FrozenSet[str]
    executive_tracked: FrozenSet[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "projectable", frozenset(self.projectable))
        object.__setattr__(self, "executive_tracked", frozenset(self.executive_tracked))
        overlap = self.projectable & self.executive_tracked
        if overlap:
            raise ValueError(f"a predicate cannot be both projectable and executive-tracked: {sorted(overlap)}")

    @property
    def monitored(self) -> FrozenSet[str]:
        return self.projectable

    def declared_predicates(self) -> FrozenSet[str]:
        return self.projectable | self.executive_tracked

    def monitored_view(self, state: SymbolicState) -> SymbolicState:
        return state.restricted_to(self.monitored)

    def monitored_key(self, state: SymbolicState) -> SymbolicKey:
        return self.monitored_view(state).key()

    def agrees(self, predicted: SymbolicState, observed: SymbolicState) -> bool:
        """The SYMBOLIC basis of the monitor comparison (Decision 13.6).

        Agreement here does not by itself clear a step: a predicted world effect may still
        disagree, and the authoritative `ExecutionOutcome` is always checked regardless.
        """
        return self.monitored_key(predicted) == self.monitored_key(observed)

    def _require_executive_tracked(self, literal: GroundedLiteral) -> None:
        if literal.predicate not in self.executive_tracked:
            raise ValueError(
                f"{literal.predicate!r} is not executive-tracked; projectable predicates come "
                f"from the authoritative state, not from an execution outcome"
            )

    def establish(self, state: SymbolicState, literal: GroundedLiteral) -> SymbolicState:
        """Add ONE executive-tracked grounded literal (a positive effect)."""
        self._require_executive_tracked(literal)
        return SymbolicState.of(set(state.literals) | {literal})

    def retract(self, state: SymbolicState, literal: GroundedLiteral) -> SymbolicState:
        """Remove ONE executive-tracked grounded literal (a negative effect).

        Exactly one grounding, never a predicate-wide sweep: V1 does not infer or enforce global
        exclusivity (Decision 6 keeps `in_pose` non-exclusive), so retracting `in_pose(a0, box_1)`
        must not disturb `in_pose(a0, box_0)`. A no-op when the literal was not true.

        This is also how a SUCCESSFUL skill applies a negative effect — `Push` deletes
        `in_pose(agent, box)` on success (`domain/box_push_v1.py`). Effect polarity and execution
        outcome are different axes and must not be collapsed into one boolean.
        """
        self._require_executive_tracked(literal)
        return SymbolicState.of(set(state.literals) - {literal})

    def apply_outcome(
        self,
        state: SymbolicState,
        literal: GroundedLiteral,
        *,
        succeeded: bool,
        world_changed: bool,
    ) -> SymbolicState:
        """The Decision 13.8 rule for an ATTEMPTED `GotoPushPose`-style establishing skill.

        Narrower than `establish`/`retract`: this is the outcome-driven rule, not a general effect
        applier. Use `establish`/`retract` for a skill's declared effects (including a negative
        effect on success); use this when a skill whose success EFFECT is `literal` has just
        returned a typed outcome.

        The frozen rule, in full:

          * A **pre-executor rejection** (`CallValidation.is_pre_executor_rejection`) never reaches
            this method at all. No attempt occurred, so symbolic state is unchanged — call nothing.
          * SUCCESS establishes the attempted grounded literal.
          * FAILURE **never** applies the success effect.
          * FAILURE invalidates the exact attempted grounded literal **only when the attempt could
            have disturbed its prior truth**, i.e. only when the world actually changed. `in_pose`
            is a function of agent and box positions; if neither moved
            (`FailureStateClass.UNCHANGED` or `BACKEND_REJECTED_BEFORE_TRANSITION`, both of which
            imply `not ExecutionResult.world_changed`), the prior truth is exactly as guaranteed as
            it was before the attempt, and retracting it would discard a fact the executive still
            knows. A `PARTIAL_EXECUTION` failure did move things, so the prior truth is no longer
            guaranteed and the literal goes.
          * Only that ONE grounding is ever touched. V1 does not infer or enforce global
            exclusivity — Decision 6 keeps `in_pose` non-exclusive.

        `world_changed` is required rather than defaulted: the caller holds the `ExecutionResult`
        and must pass `result.world_changed`. A default would silently pick one of the two
        behaviours at every call site that forgot.
        """
        if succeeded:
            return self.establish(state, literal)
        if world_changed:
            return self.retract(state, literal)
        return state

    def canonical(self) -> Dict[str, Any]:
        return {
            "projectable": sorted(self.projectable),
            "executive_tracked": sorted(self.executive_tracked),
            "monitored": sorted(self.monitored),
        }
