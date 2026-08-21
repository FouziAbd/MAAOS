"""The V1 exact-state symbolic belief.

V1 is fully observable (Decision 5): the projectable part of the belief is ALWAYS re-derived from
the authoritative `StateSnapshot` via the frozen projection — it is exact, never dead-reckoned,
and never patched from outcomes. The ONLY maintained content is the executive-tracked fluents
(`in_pose`), updated from typed execution outcomes exactly per Decision 13.8:

  - a pre-executor rejection never reaches `record_outcome` at all (symbolic state unchanged);
  - SUCCESS of an establishing skill (`GotoPushPose`) establishes the attempted literal, and a
    successful skill's declared NEGATIVE tracked effects are retracted (`Push`/`CooperativePush`
    consume `in_pose` on success);
  - FAILURE never applies success effects, and invalidates the establishing skill's attempted
    literal only when the attempt could have disturbed it (`world_changed`);
  - FAILURE of a CONSUMING skill retracts nothing — its precondition literals are retained (the
    frozen consuming-skill rule; `PushSkill` preserves the pushing formation on every partial
    cell, so retention is correct, not merely conservative);
  - no global exclusivity is ever inferred (Decision 6 keeps `in_pose` non-exclusive).

This module is symbolic-side: it may not import the predictor, monitor, backend, or `runtime`.
"""
from __future__ import annotations

from typing import Callable, Optional

from shared.execution import ExecutionOutcome, ExecutionResult
from shared.skill_ir import DomainIR
from shared.skills import GroundedSkillCall, OutsideSymbolicModel
from shared.state_snapshot import StateSnapshot
from shared.symbolic_state import GroundedLiteral, ProjectionContract, SymbolicState

from symbolic.applicability import ground_literals


class ExactSymbolicBelief:
    """Projectable literals from the authoritative snapshot + maintained tracked literals."""

    def __init__(
        self,
        domain: DomainIR,
        projection: ProjectionContract,
        project: Callable[[StateSnapshot], SymbolicState],
    ) -> None:
        self._domain = domain
        self._projection = projection
        self._project = project
        self._projected: SymbolicState = SymbolicState.of(())
        self._tracked: SymbolicState = SymbolicState.of(())
        self._synced = False

    # ── the exact-state path ───────────────────────────────────────────────────────

    def sync(self, snapshot: StateSnapshot) -> None:
        """Re-derive every projectable literal from the authoritative world. Tracked literals
        survive a sync untouched — they have no world counterpart to re-derive from, which is
        precisely what makes them optimistic (a stale `in_pose` is DESIGNED to survive until an
        execution outcome disturbs it)."""
        self._projected = self._projection.monitored_view(self._project(snapshot))
        self._synced = True

    @property
    def state(self) -> SymbolicState:
        """The planning/applicability state: exact projection + tracked fluents."""
        if not self._synced:
            raise RuntimeError("ExactSymbolicBelief.sync(snapshot) must be called first")
        return SymbolicState.of(self._projected.literals | self._tracked.literals)

    @property
    def tracked(self) -> SymbolicState:
        return self._tracked

    # ── Decision 13.8 outcome maintenance ─────────────────────────────────────────

    def record_outcome(self, result: ExecutionResult) -> None:
        """Maintain the executive-tracked fluents from one typed execution outcome.

        Projectable predicates are deliberately NOT touched here — the next `sync` carries them,
        and patching them from outcomes is how a model starts believing its own predictions.
        """
        call = result.call
        resolved = self._domain.resolve(call.skill)
        if isinstance(resolved, OutsideSymbolicModel):
            return                              # no symbolic model — nothing to maintain
        succeeded = result.outcome is ExecutionOutcome.SUCCESS
        tracked_names = self._projection.executive_tracked

        positive = [e for e in resolved.effects if e.positive
                    and str(e.predicate.name) in tracked_names]
        negative = [e for e in resolved.effects if not e.positive
                    and str(e.predicate.name) in tracked_names]

        if succeeded:
            for literal in ground_literals(resolved, call, [e.predicate for e in positive]):
                self._tracked = self._projection.establish(self._tracked, literal)
            for literal in ground_literals(resolved, call, [e.predicate for e in negative]):
                self._tracked = self._projection.retract(self._tracked, literal)
            return

        # FAILURE: never apply success effects; a consuming skill retracts nothing; an
        # establishing skill's attempted literal is invalidated only if the world moved.
        for literal in ground_literals(resolved, call, [e.predicate for e in positive]):
            self._tracked = self._projection.apply_outcome(
                self._tracked, literal, succeeded=False, world_changed=result.world_changed
            )

    # ── test/diagnostic conveniences ───────────────────────────────────────────────

    def establish(self, literal: GroundedLiteral) -> None:
        """Directly establish a tracked literal (test scaffolding / P4 recovery hooks)."""
        self._tracked = self._projection.establish(self._tracked, literal)
