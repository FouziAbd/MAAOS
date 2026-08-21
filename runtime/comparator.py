"""The track comparator (:70, :250): NL-vs-symbolic evidence, never environment-vs-model.

Consumes the NL track's typed `NLProposal` (coverage + confidence evidence) and the symbolic
track's selected call, and emits `TrackDivergence` — the ONLY component that may raise that
channel. It never classifies an environment-vs-model issue (that is `ExecutionDiscrepancy`,
owned by the monitor) and never blocks execution by itself: divergences are evidence for the
orchestrator/trace.

Kind assignment (shared/divergence.py):
  - COVERAGE_GAP            — the NL proposal names a skill the symbolic model cannot express
                              (Explore/Wait — Decision 15), or the NL track could produce no
                              well-formed proposal at all.
  - TRANSLATION_RESIDUAL    — the coverage report carries residual clauses (task text the V1
                              vocabulary cannot represent) while a proposal exists.
  - CONTRADICTION           — both tracks propose, and the proposals differ in skill/box/zone.
  - BENIGN_ABSTRACTION_MISMATCH — same skill/box/zone, different agent binding only: under
                              Decision 6's non-exclusive optimism either binding is
                              symbolically equivalent.
  - CONFIDENCE_MISMATCH     — the NL confidence is below `LOW_CONFIDENCE` while the symbolic
                              track holds a plan.
"""
from __future__ import annotations

from typing import Optional, Tuple

from shared.divergence import DivergenceKind, TrackDivergence
from shared.skills import GroundedSkillCall, REGISTRY

from nl.track import NLProposal

LOW_CONFIDENCE = 0.75


def compare_tracks(
    symbolic_call: Optional[GroundedSkillCall],
    nl_proposal: Optional[NLProposal],
) -> Tuple[TrackDivergence, ...]:
    if nl_proposal is None:
        return ()
    divergences = []

    if nl_proposal.malformed is not None:
        divergences.append(TrackDivergence(
            kind=DivergenceKind.COVERAGE_GAP,
            message="NL track produced no well-formed proposal this cycle",
            nl_view=f"standing MalformedCall: {nl_proposal.malformed.reason}",
            symbolic_view=str(symbolic_call) if symbolic_call else "no symbolic selection",
        ))
        return tuple(divergences)

    call = nl_proposal.call
    if call.skill not in REGISTRY.symbolic_action_set():
        divergences.append(TrackDivergence(
            kind=DivergenceKind.COVERAGE_GAP,
            message=f"NL proposes {call.skill}, outside the V1 symbolic model (Decision 15)",
            nl_view=str(call),
            symbolic_view=str(symbolic_call) if symbolic_call else "no symbolic selection",
            residual=nl_proposal.coverage.residual,
        ))
    elif nl_proposal.coverage.residual:
        divergences.append(TrackDivergence(
            kind=DivergenceKind.TRANSLATION_RESIDUAL,
            message="task text carries clauses outside the V1 vocabulary",
            nl_view=str(call),
            symbolic_view=str(symbolic_call) if symbolic_call else "no symbolic selection",
            residual=nl_proposal.coverage.residual,
        ))

    if symbolic_call is not None and call.skill in REGISTRY.symbolic_action_set():
        if call == symbolic_call:
            pass
        elif (call.skill, call.box, call.zone) == (
            symbolic_call.skill, symbolic_call.box, symbolic_call.zone
        ):
            divergences.append(TrackDivergence(
                kind=DivergenceKind.BENIGN_ABSTRACTION_MISMATCH,
                message="same skill/box/zone, different agent binding — symbolically "
                        "equivalent under non-exclusive optimism (Decision 6)",
                nl_view=str(call), symbolic_view=str(symbolic_call),
            ))
        else:
            divergences.append(TrackDivergence(
                kind=DivergenceKind.CONTRADICTION,
                message="tracks propose different actions",
                nl_view=str(call), symbolic_view=str(symbolic_call),
            ))

    if (
        symbolic_call is not None
        and nl_proposal.confidence is not None
        and nl_proposal.confidence.confidence < LOW_CONFIDENCE
    ):
        divergences.append(TrackDivergence(
            kind=DivergenceKind.CONFIDENCE_MISMATCH,
            message=f"NL confidence {nl_proposal.confidence.confidence} below "
                    f"{LOW_CONFIDENCE} while the symbolic track holds a plan",
            nl_view=nl_proposal.confidence.rationale,
            symbolic_view=str(symbolic_call),
        ))
    return tuple(divergences)
