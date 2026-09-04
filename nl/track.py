"""The stub NL track (contract :238) — a PEER reasoning track, never the executor.

One `propose()` cycle: interpret the task → update the semantic belief from the canonical
snapshot → ask the SkillSelector through the seam → one repair attempt if malformed →
translate with residual. The result is a typed `NLProposal` for the P4 orchestrator/track
comparator — since R6 (report Phase 6 item 3) a DISCRIMINATED union of two variants:
`GroundedProposal` (a call with the coverage and confidence evidence of its translation) or
`MalformedProposal` (the standing MalformedCall with the task-interpretation coverage). Static
typing proves which one a consumer holds after an `isinstance` check; the former single class
encoded the same invariant as two mutually-exclusive optional fields checked only at runtime.
Both variants keep the read surface the runtime's `AdvisoryProposal` contract records
(`call` / `coverage` / `confidence`), so the trace columns are unchanged.

Structural guarantees, not conventions:
  - this package cannot import the backend, the adapter, dspy, or `runtime`
    (auto-discovered guard in tests/test_no_backend_imports.py) — the NL track CANNOT execute;
  - the symbolic track cannot import this package and vice versa (peer-isolation guard in
    tests/test_p3_nl.py) — the NL track cannot become the symbolic planner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypeAlias

from shared.execution import ExecutionOutcome
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import GroundedSkillCall, MalformedCall
from shared.state_snapshot import StateSnapshot
from shared.task import Task

from nl.repair import RepairSkillCall
from nl.seam import LMSeam
from nl.semantic_belief import SemanticBelief, update_belief
from nl.skill_selector import SkillSelector
from nl.task_interpreter import interpret_task
from nl.translator import translate_proposal


@dataclass(frozen=True, slots=True)
class GroundedProposal:
    """The NL track's answer for one executive cycle when it produced a well-formed call:
    the call, the merged task-interpretation + translation coverage, the translation's
    confidence evidence, and whether the one repair attempt was needed."""
    call: GroundedSkillCall
    coverage: CoverageReport
    confidence: ConfidenceReport
    repaired: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.call, GroundedSkillCall):
            raise TypeError(
                f"GroundedProposal requires a GroundedSkillCall, got "
                f"{type(self.call).__name__}; a proposal without a call is a MalformedProposal"
            )
        if not isinstance(self.coverage, CoverageReport):
            raise TypeError("GroundedProposal requires a CoverageReport")
        if not isinstance(self.confidence, ConfidenceReport):
            raise TypeError("GroundedProposal requires a ConfidenceReport")

    @property
    def malformed(self) -> None:
        """A grounded proposal carries no standing malformed call (typed None)."""
        return None


@dataclass(frozen=True, slots=True)
class MalformedProposal:
    """The NL track's answer when the model's output stayed malformed after the one repair
    attempt: the standing `MalformedCall` (never rewritten into another skill) plus the
    task-interpretation coverage, which is evidence independent of the call and is still
    reported by the comparator (R3 item 6)."""
    malformed: MalformedCall
    coverage: CoverageReport

    def __post_init__(self) -> None:
        if not isinstance(self.malformed, MalformedCall):
            raise TypeError(
                f"MalformedProposal requires a MalformedCall, got "
                f"{type(self.malformed).__name__}"
            )
        if not isinstance(self.coverage, CoverageReport):
            raise TypeError("MalformedProposal requires a CoverageReport")

    @property
    def call(self) -> None:
        """No well-formed call this cycle (typed None — the runtime's proposal column)."""
        return None

    @property
    def confidence(self) -> None:
        """Nothing was translated, so there is no translation confidence (typed None)."""
        return None


#: The NL track's proposal type: exactly one of the two variants. `isinstance` against either
#: variant narrows statically; `isinstance(x, NLProposal)` also works at runtime (PEP 604).
NLProposal: TypeAlias = GroundedProposal | MalformedProposal


class NLTrack:
    """Stateful only in the semantic belief; every proposal is otherwise pure."""

    def __init__(self, seam: LMSeam) -> None:
        self._selector = SkillSelector(seam)
        self._repair = RepairSkillCall(seam)
        self.belief = SemanticBelief()

    def observe(
        self,
        snapshot: StateSnapshot,
        last_skill: Optional[str] = None,
        last_outcome: Optional[ExecutionOutcome] = None,
    ) -> None:
        self.belief = update_belief(self.belief, snapshot, last_skill, last_outcome)

    def propose(self, task: Task) -> NLProposal:
        if not self.belief.facts:
            # mirror of ExactSymbolicBelief's sync-before-use rule: proposing with no observed
            # situation would silently ask the model about nothing
            raise RuntimeError("NLTrack.observe(snapshot) must be called before propose()")
        interpreted = interpret_task(task)
        proposed = self._selector.propose(interpreted, self.belief)
        repaired = False
        if isinstance(proposed, MalformedCall):
            proposed = self._repair.repair(proposed)
            repaired = not isinstance(proposed, MalformedCall)
        if isinstance(proposed, MalformedCall):
            return MalformedProposal(malformed=proposed, coverage=interpreted.coverage)
        translated = translate_proposal(proposed)
        coverage = CoverageReport(
            covered=interpreted.coverage.covered + translated.coverage.covered,
            residual=interpreted.coverage.residual + translated.coverage.residual,
            note="task interpretation + proposal translation",
        )
        return GroundedProposal(
            call=proposed, coverage=coverage, confidence=translated.confidence,
            repaired=repaired,
        )
