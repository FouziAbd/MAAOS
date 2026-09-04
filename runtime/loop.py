"""The executive loop manager (:35, :252-255): owns the cycle, the budgets, and the wiring.

One cycle: budget gate -> sync -> plan -> ground -> validate -> orchestrate -> execute ->
record -> monitor -> compare -> trace. Every distinction the earlier phases froze is enacted
here, with the P4-binding decisions from `docs/decisions/P0_V1_DECISIONS.md` §19.1:

  - gating happens on the typed `CallValidation`, in the loop — the executor gates nothing
    (§19.1 item 2);
  - the monitor is wired on the BELIEF the attempt was chosen under, never a re-projection
    (§19.1 item 3), and its `ValueError` escape is wrapped into an `InfrastructureFault`
    (§19.1 item 4);
  - GROUNDING-BEFORE-APPLICABILITY (§19.1 item 5, decided here): identities are checked
    against the authoritative snapshot BEFORE symbolic applicability, so a ghost call routes
    as the typed `UngroundedCall -> MISSING_GROUNDING` fault (Decision 7), never as a quiet
    symbolic verdict. Planner output is always grounded; this gate guards recovery/NL calls.
  - case-(c) budget charging: a mid-execution fault consumed one executive step and
    `primitive_steps_before_failure=N` primitives recorded only in `fault.detail`; the loop
    charges BOTH on top of the recorded-accounting sums (`runtime/executive_history.py`).
  - DECIDED (P4): case-(c) faulted attempts do NOT feed the repeated-failure counts — faults
    escalate through the fault channel (`halt_on_infrastructure_fault`; the history's
    `faults_since` accessor exists for cycle logic but the V1 loop does not yet consume it —
    :163 is permissive), failures through `failure_count`. One attempt never escalates
    through both channels.

R4 (report Phase 4): this module is the GENERIC runtime core. It imports only `shared`
contracts and the domain-independent runtime helpers; every domain-owned operation
(planning, grounding, applicability, prediction, monitoring, the model version) reaches it
through the injected `DomainServices`, the symbolic belief through the injected
`SymbolicTrack`, and the comparator / recovery provider / policy through their own
contracts. The loop names no domain concept: it never reads an agent, box, or zone. The
BoxPush application is assembled in the composition root `app/box_push_v1.py`; the import
boundary is enforced by `tests/test_r4_composition.py`.

R6 (report Phase 6 acceptance "core contracts, runtime ... pass static type checking"): the
loop is generic in the five domain-owned types it handles — authoritative state, symbolic
state, call, task, advisory proposal — bounded by the structural value protocols
(`shared/value_contracts.py`) where it reads members, and every injected collaborator is
typed at those parameters. The composition root fixes them
(`ExecutiveLoopManager[StateSnapshot, SymbolicState, GroundedSkillCall, Task, NLProposal]`);
the R5 probe fixes its own. The loop names no concrete type of any domain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, List, Optional, Tuple

from shared.contracts import (
    AdvisoryProposal,
    DomainServices,
    Environment,
    Halt,
    OrchestrationContext,
    OrchestrationPolicyContract,
    PreliminaryContext,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    Replan,
    RequestProposal,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
    TrackRequest,
)
from shared.discrepancy import ExecutionDiscrepancy
from shared.execution import ExecutionOutcome, ExecutionResult
from shared.faults import InfrastructureFault, InfrastructureFaultError, FaultKind
from shared.orchestration_config import ExecutiveDecision, OrchestrationConfig
from shared.planner_result import PlanFound, PlannerFailure, PlannerResult
from shared.skills import (
    MalformedCall,
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)
from shared.trace_schema import TraceEntry
from shared.versioning import Provenance

from runtime.executive_history import ExecutiveHistory
from runtime.executor import ExecutionAttempt, execute
from runtime.policies import build_policy

_CASE_C_KEY = re.compile(r"primitive_steps_before_failure=(\d+)")


class EpisodeOutcome(StrEnum):
    GOAL_REACHED = "goal_reached"
    HALTED_NO_PLAN = "halted_no_plan"
    HALTED_REPEATED_FAILURE = "halted_repeated_failure"
    FAULTED = "faulted"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class EpisodeResult[StateT: RuntimeState, CallT: RuntimeCall, TaskT: TaskContract]:
    outcome: EpisodeOutcome
    reason: str
    history: ExecutiveHistory[StateT, CallT, TaskT]
    discrepancies: Tuple[ExecutionDiscrepancy[CallT], ...] = field(default_factory=tuple)


class ExecutiveLoopManager[
    StateT: RuntimeState,
    SymbolicStateT,
    CallT: RuntimeCall,
    TaskT: TaskContract,
    ProposalT: AdvisoryProposal,
]:
    """Deterministic sequential V1 executive loop over an injected `Environment`.

    Every variable component arrives by INJECTION (R4 completes what R2 began):

      - `env`: this package cannot import the backend (the fail-closed import guard), which
        structurally separates the loop from any concrete environment.
      - `domain` (keyword-only, required): the `DomainServices` bundle — planning,
        grounding, applicability, prediction, monitoring, model version. The loop holds no
        domain constant and applies no domain function of its own.
      - `symbolic_track` (keyword-only, required): the belief-holding `SymbolicTrack`,
        synced from the authoritative state before every use.
      - `policy` (R2): any `OrchestrationPolicyContract` object, or omit it and the
        registry in `runtime/policies.py` builds the one named by `config.policy` — the
        loop itself never dispatches on the policy enum.
      - `comparator` (R3 evidence, R4 injection): required whenever an `nl_track` is
        attached — a requested proposal must be comparable — and unused otherwise.
      - `recovery_provider`: consulted only on a REQUEST_PROPOSAL decision; with none
        injected, no recovery advice exists and the loop halts exactly as it does when the
        provider returns nothing.

    For the optional `nl_track`, `propose()` is consulted only when the policy's
    `required_inputs()` requests the advisory proposal; `observe()` feeds the attached
    track under ANY policy (data flows loop->NL only, LM-free), and an observe() failure is
    an infrastructure fault — so a SYMBOLIC_PRIMARY episode with an attached track can
    legitimately FAULT on it.

    A policy that overrides `decide()` owns re-declaring `required_inputs()`: the shipped
    policies derive their request from their own routing, and a subclass overriding only
    one of the two inherits a request that matches the BASE routing, not its own.

    The BoxPush assembly is `app.box_push_v1.build_loop`; this class is the same for any
    domain that supplies the contracts.
    """

    def __init__(
        self,
        env: Environment[StateT, CallT, ExecutionAttempt[StateT, CallT], object],
        task: TaskT,
        config: Optional[OrchestrationConfig] = None,
        nl_track: Optional[ReasoningTrack[StateT, TaskT, ProposalT]] = None,
        provenance: Optional[Provenance] = None,
        policy: Optional[OrchestrationPolicyContract[StateT, CallT, ProposalT]] = None,
        *,
        domain: DomainServices[StateT, SymbolicStateT, CallT],
        symbolic_track: SymbolicTrack[StateT, SymbolicStateT],
        comparator: Optional[ProposalComparator[CallT, ProposalT]] = None,
        recovery_provider: Optional[RecoveryProvider[CallT]] = None,
    ) -> None:
        if nl_track is not None and comparator is None:
            raise TypeError(
                "an attached nl_track requires an injected comparator: a requested "
                "proposal must be comparable — compose one at the application boundary"
            )
        self.env = env
        self.task = task
        self.config = config or OrchestrationConfig()
        self.policy = policy if policy is not None else build_policy(self.config)
        self.domain = domain
        self.comparator = comparator
        self.recovery_provider = recovery_provider
        self.nl_track = nl_track
        self.history: ExecutiveHistory[StateT, CallT, TaskT] = ExecutiveHistory()
        self.belief = symbolic_track
        self.provenance = provenance or Provenance(
            source="runtime/loop.py::ExecutiveLoopManager",
            model_version=domain.model_version,
        )
        # case-(c) charges live OUTSIDE the recorded accounting (see module docstring)
        self._extra_executive = 0
        self._extra_primitive = 0
        self._pending_recovery: Tuple[CallT, ...] = ()
        self._all_discrepancies: List[ExecutionDiscrepancy[CallT]] = []
        self._zero_progress_cycles = 0

    # ── budgets (recorded sums + case-(c) charges) ────────────────────────────────
    @property
    def executive_steps_charged(self) -> int:
        return self.history.executive_steps_used + self._extra_executive

    @property
    def primitive_steps_charged(self) -> int:
        return self.history.primitive_steps_used + self._extra_primitive

    def _budget_exhausted(self) -> Optional[str]:
        if self.executive_steps_charged >= self.config.executive_step_budget:
            return f"executive budget {self.config.executive_step_budget} exhausted"
        if self.primitive_steps_charged >= self.config.primitive_step_budget:
            return f"primitive budget {self.config.primitive_step_budget} exhausted"
        return None

    # ── wiring helpers ────────────────────────────────────────────────────────────
    def _sync(self) -> StateT:
        snapshot = self.env.export_full_state()
        self.belief.sync(snapshot)
        return snapshot

    def _plan(self, snapshot: StateT) -> PlannerResult:
        """The domain's plan channel for the current belief (the synced snapshot travels
        with it so the domain can fix its grounding universe)."""
        return self.domain.plan(self.belief.state, snapshot)

    def _monitor(
        self, pre_symbolic: SymbolicStateT, result: ExecutionResult[StateT, CallT]
    ) -> Tuple[Tuple[ExecutionDiscrepancy[CallT], ...], Optional[InfrastructureFault]]:
        """§19.1 items 3-4: belief in, ValueError wrapped out."""
        try:
            return self.domain.monitor(pre_symbolic, result), None
        except ValueError as error:
            return (), InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message=f"monitor raised untyped ValueError: {error}",
                source="runtime/loop.py::_monitor",
            )

    def _charge_case_c(self, fault: InfrastructureFault) -> None:
        match = _CASE_C_KEY.search(fault.detail)
        if match:                              # case (c): one executive step + N primitives
            self._extra_executive += 1
            self._extra_primitive += int(match.group(1))

    def _entry(self, step: int, snapshot: StateT, **kw: Any) -> TraceEntry[StateT, CallT, TaskT]:
        entry: TraceEntry[StateT, CallT, TaskT] = TraceEntry(
            executive_step=step, task=self.task, pre_state=snapshot,
            model_version=self.domain.model_version, provenance=self.provenance, **kw,
        )
        self.history.append(entry)
        return entry

    # ── the loop ──────────────────────────────────────────────────────────────────
    def run(self, *, seed: Optional[int] = None) -> EpisodeResult[StateT, CallT, TaskT]:
        self.env.reset(seed=seed)
        step = 0
        first = True
        while True:
            snapshot = self._sync()
            observe_fault: Optional[InfrastructureFault] = None
            if first and self.nl_track is not None:
                # the NL track observes the INITIAL situation too — without this, a real
                # NLTrack's observe-before-propose precondition silently discards every
                # episode's first advisory proposal (review W4)
                try:
                    self._observe(snapshot)
                    first = False               # only a SUCCESSFUL observe discharges it
                except InfrastructureFaultError as error:
                    # WARN-1 site 1: detected BEFORE any planning/execution this cycle —
                    # zero steps, world untouched, classified by POSITION at this site.
                    # The fault REPLACES the cycle (:163): goal/budget belong to the
                    # normal cycle and are re-checked next cycle; the shared liveness
                    # bookkeeping below bounds continue mode (zero-charge by construction).
                    observe_fault = error.fault
            if observe_fault is None:
                # DECIDED (review X10): on the exact tie the GOAL wins — the goal test is
                # free (no step charged), so reporting BUDGET_EXHAUSTED for a completed
                # task would be an accounting artifact, not a semantic outcome
                if self.task.is_satisfied_by(snapshot):
                    return self._finish(EpisodeOutcome.GOAL_REACHED, "task goal satisfied")
                exhausted = self._budget_exhausted()
                if exhausted:
                    return self._finish(EpisodeOutcome.BUDGET_EXHAUSTED, exhausted)

            charged_before = self.executive_steps_charged
            if observe_fault is not None:
                self._entry(step, snapshot, faults=(observe_fault,))
                outcome = self._maybe_fault_halt(observe_fault)
            else:
                outcome = self._run_cycle(step, snapshot)
            step += 1
            if outcome is not None:
                return outcome
            # LIVENESS GUARD (cross-cycle): budgets bound only CHARGED steps, so an episode
            # cycling through zero-charge outcomes (repeated inapplicable heads, or faults in
            # continue mode) would never terminate — the P4 harness demonstrated exactly that
            # with a disabled inapplicability check. This guard terminates UNCONDITIONALLY,
            # continue-mode included: it is an infrastructure bound on the loop itself,
            # never a symbolic feasibility predicate (:118).
            if self.executive_steps_charged == charged_before:
                self._zero_progress_cycles += 1
                # bound deliberately REUSES max_rejections_per_cycle: both bounds cap free
                # (zero-charge) repetition, one within a cycle, this one across cycles; a
                # dedicated field would require amending the frozen OrchestrationConfig
                if self._zero_progress_cycles > self.config.max_rejections_per_cycle:
                    fault = InfrastructureFault(
                        kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                        message=f"{self._zero_progress_cycles} consecutive zero-charge "
                                f"cycles — the loop is not progressing (liveness guard)",
                        source="runtime/loop.py::run",
                    )
                    # a FAULTED episode must carry its fault in the record (review W3).
                    # CONVENTION: this detection entry is stamped with the NEXT step index
                    # (step was already advanced) and the LAST synced snapshot — zero-charge
                    # cycles cannot change the world, so the snapshot is exact; the index is
                    # monotone and never collides with a run cycle.
                    self._entry(step, snapshot, faults=(fault,))
                    return self._finish(EpisodeOutcome.FAULTED, fault.message)
            else:
                self._zero_progress_cycles = 0

    def _run_cycle(
        self, step: int, snapshot: StateT
    ) -> Optional[EpisodeResult[StateT, CallT, TaskT]]:
        # plan (recovery advice, when standing, pre-empts the head — same gates apply)
        planner_result = self._plan(snapshot)
        if isinstance(planner_result, PlannerFailure):
            fault = planner_result.to_infrastructure_fault()   # :156 — infrastructure, typed
            self._entry(step, snapshot, symbolic_result=planner_result, faults=(fault,))
            return self._maybe_fault_halt(fault)

        rejections = 0
        acquired = False                        # one acquisition per cycle, policy-requested
        cached_proposal: Optional[ProposalT] = None
        while True:
            preliminary = self._preliminary(planner_result, snapshot)
            # ── R3 lifecycle (report Phase 3 item 7): ask the policy which track inputs it
            # requires, acquire them, and build the comparison BEFORE the final decision.
            # The compared symbolic side is the call an Execute decision would enact
            # (standing recovery, else the plan head), so executed-entry divergence
            # evidence keeps its accepted meaning (review X3: "against THAT cycle's
            # selected call"). Predictions stay AFTER the decision — the forbidden oracle
            # is a predictor consulted before choosing, and none is (clause 9).
            request = self.policy.required_inputs(preliminary)
            if request.nl_proposal and not acquired:
                try:
                    cached_proposal = self._advisory_proposal(request)
                except InfrastructureFaultError as error:
                    # NL_TRACK_FAILURE at ACQUISITION — now pre-decision by the R3 order
                    # (:163, H8): the cycle short-circuits fail-closed with the world
                    # untouched, zero steps charged, no decision made, no gates run, and
                    # NO manufactured divergence (divergences compare track CONTENT, and
                    # there is none).
                    fault = error.fault
                    self._entry(step, snapshot, symbolic_result=planner_result,
                                faults=(fault,))
                    return self._maybe_fault_halt(fault)
                acquired = True
            nl_proposal = cached_proposal if request.nl_proposal else None
            comparison = (
                self.comparator.compare(self._compared_call(preliminary), nl_proposal)
                if nl_proposal is not None and self.comparator is not None else None
            )                                   # the None arm is unreachable: see __init__
            decision = self.policy.decide(OrchestrationContext(
                preliminary=preliminary, nl_proposal=nl_proposal, comparison=comparison,
            ))
            if isinstance(decision, Halt):
                kind = (EpisodeOutcome.HALTED_REPEATED_FAILURE if decision.call is not None
                        else EpisodeOutcome.HALTED_NO_PLAN)
                self._entry(step, snapshot, symbolic_result=planner_result,
                            decision=decision.decision, selected_call=decision.call)
                return self._finish(kind, decision.reason)
            if isinstance(decision, RequestProposal):
                # the decision itself is part of the record (:70 traces include decisions;
                # acceptance record: "orchestrator decision/recovery when P4 exists")
                self._entry(step, snapshot, symbolic_result=planner_result,
                            decision=ExecutiveDecision.REQUEST_PROPOSAL,
                            selected_call=decision.call)
                self._pending_recovery = self._recovery_for(decision.call)
                if not self._pending_recovery:
                    self._entry(step, snapshot, symbolic_result=planner_result,
                                decision=ExecutiveDecision.HALT, selected_call=decision.call)
                    return self._finish(
                        EpisodeOutcome.HALTED_REPEATED_FAILURE,
                        decision.reason + " — no recovery advice available",
                    )
                continue                        # re-select with the recovery call standing
            if isinstance(decision, Replan):
                rejections += 1
                if rejections > self.config.max_rejections_per_cycle:
                    fault = InfrastructureFault(
                        kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                        message=f"{rejections} pre-executor rejections in one cycle — the "
                                f"loop guard from OrchestrationConfig (Decision 2: rejections "
                                f"are free, so the loop must bound them)",
                        source="runtime/loop.py::_run_cycle",
                    )
                    self._entry(step, snapshot, symbolic_result=planner_result, faults=(fault,))
                    return self._maybe_fault_halt(fault)
                planner_result = self._plan(snapshot)
                if isinstance(planner_result, PlannerFailure):
                    fault = planner_result.to_infrastructure_fault()
                    self._entry(step, snapshot, symbolic_result=planner_result, faults=(fault,))
                    return self._maybe_fault_halt(fault)
                continue
            break                               # EXECUTE

        call = decision.call
        from_recovery = bool(self._pending_recovery) and call == self._pending_recovery[0]
        # ── grounding gate, then symbolic gate (§19.1 item 5 ordering) ────────────
        # Both verdicts are the DOMAIN's: identities against the authoritative snapshot
        # first, then symbolic applicability — the loop only routes the typed answers.
        ungrounded = self.domain.ground(snapshot, call)
        if ungrounded is not None:
            fault = ungrounded.to_infrastructure_fault()
            self._entry(step, snapshot, symbolic_result=planner_result,
                        selected_call=call, validation=ungrounded, faults=(fault,))
            self._pending_recovery = ()
            return self._maybe_fault_halt(fault)
        verdict = self.domain.evaluate(self.belief.state, call)
        if isinstance(verdict, SymbolicallyInapplicable):
            # recovery advice can be stale — drop it and record the typed rejection
            self._entry(step, snapshot, symbolic_result=planner_result,
                        selected_call=call, validation=verdict,
                        decision=ExecutiveDecision.REPLAN)
            self._pending_recovery = ()
            return None                         # next cycle replans from the fresh belief

    # ── execute ───────────────────────────────────────────────────────────────
        pre_symbolic = self.belief.state
        # Decision 13.6 both-bases predictions, RECORDED for the monitor/trace — computed after
        # the decision, never consulted by it (clause 9: a predictor consulted before choosing
        # is the forbidden oracle; here the choice is already made)
        prediction = self.domain.predict(pre_symbolic, snapshot, call)
        predicted_symbolic_key = prediction.symbolic_key
        predicted_world_key = prediction.world_key
        # R3: the proposal and comparison were produced BEFORE the decision (acquisition in
        # the selection loop above); the executed entry records that same evidence.
        divergences = comparison.divergences if comparison is not None else ()
        # P3 EVIDENCE PRESERVATION (consistency-all W1): the frozen schema reserves proposal
        # columns, and an AGREEING advisory proposal must not vanish just because the
        # comparator has nothing to raise. Recovery provenance keeps priority on nl_proposal
        # (the enacted NL advice IS the proposal); otherwise the advisory call is recorded.
        # Evidence only — nothing here feeds a decision (symbolic-primary unchanged).
        # Typed on the RuntimeCall protocol: the advisory call type is track-owned.
        nl_call_column: Optional[RuntimeCall] = call if from_recovery else (
            nl_proposal.call if nl_proposal is not None else None
        )
        nl_coverage = nl_proposal.coverage if nl_proposal is not None else None
        nl_confidence = (
            (nl_proposal.confidence,)
            if nl_proposal is not None and nl_proposal.confidence is not None else ()
        )
        try:
            result = execute(self.env, call)
        except InfrastructureFaultError as error:
            fault = error.fault
            if error.result is not None:
                # case (a): the attempt ran to COMPLETION and then faulted — the attached
                # ExecutionResult is the authoritative record and its recorded accounting
                # charges the step (shared/faults.py: "result is not None => one executive
                # step"). The record is FIRST-CLASS (consistency round W3/W4): full trace
                # columns, and Decision-13.8 belief maintenance + NL observation run exactly
                # as on the normal path — the attempt happened; only the monitor is skipped
                # (the fault, not a prediction comparison, is this cycle's verdict).
                # W4: the attached result's post_state IS the authoritative state — reuse
                # it rather than re-exporting (same instant by construction, not argument)
                self.belief.sync(error.result.post_state)
                self.belief.record_outcome(error.result)
                extra_faults: Tuple[InfrastructureFault, ...] = ()
                try:
                    self._observe(
                        error.result.post_state, str(call.skill), error.result.outcome
                    )
                except InfrastructureFaultError as oerr:
                    # WARN-1 site 2: the observer fault is RECORDED alongside the primary
                    # executor-boundary fault (both post-execution-compatible); the primary
                    # fault stays the cycle's verdict
                    extra_faults = (oerr.fault,)
                self._entry(step, snapshot, symbolic_result=planner_result,
                            selected_call=call,
                            validation=verdict if isinstance(verdict, ValidatedCall) else None,
                            decision=ExecutiveDecision.EXECUTE,
                            nl_proposal=nl_call_column,
                            coverage=nl_coverage, confidence=nl_confidence,
                            predicted_symbolic_key=predicted_symbolic_key,
                            predicted_world_key=predicted_world_key,
                            divergences=divergences, execution=error.result,
                            post_state=error.result.post_state,
                            faults=(fault,) + extra_faults)
            else:
                self._charge_case_c(fault)      # case (c) — see module docstring
                self._entry(step, snapshot, symbolic_result=planner_result,
                            selected_call=call,
                            validation=verdict if isinstance(verdict, ValidatedCall) else None,
                            divergences=divergences, faults=(fault,))
            return self._maybe_fault_halt(fault)

        if isinstance(result, (MalformedCall, UngroundedCall)):
            # defense in depth: the loop's own gates should make this unreachable
            fault = result.to_infrastructure_fault()
            self._entry(step, snapshot, symbolic_result=planner_result, selected_call=call,
                        validation=result, faults=(fault,))
            return self._maybe_fault_halt(fault)

        # W4: reuse the result's authoritative post_state — one export per cycle (_sync).
        # Case (c) (result=None, world possibly changed under the fault) performs no sync
        # here; the NEXT cycle's _sync is the resynchronization point.
        self.belief.sync(result.post_state)
        self.belief.record_outcome(result)
        try:
            self._observe(result.post_state, str(call.skill), result.outcome)
        except InfrastructureFaultError as oerr:
            # WARN-1 site 3: the attempt COMPLETED — its result, post_state and recorded
            # accounting are authoritative and stay first-class in the trace; only the
            # remainder of the cycle (the monitor comparison) is short-circuited (:163),
            # mirroring the case-(a) precedent. Standing recovery advice deliberately
            # remains, exactly as on every other fault path except the ungrounded drop.
            self._entry(step, snapshot, symbolic_result=planner_result, selected_call=call,
                        validation=verdict, decision=ExecutiveDecision.EXECUTE,
                        nl_proposal=nl_call_column,
                        coverage=nl_coverage, confidence=nl_confidence,
                        predicted_symbolic_key=predicted_symbolic_key,
                        predicted_world_key=predicted_world_key,
                        divergences=divergences, execution=result,
                        post_state=result.post_state, faults=(oerr.fault,))
            return self._maybe_fault_halt(oerr.fault)
        discrepancies, monitor_fault = self._monitor(pre_symbolic, result)
        self._all_discrepancies.extend(discrepancies)
        if self._pending_recovery:
            # consumed on the NORMAL path only. After a fault the standing call deliberately
            # remains: the next cycle re-validates it through the grounding and applicability
            # gates, and every retry is budget-charged — except the ungrounded fault, which
            # drops it (a ghost can never become valid). Consistency-round W3 note.
            self._pending_recovery = self._pending_recovery[1:]

        self._entry(
            step, snapshot, symbolic_result=planner_result, selected_call=call,
            validation=verdict, decision=ExecutiveDecision.EXECUTE,
            # typed recovery provenance keeps priority; an advisory proposal (agreeing or
            # not) is otherwise recorded with its coverage/confidence evidence (W1)
            nl_proposal=nl_call_column,
            coverage=nl_coverage, confidence=nl_confidence,
            predicted_symbolic_key=predicted_symbolic_key,
            predicted_world_key=predicted_world_key,
            execution=result, post_state=result.post_state,
            discrepancies=discrepancies, divergences=divergences,
            faults=(monitor_fault,) if monitor_fault else (),
        )
        if monitor_fault:
            return self._maybe_fault_halt(monitor_fault)
        return None

    # ── selection helpers ─────────────────────────────────────────────────────────
    def _preliminary(
        self, planner_result: PlannerResult, snapshot: StateT
    ) -> PreliminaryContext[StateT, CallT]:
        """Build the immutable pre-acquisition decision situation (R2/R3): the same
        context feeds `required_inputs()`, the comparison, and `decide()`."""
        if self._pending_recovery:
            return PreliminaryContext(
                state=snapshot, planner_result=planner_result,
                standing_recovery=self._pending_recovery[0],
            )
        head_validation = None
        failure_count = 0
        if isinstance(planner_result, PlanFound) and planner_result.plan:
            head_validation = self.domain.evaluate(
                self.belief.state, planner_result.plan[0]
            )
            failure_count = self.history.failure_count(
                snapshot, planner_result.plan[0]
            )
        return PreliminaryContext(
            state=snapshot, planner_result=planner_result,
            head_validation=head_validation, failure_count=failure_count,
        )

    def _compared_call(
        self, preliminary: PreliminaryContext[StateT, CallT]
    ) -> Optional[CallT]:
        """The symbolic side of the R3 pre-decision comparison: the call an Execute
        decision would enact — standing recovery advice when standing, else the plan
        head. This keeps executed-entry divergence evidence computed against THAT
        cycle's selected call (review X3), exactly as accepted."""
        if preliminary.standing_recovery is not None:
            return preliminary.standing_recovery
        if isinstance(preliminary.planner_result, PlanFound) and preliminary.planner_result.plan:
            return preliminary.planner_result.plan[0]
        return None

    def _recovery_for(self, call: CallT) -> Tuple[CallT, ...]:
        """On REQUEST_PROPOSAL: the injected provider's advice over the LAST discrepancy for
        this call (§19.1 item 1 — the livelock escape). No provider, no advice."""
        if self.recovery_provider is None:
            return ()
        for discrepancy in reversed(self._all_discrepancies):
            if discrepancy.call == call:
                return tuple(self.recovery_provider(discrepancy))
        return ()

    def _advisory_proposal(self, request: TrackRequest) -> Optional[ProposalT]:
        if self.nl_track is None or not request.nl_proposal:
            return None
        try:
            return self.nl_track.propose(self.task)
        except InfrastructureFaultError:
            raise                               # WARN-2: never re-wrap an already-typed fault
        except Exception as error:
            # H8 (final audit, closed): an exception ESCAPING the NL track is infrastructure,
            # not reasoning content — the earlier rewrite into a standing MalformedCall
            # manufactured COVERAGE_GAP evidence with fault provenance. Typed malformed LM
            # OUTPUT (the model returned content the parser/repair rejected) still arrives as
            # a `MalformedProposal` from inside NLTrack and still becomes COVERAGE_GAP via
            # the comparator, the only TrackDivergence constructor. Only the RAISE is a fault.
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.NL_TRACK_FAILURE,
                message=f"NL track propose() raised {type(error).__name__}: {error}",
                source="runtime/loop.py::_advisory_proposal",
                stage="propose",
            )) from error

    def _observe(
        self,
        snapshot: StateT,
        skill: Optional[str] = None,
        outcome: Optional[ExecutionOutcome] = None,
    ) -> None:
        """WARN-1: the SINGLE typed boundary for `nl_track.observe()` — same principle as
        `_advisory_proposal` (an exception escaping the NL track is infrastructure, never
        reasoning content), but the LIFECYCLE POSITION differs per call site: before any
        execution on the first cycle, after a COMPLETED attempt post-execution. The fault
        therefore carries `stage="observe"` and each call site classifies by its actual
        position — never by kind alone.

        CONTRACT NOTE (consistency-all 1e): the WARN-2 pass-through below re-raises an
        already-typed `InfrastructureFaultError` UNCHANGED — so a non-V1 track that raises a
        typed fault with a pre-execution KIND from observe() would reach a post-execution
        entry alongside an `ExecutionResult` and be refused loudly by `TraceEntry`'s
        lifecycle-legality check (a track-contract violation, fail-closed by design; the
        shipped NLTrack raises only untyped `RuntimeError`s here)."""
        if self.nl_track is None:
            return
        try:
            self.nl_track.observe(snapshot, skill, outcome)
        except InfrastructureFaultError:
            raise                               # WARN-2: never re-wrap an already-typed fault
        except Exception as error:
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.NL_TRACK_FAILURE,
                message=f"NL track observe() raised {type(error).__name__}: {error}",
                source="runtime/loop.py::_observe",
                stage="observe",
            )) from error

    def _maybe_fault_halt(
        self, fault: InfrastructureFault
    ) -> Optional[EpisodeResult[StateT, CallT, TaskT]]:
        """:163 — the fault has already short-circuited the CURRENT cycle (the caller returns
        without executing further). Whether the EPISODE continues is configuration."""
        if self.config.halt_on_infrastructure_fault:
            return self._finish(EpisodeOutcome.FAULTED, f"{fault.kind}: {fault.message}")
        return None

    def _finish(
        self, outcome: EpisodeOutcome, reason: str
    ) -> EpisodeResult[StateT, CallT, TaskT]:
        return EpisodeResult(
            outcome=outcome, reason=reason, history=self.history,
            discrepancies=tuple(self._all_discrepancies),
        )
