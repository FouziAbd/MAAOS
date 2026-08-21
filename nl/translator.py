"""Translator with explicit residual (contract :227; :25).

Maps one typed NL proposal into the symbolic vocabulary and reports EXACTLY what could not be
carried over. For the V1 skill set the lossy case is real, not hypothetical: `Explore`/`Wait`
are registry-valid but have NO symbolic model (Decision 15), so a proposal naming them
translates with a residual — the track comparator's COVERAGE_GAP evidence (P4), reported here,
raised there. The translator never rewrites a proposal to make it translatable.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import REGISTRY, GroundedSkillCall

#: DERIVED from the frozen registry, never hand-maintained (the registry's
#: `in_symbolic_action_set` metadata is itself cross-checked against `DOMAIN_IR.action_set()`
#: by tests/test_prediction_and_monitoring.py) — a literal here was the P0 vocabulary-drift sin.
_SYMBOLIC_SKILLS = frozenset(REGISTRY.symbolic_action_set())


@dataclass(frozen=True, slots=True)
class TranslatedProposal:
    call: GroundedSkillCall
    symbolic_form: str                 # the grounded-call key — the shared vocabulary
    coverage: CoverageReport
    confidence: ConfidenceReport


def translate_proposal(call: GroundedSkillCall) -> TranslatedProposal:
    if call.skill in _SYMBOLIC_SKILLS:
        coverage = CoverageReport(
            covered=(call.key(),),
            note="fully expressible in the frozen symbolic vocabulary",
        )
        confidence = ConfidenceReport(
            source="nl", confidence=1.0,
            rationale="typed call over frozen identities; nothing lossy",
        )
    else:
        coverage = CoverageReport(
            covered=(),
            residual=(
                f"{call.skill.value} is outside the V1 symbolic model (Decision 15): "
                f"the symbolic track can neither plan nor predict it",
            ),
            note="executable, but symbolically uncovered",
        )
        confidence = ConfidenceReport(
            source="nl", confidence=0.5,
            rationale="proposal names a skill with no symbolic model; only the authoritative "
                      "outcome can evaluate it",
        )
    return TranslatedProposal(
        call=call, symbolic_form=call.key(), coverage=coverage, confidence=confidence
    )
