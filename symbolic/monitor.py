"""The V1 monitor: prediction vs normalized authoritative execution, on BOTH bases.

Decision 13, clauses 6-8, implemented:

  - SUCCESS is checked against BOTH bases where each exists: the monitored symbolic projection
    (`ProjectionContract.agrees`) and the predicted world candidates (`world_key` membership —
    membership, because `CooperativePush`'s terminal slots are declared as a SET). A successful
    transition that matches neither declaration is a `STATE_EFFECT_MISMATCH` carrying the
    correctly-typed key pair(s) for the basis that disagreed.
  - A NON-success of a symbolically applicable skill stands on the authoritative typed outcome
    alone (clause 7): `EXECUTION_FAILURE_OF_APPLICABLE_SKILL`, no comparison pair required.
    This is the expected V1 signal (:139) — NEVER a reason to strengthen applicability.
  - A skill OUTSIDE the symbolic model (Decision 15) has no prediction, so no
    `STATE_EFFECT_MISMATCH` can exist for it; its failures are `UNEXPECTED_OUTCOME` on the
    outcome alone.

The monitor never mutates applicability, the belief, or the model — it reports. What the
orchestrator does with the report is P4.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.execution import ExecutionOutcome, ExecutionResult
from shared.skill_ir import DomainIR
from shared.skills import GroundedSkillCall, OutsideSymbolicModel
from shared.state_snapshot import StateSnapshot
from shared.symbolic_state import ProjectionContract, SymbolicState
from shared.versioning import ModelVersion

from symbolic.predictor import predict_symbolic, predict_world_candidates


def monitor_execution(
    domain: DomainIR,
    projection: ProjectionContract,
    project: Callable[[StateSnapshot], SymbolicState],
    pre_symbolic: SymbolicState,
    result: ExecutionResult,
    zone,
    model_version: Optional[ModelVersion] = None,
) -> Tuple[ExecutionDiscrepancy, ...]:
    """Compare one executed attempt against the model's predictions.

    `pre_symbolic` is the belief state the attempt was chosen under (projection + tracked
    fluents) — the prediction base. The observed side is always the authoritative
    `result.post_state`, never the belief.

    P4 OBLIGATION (decisions §19.1 item 4): a zone-identity mismatch raises a bare `ValueError`
    from the predictor here (a wiring error, unreachable with the single frozen V1 zone). The
    runtime loop must convert that escape to an `InfrastructureFault` — the same conversion rule
    `PlannerFailure` gets — never swallow it and never treat it as a discrepancy.
    """
    call = result.call
    succeeded = result.outcome is ExecutionOutcome.SUCCESS

    if isinstance(domain.resolve(call.skill), OutsideSymbolicModel):
        if succeeded:
            return ()
        return (ExecutionDiscrepancy(
            kind=DiscrepancyKind.UNEXPECTED_OUTCOME,
            call=call,
            message=f"registry-only skill {call.skill} did not succeed: outcome="
                    f"{result.outcome}, raw={result.raw_label}",
            model_version=model_version,
        ),)

    if not succeeded:
        # Clause 7: the authoritative outcome IS the evidence. No state comparison needed, and
        # none is attempted — a failed attempt's post-state trivially differs from the success
        # prediction, and reporting that too would be noise, not signal.
        return (ExecutionDiscrepancy(
            kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL,
            call=call,
            message=f"symbolically applicable {call.skill} failed in the backend: outcome="
                    f"{result.outcome}, raw={result.raw_label}, "
                    f"failure_class={result.failure_class}, detail={result.detail!r}",
            model_version=model_version,
        ),)

    discrepancies = []

    # ── symbolic basis ────────────────────────────────────────────────────────────
    predicted_symbolic = predict_symbolic(domain, pre_symbolic, call)
    observed_symbolic = project(result.post_state)
    if predicted_symbolic is not None and not projection.agrees(
        predicted_symbolic, observed_symbolic
    ):
        only_predicted, only_observed = projection.monitored_view(
            predicted_symbolic
        ).difference(projection.monitored_view(observed_symbolic))
        discrepancies.append(ExecutionDiscrepancy(
            kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
            call=call,
            predicted_symbolic_key=projection.monitored_key(predicted_symbolic),
            observed_symbolic_key=projection.monitored_key(observed_symbolic),
            message=f"monitored symbolic mismatch on success: predicted-only="
                    f"{only_predicted}, observed-only={only_observed}",
            model_version=model_version,
        ))

    # ── world basis ───────────────────────────────────────────────────────────────
    candidates = predict_world_candidates(result.pre_state, call, zone)
    if candidates:
        observed_key = result.post_state.world_key()
        candidate_keys = tuple(c.world_key() for c in candidates)
        if observed_key not in candidate_keys:
            extra = (
                f"; {len(candidate_keys) - 1} alternative admissible candidate(s): "
                + ", ".join(k[:16] for k in candidate_keys[1:])
                if len(candidate_keys) > 1 else ""
            )
            discrepancies.append(ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH,
                call=call,
                predicted_world_key=candidate_keys[0],
                observed_world_key=observed_key,
                message="successful execution does not match any predicted world effect"
                        + extra,
                model_version=model_version,
            ))

    return tuple(discrepancies)
