"""The stub NL track (contract :238) — a PEER reasoning track, never the executor.

One `propose()` cycle: interpret the task → update the semantic belief from the canonical
snapshot → ask the SkillSelector through the seam → one repair attempt if malformed →
translate with residual. The result is a typed `NLProposal` for the P4 orchestrator/track
comparator: a call (or a standing MalformedCall) plus the coverage and confidence evidence.

Structural guarantees, not conventions:
  - this package cannot import the backend, the adapter, dspy, or `runtime`
    (auto-discovered guard in tests/test_no_backend_imports.py) — the NL track CANNOT execute;
  - the symbolic track cannot import this package and vice versa (peer-isolation guard in
    tests/test_p3_nl.py) — the NL track cannot become the symbolic planner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
class NLProposal:
    """The NL track's answer for one executive cycle."""
    call: Optional[GroundedSkillCall]
    malformed: Optional[MalformedCall]
    coverage: CoverageReport
    confidence: Optional[ConfidenceReport]
    repaired: bool

    def __post_init__(self) -> None:
        if (self.call is None) == (self.malformed is None):
            raise ValueError("an NLProposal carries exactly one of call | malformed")


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
            return NLProposal(
                call=None, malformed=proposed,
                coverage=interpreted.coverage, confidence=None, repaired=False,
            )
        translated = translate_proposal(proposed)
        coverage = CoverageReport(
            covered=interpreted.coverage.covered + translated.coverage.covered,
            residual=interpreted.coverage.residual + translated.coverage.residual,
            note="task interpretation + proposal translation",
        )
        return NLProposal(
            call=proposed, malformed=None,
            coverage=coverage, confidence=translated.confidence, repaired=repaired,
        )
