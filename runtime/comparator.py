"""The BoxPush action-proposal comparator (:70, :250) — R3-scoped (report Phase 3 items 2-6).

`BoxPushActionComparator` is the current V1 comparison, explicitly named for what it
compares: ACTION PROPOSALS in BoxPush V1, nothing more. It conforms to the generic
`shared.contracts.ProposalComparator` protocol and emits a structured `ComparisonReport`
whose findings wrap the frozen `TrackDivergence` payloads — the serialized trace channel is
byte-identical to the pre-R3 comparator for identical inputs.

R3 restructuring, item by item:
  - item 2: the module function became this scoped class; `compare_tracks` remains as the
    legacy divergence-tuple surface over a default instance.
  - item 3: the different-agent-binding rule lives in the domain
    (`domain.box_push_v1.BoxPushActionEquivalence`), injected as the `ActionEquivalence`
    contract — this module holds NO agent/box/zone rule (pinned by an AST scan in
    tests/test_r3_comparison.py).
  - item 4: the low-confidence threshold is constructor configuration
    (`low_confidence_threshold`, default `LOW_CONFIDENCE`); the raw confidence and its
    source stay in the `ConfidenceReport` evidence — descriptive, never calibrated.
  - item 6: a malformed proposal no longer returns early — independent findings that do not
    need a well-formed call (the task-translation residual) are still reported.

Evidence duties (frozen): consumes the NL track's typed `NLProposal` and the symbolic
track's candidate call, and emits `TrackDivergence` — the ONLY component that may raise
that channel. It never classifies an environment-vs-model issue (that is
`ExecutionDiscrepancy`, owned by the monitor), never touches the backend, and never
selects an action: reports inform the policy (R3 lifecycle), they decide nothing.

Kind assignment (shared/divergence.py) — unchanged from the accepted V1 comparator:
  - COVERAGE_GAP            — the NL proposal names a skill the symbolic model cannot express
                              (Explore/Wait — Decision 15), or the NL track could produce no
                              well-formed proposal at all.
  - TRANSLATION_RESIDUAL    — the coverage report carries residual clauses (task text the V1
                              vocabulary cannot represent).
  - CONTRADICTION           — both tracks propose, and the proposals are neither identical
                              nor domain-equivalent.
  - BENIGN_ABSTRACTION_MISMATCH — the domain equivalence rule accepts the difference.
  - CONFIDENCE_MISMATCH     — the NL confidence is below the configured threshold while the
                              symbolic track holds a plan.

DEFERRED(R4): this BoxPush-scoped component still lives in `runtime/` and imports the
concrete domain equivalence for its default; the composition root owns relocating and
injecting it.
"""
from __future__ import annotations

from typing import Optional, Tuple

from shared.contracts.comparison import (
    ComparedAspect,
    ComparisonFinding,
    ComparisonReport,
    FindingSeverity,
)
from shared.contracts.comparison import ActionEquivalence
from shared.divergence import DivergenceKind, TrackDivergence
from shared.skills import GroundedSkillCall, REGISTRY

from domain.box_push_v1 import BoxPushActionEquivalence
from nl.track import NLProposal

LOW_CONFIDENCE = 0.75          # the documented V1 default; configuration, not a hidden rule


def _finding(
    aspect: ComparedAspect, severity: FindingSeverity, **divergence_fields
) -> ComparisonFinding:
    return ComparisonFinding(
        aspect=aspect, severity=severity, divergence=TrackDivergence(**divergence_fields)
    )


class BoxPushActionComparator:
    """Scoped V1 action-proposal comparison behind the generic ProposalComparator contract."""

    def __init__(
        self,
        equivalence: ActionEquivalence,
        *,
        low_confidence_threshold: float = LOW_CONFIDENCE,
    ) -> None:
        if not 0.0 <= low_confidence_threshold <= 1.0:
            raise ValueError("low_confidence_threshold must be within [0.0, 1.0]")
        self.equivalence = equivalence
        self.low_confidence_threshold = low_confidence_threshold

    def compare(
        self,
        symbolic_call: Optional[GroundedSkillCall],
        nl_proposal: Optional[NLProposal],
        /,
    ) -> ComparisonReport:
        if nl_proposal is None:
            return ComparisonReport()
        symbolic_view = str(symbolic_call) if symbolic_call else "no symbolic selection"
        findings = []

        if nl_proposal.malformed is not None:
            findings.append(_finding(
                ComparedAspect.PROPOSAL_FORM, FindingSeverity.ATTENTION,
                kind=DivergenceKind.COVERAGE_GAP,
                message="NL track produced no well-formed proposal this cycle",
                nl_view=f"standing MalformedCall: {nl_proposal.malformed.reason}",
                symbolic_view=symbolic_view,
            ))
            # item 6: no early return — findings that need no well-formed call still stand
            if nl_proposal.coverage.residual:
                findings.append(_finding(
                    ComparedAspect.TASK_TRANSLATION, FindingSeverity.ATTENTION,
                    kind=DivergenceKind.TRANSLATION_RESIDUAL,
                    message="task text carries clauses outside the V1 vocabulary",
                    nl_view=f"standing MalformedCall: {nl_proposal.malformed.reason}",
                    symbolic_view=symbolic_view,
                    residual=nl_proposal.coverage.residual,
                ))
            return ComparisonReport(findings=tuple(findings))

        call = nl_proposal.call
        in_model = call.skill in REGISTRY.symbolic_action_set()
        if not in_model:
            findings.append(_finding(
                ComparedAspect.MODEL_COVERAGE, FindingSeverity.ATTENTION,
                kind=DivergenceKind.COVERAGE_GAP,
                message=f"NL proposes {call.skill}, outside the V1 symbolic model (Decision 15)",
                nl_view=str(call), symbolic_view=symbolic_view,
                residual=nl_proposal.coverage.residual,
            ))
        elif nl_proposal.coverage.residual:
            findings.append(_finding(
                ComparedAspect.TASK_TRANSLATION, FindingSeverity.ATTENTION,
                kind=DivergenceKind.TRANSLATION_RESIDUAL,
                message="task text carries clauses outside the V1 vocabulary",
                nl_view=str(call), symbolic_view=symbolic_view,
                residual=nl_proposal.coverage.residual,
            ))

        if symbolic_call is not None and in_model and call != symbolic_call:
            reason = self.equivalence.benign_equivalence(call, symbolic_call)
            if reason is not None:
                findings.append(_finding(
                    ComparedAspect.ACTION_CHOICE, FindingSeverity.BENIGN,
                    kind=DivergenceKind.BENIGN_ABSTRACTION_MISMATCH,
                    message=reason,
                    nl_view=str(call), symbolic_view=str(symbolic_call),
                ))
            else:
                findings.append(_finding(
                    ComparedAspect.ACTION_CHOICE, FindingSeverity.ATTENTION,
                    kind=DivergenceKind.CONTRADICTION,
                    message="tracks propose different actions",
                    nl_view=str(call), symbolic_view=str(symbolic_call),
                ))

        if (
            symbolic_call is not None
            and nl_proposal.confidence is not None
            and nl_proposal.confidence.confidence < self.low_confidence_threshold
        ):
            findings.append(_finding(
                ComparedAspect.CONFIDENCE, FindingSeverity.ATTENTION,
                kind=DivergenceKind.CONFIDENCE_MISMATCH,
                message=f"NL confidence {nl_proposal.confidence.confidence} below "
                        f"{self.low_confidence_threshold} while the symbolic track holds a plan",
                nl_view=nl_proposal.confidence.rationale,
                symbolic_view=str(symbolic_call),
            ))
        return ComparisonReport(findings=tuple(findings))


# The default V1 composition: domain equivalence + documented default threshold.
DEFAULT_COMPARATOR = BoxPushActionComparator(BoxPushActionEquivalence())


def compare_tracks(
    symbolic_call: Optional[GroundedSkillCall],
    nl_proposal: Optional[NLProposal],
) -> Tuple[TrackDivergence, ...]:
    """Legacy divergence-tuple surface over the default comparator (pre-R3 signature)."""
    return DEFAULT_COMPARATOR.compare(symbolic_call, nl_proposal).divergences
