"""The default proposal comparator (DK2) — `shared.contracts.ProposalComparator` over the
frozen `TrackDivergence` channel, for any domain whose advisory proposal satisfies
`shared.contracts.AdvisoryProposal` (`call` / `coverage` / `confidence`).

What it reports BY DEFAULT is the intersection of `app/comparator.py::BoxPushActionComparator`
and `tests/probe_counter.py::CounterActionComparator`:

    no proposal                      -> empty report (genuine absence)
    proposal without a call          -> PROPOSAL_FORM / COVERAGE_GAP
    proposed call != symbolic call   -> ACTION_CHOICE / CONTRADICTION
    same call                        -> empty report (genuine agreement)

The three BoxPush-only arms are OPT-IN configuration, never hidden defaults:

    equivalence=<ActionEquivalence>          a different-but-equivalent call becomes
                                             ACTION_CHOICE / BENIGN_ABSTRACTION_MISMATCH
                                             with the domain's reason (R3 item 3)
    low_confidence_threshold=<float>         a proposal below it, while the symbolic side
                                             holds a call, adds CONFIDENCE / CONFIDENCE_MISMATCH
    report_translation_residual=True         a coverage residual adds TASK_TRANSLATION /
                                             TRANSLATION_RESIDUAL

Evidence duties (frozen): the comparator is the ONLY producer of `TrackDivergence`; it never
classifies an environment-vs-model issue, never touches the backend, never selects an action.
Severity is descriptive V1 evidence, never a calibrated probability.
"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar, cast

from shared.contracts.comparison import (
    ActionEquivalence,
    ComparedAspect,
    ComparisonFinding,
    ComparisonReport,
    FindingSeverity,
)
from shared.divergence import DivergenceKind, TrackDivergence
from shared.value_contracts import AdvisoryProposal, RuntimeCall

CallT = TypeVar("CallT", bound=RuntimeCall)
ProposalT = TypeVar("ProposalT", bound=AdvisoryProposal)


def _finding(
    aspect: ComparedAspect, severity: FindingSeverity, **divergence_fields
) -> ComparisonFinding:
    return ComparisonFinding(
        aspect=aspect, severity=severity, divergence=TrackDivergence(**divergence_fields)
    )


class DefaultProposalComparator(Generic[CallT, ProposalT]):
    """Kind assignment over the frozen channel; domain rules and thresholds are opt-in."""

    def __init__(
        self,
        equivalence: Optional[ActionEquivalence[CallT]] = None,
        *,
        low_confidence_threshold: Optional[float] = None,
        report_translation_residual: bool = False,
    ) -> None:
        if low_confidence_threshold is not None and not 0.0 <= low_confidence_threshold <= 1.0:
            raise ValueError("low_confidence_threshold must be within [0.0, 1.0]")
        self.equivalence = equivalence
        self.low_confidence_threshold = low_confidence_threshold
        self.report_translation_residual = report_translation_residual

    def compare(
        self, symbolic_call: Optional[CallT], nl_proposal: Optional[ProposalT], /
    ) -> ComparisonReport:
        if nl_proposal is None:
            return ComparisonReport()
        symbolic_view = str(symbolic_call) if symbolic_call is not None else "no symbolic selection"
        coverage = nl_proposal.coverage
        residual = tuple(coverage.residual) if coverage is not None else ()
        findings = []

        call = nl_proposal.call
        if call is None:
            findings.append(_finding(
                ComparedAspect.PROPOSAL_FORM, FindingSeverity.ATTENTION,
                kind=DivergenceKind.COVERAGE_GAP,
                message="the advisory track produced no well-formed proposal this cycle",
                nl_view="no well-formed proposal", symbolic_view=symbolic_view,
                residual=residual,
            ))
        if self.report_translation_residual and residual:
            # R3 item 6 (BoxPush): a residual is reported even when the proposal is malformed
            findings.append(_finding(
                ComparedAspect.TASK_TRANSLATION, FindingSeverity.ATTENTION,
                kind=DivergenceKind.TRANSLATION_RESIDUAL,
                message="task content outside the symbolic vocabulary",
                nl_view=str(call) if call is not None else "no well-formed proposal",
                symbolic_view=symbolic_view, residual=residual,
            ))
        if call is None:
            # nothing else is comparable without a call (BoxPush returns here too)
            return ComparisonReport(findings=tuple(findings))

        if symbolic_call is not None and call != symbolic_call:
            # `AdvisoryProposal.call` is typed on the neutral RuntimeCall; the domain's
            # equivalence rule sees the domain's own call type (the track proposes it)
            reason = (
                self.equivalence.benign_equivalence(cast(CallT, call), symbolic_call)
                if self.equivalence is not None else None
            )
            if reason is not None:
                findings.append(_finding(
                    ComparedAspect.ACTION_CHOICE, FindingSeverity.BENIGN,
                    kind=DivergenceKind.BENIGN_ABSTRACTION_MISMATCH, message=reason,
                    nl_view=str(call), symbolic_view=str(symbolic_call),
                ))
            else:
                findings.append(_finding(
                    ComparedAspect.ACTION_CHOICE, FindingSeverity.ATTENTION,
                    kind=DivergenceKind.CONTRADICTION,
                    message="tracks propose different actions",
                    nl_view=str(call), symbolic_view=str(symbolic_call),
                ))

        confidence = nl_proposal.confidence
        if (
            self.low_confidence_threshold is not None
            and symbolic_call is not None
            and confidence is not None
            and confidence.confidence < self.low_confidence_threshold
        ):
            findings.append(_finding(
                ComparedAspect.CONFIDENCE, FindingSeverity.ATTENTION,
                kind=DivergenceKind.CONFIDENCE_MISMATCH,
                message=f"advisory confidence {confidence.confidence} below "
                        f"{self.low_confidence_threshold} while the symbolic track holds a call",
                nl_view=confidence.rationale, symbolic_view=str(symbolic_call),
            ))
        return ComparisonReport(findings=tuple(findings))


__all__ = ["DefaultProposalComparator"]
