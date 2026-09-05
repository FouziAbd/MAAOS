"""The R5 probe domain — a TEST-ONLY counter domain proving runtime substitutability
(report Phase 5; `.claude/rules/v1-scope.md`: "permitted only as a test fixture").

Nothing here is a product domain, a scientific model, or a semantic proposal. It exists so
`tests/test_r5_probe.py` can drive the UNMODIFIED `runtime.loop.ExecutiveLoopManager` with
state and action types that have no agents, boxes, zones, or geometry — and observe, at the
trace/outcome seam, that the runtime handled them without interpreting them.

The domain, in full (report Phase 5 default design):

    state        CounterState(counter_id, value, target, stopped, tick)   — immutable
    actions      Increment(amount)  |  Stop                                — immutable
    transition   Increment adds `amount`; Stop terminates when value == target
    goal         stopped at the target
    optimism     the symbolic model admits any Increment that stays within the target and
                 knows nothing about the fake environment's "sticky" value, where an
                 Increment(1) PHYSICALLY fails while leaving the world unchanged. That is the
                 counter analogue of the frozen V1 abstraction rule: a symbolically applicable
                 call may fail in the backend, and the failure is typed evidence — never a
                 reason for the symbolic side to ask the environment first.

Component map onto the `shared.contracts` seams the runtime consumes:

    CounterEnvironment      Environment      (reset / observe / export_full_state /
                                              execute_skill / is_terminal / render)
    CounterSymbolicTrack    SymbolicTrack    (sync / state / record_outcome)
    CounterDomainServices   DomainServices   (model_version / plan / ground / evaluate /
                                              predict / monitor)
    FakeReasoningTrack      ReasoningTrack   (observe / propose — programmable, LM-free)
    CounterActionComparator ProposalComparator
    counter_recovery        RecoveryProvider
    CounterState / CounterAction / CounterTask / CounterProposal satisfy the R5 structural
    `RuntimeState` / `RuntimeCall` / `TaskContract` / `AdvisoryProposal` protocols.

`compose_probe` / `build_probe_loop` are this fixture's composition root, mirroring
`app.box_push_v1` in shape so the probe is assembled the same way the product is.

Import discipline (pinned by the R5 tests): stdlib, `shared`, and `runtime` only. The
shared typed CHANNELS (`ExecutionResult`, `PlannerResult`, `CallValidation`,
`ExecutionDiscrepancy`, `TrackDivergence`, `InfrastructureFault`, the Decision-13 keys,
the coverage/confidence reports) are reused as they are — they carry no BoxPush vocabulary
and the contracts are typed on them. Nothing from `domain`, `symbolic`, `nl`, `app`, or the
backend is reachable from here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from runtime.loop import ExecutiveLoopManager
from shared.comparison_keys import SymbolicKey, WorldKey
from shared.contracts import (
    AdvisoryProposal,
    ComparedAspect,
    ComparisonFinding,
    ComparisonReport,
    DomainServices,
    Environment,
    FindingSeverity,
    OrchestrationPolicyContract,
    Prediction,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
)
from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.divergence import DivergenceKind, TrackDivergence
from shared.execution import (
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    StepAccounting,
)
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError
from shared.orchestration_config import OrchestrationConfig
from shared.planner_result import NoPlan, PlanFound, PlannerResult
from shared.reports import ConfidenceReport, CoverageReport
from shared.skills import (
    CallValidation,
    MalformedCall,
    SymbolicallyInapplicable,
    UngroundedCall,
    ValidatedCall,
)
from shared.versioning import ModelVersion, Provenance

PROBE_MODEL_VERSION = ModelVersion(revision=0, label="counter-probe")


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ── domain-owned value types ───────────────────────────────────────────────────────────

class CounterOp(StrEnum):
    INCREMENT = "Increment"
    STOP = "Stop"


@dataclass(frozen=True, slots=True)
class CounterState:
    """The authoritative state: a current integer, a target integer, a stopped flag — and
    `tick`, the environment's own attempt counter, which is episode bookkeeping EXCLUDED
    from the world key (the counter analogue of the V1 snapshot's step counters). The
    runtime never reads `tick`; the R5 tests pin that it survives untouched anyway."""
    counter_id: str
    value: int
    target: int
    stopped: bool = False
    tick: int = 0

    def __post_init__(self) -> None:
        if not self.counter_id:
            raise ValueError("CounterState requires a counter_id")
        if self.target < 0 or self.value < 0:
            raise ValueError("counter values are non-negative")

    def canonical(self) -> Dict[str, Any]:
        return {
            "counter": self.counter_id, "value": self.value,
            "target": self.target, "stopped": self.stopped,
        }

    def world_key(self) -> WorldKey:
        return WorldKey(_digest(self.canonical()))

    def same_world(self, other: "CounterState", /) -> bool:
        return self.canonical() == other.canonical()


@dataclass(frozen=True, slots=True)
class CounterAction:
    """A grounded executive call: `Increment(amount)` or `Stop`, naming the counter it acts
    on (the IDENTITY the grounding gate checks against the authoritative state)."""
    op: CounterOp
    counter_id: str
    amount: int = 0

    def __post_init__(self) -> None:
        if self.op is CounterOp.INCREMENT and self.amount < 1:
            raise ValueError("Increment requires a positive amount")
        if self.op is CounterOp.STOP and self.amount != 0:
            raise ValueError("Stop takes no amount")
        if not self.counter_id:
            raise ValueError("CounterAction requires a counter_id")

    @property
    def skill(self) -> CounterOp:
        return self.op

    @property
    def cost(self) -> int:
        return 1

    def canonical(self) -> Dict[str, Any]:
        return {"op": str(self.op), "counter": self.counter_id, "amount": self.amount}

    def key(self) -> str:
        return json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))

    def __str__(self) -> str:
        if self.op is CounterOp.INCREMENT:
            return f"Increment({self.counter_id}; +{self.amount})"
        return f"Stop({self.counter_id})"


def increment(counter_id: str, amount: int = 1) -> CounterAction:
    return CounterAction(CounterOp.INCREMENT, counter_id, amount)


def stop(counter_id: str) -> CounterAction:
    return CounterAction(CounterOp.STOP, counter_id)


@dataclass(frozen=True, slots=True)
class CounterSymbolicState:
    """The symbolic track's state — an exact projection of the authoritative state (the
    probe is fully observable; nothing is dead-reckoned or maintained from outcomes)."""
    value: int
    target: int
    stopped: bool

    def canonical(self) -> Dict[str, Any]:
        return {"value": self.value, "target": self.target, "stopped": self.stopped}

    def symbolic_key(self) -> SymbolicKey:
        return SymbolicKey(_digest(self.canonical()))


def project(state: CounterState) -> CounterSymbolicState:
    return CounterSymbolicState(state.value, state.target, state.stopped)


@dataclass(frozen=True, slots=True)
class CounterTask:
    task_id: str
    description: str
    counter_id: str

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("CounterTask requires a task_id")

    def is_satisfied_by(self, state: CounterState, /) -> bool:
        """Pure goal test over the authoritative state: stopped at the target."""
        return state.stopped and state.value == state.target

    def canonical(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id, "description": self.description,
            "counter": self.counter_id,
        }


# ── the deterministic symbolic transition (shared by planner, predictor, monitor) ───────

def _apply(value: int, target: int, stopped: bool, call: CounterAction) -> Tuple[int, int, bool]:
    if call.op is CounterOp.INCREMENT:
        return value + call.amount, target, stopped
    return value, target, True


def _apply_symbolic(sym: CounterSymbolicState, call: CounterAction) -> CounterSymbolicState:
    return CounterSymbolicState(*_apply(sym.value, sym.target, sym.stopped, call))


def _apply_world(state: CounterState, call: CounterAction) -> CounterState:
    value, target, stopped = _apply(state.value, state.target, state.stopped, call)
    return CounterState(state.counter_id, value, target, stopped, tick=state.tick)


# ── the fake environment (the sole physical authority of the probe) ────────────────────

ProbeExecutionOutcome = Union[
    ExecutionResult[CounterState, CounterAction], MalformedCall, UngroundedCall[CounterAction]
]


class CounterEnvironment:
    """Deterministic, offline, external-dependency-free.

    `sticky_at`: one value or several; when the current value is one of them, an
    `Increment(1)` PHYSICALLY fails with the world unchanged (typed FAILURE / UNCHANGED).
    Any other amount succeeds. The symbolic model does not know this rule — that is the
    point. `Stop` succeeds only at the target.

    Refusals mirror the V1 contract's protocol faults: execution before `reset` and
    execution after the terminal state are `InfrastructureFaultError`s whose message
    begins with "refused:" (a pre-attempt refusal — zero steps, world untouched).
    """

    def __init__(
        self, initial: CounterState, *, sticky_at: Union[int, Iterable[int], None] = None
    ) -> None:
        self._initial = initial
        self._sticky: frozenset = (
            frozenset() if sticky_at is None
            else frozenset((sticky_at,)) if isinstance(sticky_at, int) else frozenset(sticky_at)
        )
        self._state: Optional[CounterState] = None
        self.executed: List[CounterAction] = []

    def reset(self, *, seed: Optional[int] = None) -> CounterState:
        del seed                                # deterministic by construction
        self._state = CounterState(
            self._initial.counter_id, self._initial.value, self._initial.target,
            self._initial.stopped, tick=0,
        )
        self.executed = []
        return self._state

    def observe(self) -> Mapping[str, int]:
        return {"value": self._require().value}

    def export_full_state(self) -> CounterState:
        return self._require()

    def execute_skill(self, call: CounterAction, /) -> ProbeExecutionOutcome:
        state = self._require()
        if state.stopped:
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message="refused: the counter is terminal; execution after terminal state",
                source="tests/probe_counter.py::CounterEnvironment",
            ))
        if not isinstance(call, CounterAction):
            return MalformedCall(reason=f"not a CounterAction: {call!r}", raw=repr(call))
        if call.counter_id != state.counter_id:
            return UngroundedCall(reason=f"unknown counter {call.counter_id}", call=call)
        self.executed.append(call)
        pre = state
        if call.op is CounterOp.INCREMENT:
            physically_stuck = pre.value in self._sticky and call.amount == 1
            if physically_stuck or pre.value + call.amount > pre.target:
                post = CounterState(pre.counter_id, pre.value, pre.target, pre.stopped, pre.tick + 1)
                self._state = post
                return ExecutionResult(
                    call=call, outcome=ExecutionOutcome.FAILURE, pre_state=pre, post_state=post,
                    accounting=StepAccounting(executive_steps=1, primitive_steps=1),
                    failure_class=FailureStateClass.UNCHANGED,
                    detail="probe: the counter did not advance",
                )
            post = CounterState(
                pre.counter_id, pre.value + call.amount, pre.target, pre.stopped, pre.tick + 1
            )
            self._state = post
            return ExecutionResult(
                call=call, outcome=ExecutionOutcome.SUCCESS, pre_state=pre, post_state=post,
                accounting=StepAccounting(executive_steps=1, primitive_steps=call.amount),
            )
        # Stop
        if pre.value != pre.target:
            post = CounterState(pre.counter_id, pre.value, pre.target, pre.stopped, pre.tick + 1)
            self._state = post
            return ExecutionResult(
                call=call, outcome=ExecutionOutcome.FAILURE, pre_state=pre, post_state=post,
                accounting=StepAccounting(executive_steps=1, primitive_steps=1),
                failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION,
                detail="probe: cannot stop away from the target",
            )
        post = CounterState(pre.counter_id, pre.value, pre.target, True, pre.tick + 1)
        self._state = post
        return ExecutionResult(
            call=call, outcome=ExecutionOutcome.SUCCESS, pre_state=pre, post_state=post,
            accounting=StepAccounting(executive_steps=1, primitive_steps=1),
        )

    def is_terminal(self) -> bool:
        return self._require().stopped

    def render(self) -> str:
        state = self._require()
        return f"[{state.counter_id}] {state.value}/{state.target}{' STOPPED' if state.stopped else ''}"

    def _require(self) -> CounterState:
        if self._state is None:
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message="refused: reset() must precede any other environment call",
                source="tests/probe_counter.py::CounterEnvironment",
            ))
        return self._state


# ── the symbolic track ──────────────────────────────────────────────────────────────────

class CounterSymbolicTrack:
    """Exact, fully observable: `state` is always the projection of the last synced
    authoritative state. `record_outcome` is evidence intake only (counted, never used
    to patch the projection, never touching the environment)."""

    def __init__(self) -> None:
        self._state: Optional[CounterSymbolicState] = None
        self.recorded: List[ExecutionResult[CounterState, CounterAction]] = []

    def sync(self, snapshot: CounterState, /) -> None:
        self._state = project(snapshot)

    @property
    def state(self) -> CounterSymbolicState:
        if self._state is None:
            raise RuntimeError("CounterSymbolicTrack.sync(state) must be called first")
        return self._state

    def record_outcome(self, result: ExecutionResult[CounterState, CounterAction], /) -> None:
        self.recorded.append(result)


# ── the domain services ─────────────────────────────────────────────────────────────────

class CounterDomainServices:
    """`DomainServices[CounterState, CounterSymbolicState, CounterAction]` for one task.

    plan      Increment(1) up to the target, then Stop; NoPlan when the value already exceeds
              the target (no decrement exists in the model); an empty plan once stopped.
              The authoritative `state` is read for the counter IDENTITY only.
    ground    the call must name the authoritative counter (typed UngroundedCall otherwise).
    evaluate  Increment applicable iff it stays within the target and the counter is not
              stopped; Stop applicable iff at the target and not stopped. Optimistic: no
              knowledge of the environment's sticky rule, by design.
    predict   both Decision-13 bases from the deterministic symbolic transition.
    monitor   a non-success outcome of an applicable call -> EXECUTION_FAILURE_OF_APPLICABLE_
              SKILL (evidence is the typed outcome alone); a success whose realized keys differ
              from the prediction -> STATE_EFFECT_MISMATCH with the differing pair(s).
              Raises a bare ValueError on a counter-identity wiring error (the probe analogue
              of the V1 predictor's zone-identity escape the loop must wrap).
    """

    def __init__(self, task: CounterTask) -> None:
        self.task = task

    @property
    def model_version(self) -> ModelVersion:
        return PROBE_MODEL_VERSION

    def plan(self, symbolic_state: CounterSymbolicState, state: CounterState, /) -> PlannerResult:
        counter = state.counter_id                       # identity only
        if symbolic_state.stopped:
            return PlanFound(plan=(), model_version=PROBE_MODEL_VERSION)
        if symbolic_state.value > symbolic_state.target:
            return NoPlan(
                reason="the value exceeds the target and the model has no decrement",
                model_version=PROBE_MODEL_VERSION,
            )
        steps = [increment(counter, 1)] * (symbolic_state.target - symbolic_state.value)
        steps.append(stop(counter))
        return PlanFound(plan=tuple(steps), model_version=PROBE_MODEL_VERSION)

    def ground(
        self, state: CounterState, call: CounterAction, /
    ) -> Optional[UngroundedCall[CounterAction]]:
        if call.counter_id != state.counter_id:
            return UngroundedCall(reason=f"unknown counter {call.counter_id} in {call}", call=call)
        return None

    def evaluate(self, symbolic_state: CounterSymbolicState, call: CounterAction, /) -> CallValidation:
        if symbolic_state.stopped:
            return SymbolicallyInapplicable(
                reason=f"{call}: the counter is already stopped", call=call,
                unsatisfied=("not stopped",),
            )
        if call.op is CounterOp.INCREMENT:
            if symbolic_state.value + call.amount > symbolic_state.target:
                return SymbolicallyInapplicable(
                    reason=f"{call}: would overshoot the target", call=call,
                    unsatisfied=("value + amount <= target",),
                )
            return ValidatedCall(call=call)
        if symbolic_state.value != symbolic_state.target:
            return SymbolicallyInapplicable(
                reason=f"{call}: not at the target", call=call,
                unsatisfied=("value == target",),
            )
        return ValidatedCall(call=call)

    def predict(
        self, symbolic_state: CounterSymbolicState, state: CounterState, call: CounterAction, /
    ) -> Prediction:
        return Prediction(
            symbolic_key=_apply_symbolic(symbolic_state, call).symbolic_key(),
            world_key=_apply_world(state, call).world_key(),
        )

    def monitor(
        self,
        pre_symbolic: CounterSymbolicState,
        result: ExecutionResult[CounterState, CounterAction],
        /,
    ) -> Tuple[ExecutionDiscrepancy[CounterAction], ...]:
        call = result.call
        if call.counter_id != self.task.counter_id:
            raise ValueError(f"monitor wired to counter {self.task.counter_id}, got {call.counter_id}")
        if result.outcome is not ExecutionOutcome.SUCCESS:
            return (ExecutionDiscrepancy(
                kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, call=call,
                message=f"probe: applicable {call} failed physically ({result.outcome}); "
                        f"counter held at {result.pre_state.value}",
                model_version=PROBE_MODEL_VERSION,
            ),)
        predicted_world = _apply_world(result.pre_state, call).world_key()
        observed_world = result.post_state.world_key()
        predicted_symbolic = _apply_symbolic(pre_symbolic, call).symbolic_key()
        observed_symbolic = project(result.post_state).symbolic_key()
        if predicted_world != observed_world or predicted_symbolic != observed_symbolic:
            return (ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=call,
                predicted_world_key=predicted_world, observed_world_key=observed_world,
                predicted_symbolic_key=predicted_symbolic, observed_symbolic_key=observed_symbolic,
                message=f"probe: {call} realized a different counter than predicted",
                model_version=PROBE_MODEL_VERSION,
            ),)
        return ()


# ── the advisory side: proposal, programmable track, comparator, recovery ──────────────

@dataclass(frozen=True, slots=True)
class CounterProposal:
    """The fake advisory track's proposal. `evidence` is OPAQUE domain content the runtime
    has no column for and must neither interpret nor discard on the way to the policy."""
    call: Optional[CounterAction]
    coverage: Optional[CoverageReport] = None
    confidence: Optional[ConfidenceReport] = None
    evidence: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))


class FakeReasoningTrack:
    """`ReasoningTrack[CounterState, CounterTask, CounterProposal]`, LM-free and programmable.

    With a `script`, proposals are served in order (exhaustion raises — a scripted test
    that under-provisions is a test bug, surfaced as the loop's typed NL fault). Without
    one, the track ECHOES the plan from its last observation: Increment(1) below the
    target, Stop at it. `propose` before any `observe` raises, mirroring the shipped
    track's observe-before-propose precondition.
    """

    def __init__(self, script: Optional[Sequence[CounterProposal]] = None) -> None:
        self._script: Optional[List[CounterProposal]] = list(script) if script is not None else None
        self.observations: List[Tuple[CounterState, Optional[str], Optional[ExecutionOutcome]]] = []
        self.proposed: List[CounterProposal] = []

    def observe(
        self,
        state: CounterState,
        last_action_label: Optional[str] = None,
        last_outcome: Optional[ExecutionOutcome] = None,
        /,
    ) -> None:
        self.observations.append((state, last_action_label, last_outcome))

    def propose(self, task: CounterTask, /) -> CounterProposal:
        if not self.observations:
            raise RuntimeError("FakeReasoningTrack.propose() before any observe()")
        if self._script is not None:
            if not self._script:
                raise RuntimeError("FakeReasoningTrack script exhausted")
            proposal = self._script.pop(0)
        else:
            state = self.observations[-1][0]
            call = increment(task.counter_id, 1) if state.value < state.target else stop(task.counter_id)
            proposal = CounterProposal(
                call=call, coverage=CoverageReport(covered=("counter",)),
                confidence=ConfidenceReport(source="nl", confidence=1.0),
                evidence=(f"echo of value={state.value}",),
            )
        self.proposed.append(proposal)
        return proposal


class CounterActionComparator:
    """`ProposalComparator[CounterAction, CounterProposal]` — evidence only.

    No proposal -> empty report. A proposal without a call -> one PROPOSAL_FORM /
    COVERAGE_GAP finding. A proposed call different from the symbolic selection ->
    one ACTION_CHOICE / CONTRADICTION finding whose `residual` carries the proposal's
    opaque evidence verbatim. Same call -> genuine agreement (empty report).
    """

    def compare(
        self, symbolic_call: Optional[CounterAction], nl_proposal: Optional[CounterProposal], /
    ) -> ComparisonReport:
        if nl_proposal is None:
            return ComparisonReport()
        if nl_proposal.call is None:
            return ComparisonReport(findings=(ComparisonFinding(
                aspect=ComparedAspect.PROPOSAL_FORM, severity=FindingSeverity.ATTENTION,
                divergence=TrackDivergence(
                    kind=DivergenceKind.COVERAGE_GAP, message="probe: no well-formed proposal",
                    symbolic_view=str(symbolic_call) if symbolic_call is not None else "",
                    residual=nl_proposal.evidence,
                ),
            ),))
        if symbolic_call is not None and nl_proposal.call != symbolic_call:
            return ComparisonReport(findings=(ComparisonFinding(
                aspect=ComparedAspect.ACTION_CHOICE, severity=FindingSeverity.ATTENTION,
                divergence=TrackDivergence(
                    kind=DivergenceKind.CONTRADICTION,
                    message=f"probe: advisory {nl_proposal.call} vs symbolic {symbolic_call}",
                    nl_view=str(nl_proposal.call), symbolic_view=str(symbolic_call),
                    residual=nl_proposal.evidence,
                ),
            ),))
        return ComparisonReport()


def counter_recovery(
    discrepancy: ExecutionDiscrepancy[CounterAction], /
) -> Tuple[CounterAction, ...]:
    """`RecoveryProvider[CounterAction]`: after a failed Increment, ADVISE a larger stride.
    Advice only — it passes the same grounding/applicability gates and executor as any call."""
    call = discrepancy.call
    if call.op is CounterOp.INCREMENT:
        return (increment(call.counter_id, call.amount + 1),)
    return ()


# ── the probe's composition root (mirrors app.box_push_v1 in shape) ─────────────────────

ProbeLoop = ExecutiveLoopManager[
    CounterState, CounterSymbolicState, CounterAction, CounterTask, CounterProposal
]
ProbeDomainServicesContract = DomainServices[CounterState, CounterSymbolicState, CounterAction]
ProbeSymbolicTrackContract = SymbolicTrack[CounterState, CounterSymbolicState]
ProbeReasoningTrackContract = ReasoningTrack[CounterState, CounterTask, CounterProposal]
ProbeComparatorContract = ProposalComparator[CounterAction, CounterProposal]
ProbePolicyContract = OrchestrationPolicyContract[CounterState, CounterAction, CounterProposal]


@dataclass(frozen=True, slots=True)
class ProbeComponents:
    domain: ProbeDomainServicesContract
    symbolic_track: ProbeSymbolicTrackContract
    comparator: ProbeComparatorContract
    recovery_provider: RecoveryProvider[CounterAction]


def compose_probe(task: CounterTask) -> ProbeComponents:
    return ProbeComponents(
        domain=CounterDomainServices(task),
        symbolic_track=CounterSymbolicTrack(),
        comparator=CounterActionComparator(),
        recovery_provider=counter_recovery,
    )


def build_probe_loop(
    env: CounterEnvironment,
    task: CounterTask,
    config: Optional[OrchestrationConfig] = None,
    nl_track: Optional[ProbeReasoningTrackContract] = None,
    provenance: Optional[Provenance] = None,
    policy: Optional[ProbePolicyContract] = None,
    *,
    domain: Optional[ProbeDomainServicesContract] = None,
    symbolic_track: Optional[ProbeSymbolicTrackContract] = None,
    comparator: Optional[ProbeComparatorContract] = None,
    recovery_provider: Optional[RecoveryProvider[CounterAction]] = None,
) -> ProbeLoop:
    """Assemble one executive loop over the probe — the SAME `ExecutiveLoopManager` class
    the product uses, receiving every component through the same keyword seams."""
    defaults = compose_probe(task)
    return ExecutiveLoopManager(
        env, task, config, nl_track, provenance, policy,
        domain=domain if domain is not None else defaults.domain,
        symbolic_track=symbolic_track if symbolic_track is not None else defaults.symbolic_track,
        comparator=comparator if comparator is not None else defaults.comparator,
        recovery_provider=(
            recovery_provider if recovery_provider is not None else defaults.recovery_provider
        ),
    )


# ── the canonical probe instance used by the tests ─────────────────────────────────────

COUNTER = "c0"
TASK = CounterTask(task_id="count-to-four", description="Count to four, then stop", counter_id=COUNTER)
INITIAL = CounterState(counter_id=COUNTER, value=0, target=4)
#: the designed physical obstacle: Increment(1) at value 2 fails, Increment(2) does not
STICKY_AT = 2


def sticky_environment() -> CounterEnvironment:
    return CounterEnvironment(INITIAL, sticky_at=STICKY_AT)


def smooth_environment() -> CounterEnvironment:
    return CounterEnvironment(INITIAL)


# ── static conformance witnesses (mypy) ────────────────────────────────────────────────
# `python -m mypy --ignore-missing-imports --follow-imports=silent tests/probe_counter.py`

ProbeEnvironmentContract = Environment[
    CounterState, CounterAction, ProbeExecutionOutcome, Mapping[str, int]
]
# (the track/domain/comparator/policy contract aliases are defined beside ProbeComponents)


def environment_conforms(env: CounterEnvironment) -> ProbeEnvironmentContract:
    return env


def symbolic_track_conforms(track: CounterSymbolicTrack) -> ProbeSymbolicTrackContract:
    return track


def domain_services_conform(services: CounterDomainServices) -> ProbeDomainServicesContract:
    return services


def reasoning_track_conforms(track: FakeReasoningTrack) -> ProbeReasoningTrackContract:
    return track


def comparator_conforms(comparator: CounterActionComparator) -> ProbeComparatorContract:
    return comparator


recovery_conforms: RecoveryProvider[CounterAction] = counter_recovery


def state_conforms(state: CounterState) -> RuntimeState:
    return state


def call_conforms(call: CounterAction) -> RuntimeCall:
    return call


def task_conforms(task: CounterTask) -> TaskContract:
    return task


def proposal_conforms(proposal: CounterProposal) -> AdvisoryProposal:
    return proposal


__all__ = [
    "COUNTER", "INITIAL", "STICKY_AT", "TASK", "PROBE_MODEL_VERSION",
    "CounterAction", "CounterActionComparator", "CounterDomainServices", "CounterEnvironment",
    "CounterOp", "CounterProposal", "CounterState", "CounterSymbolicState",
    "CounterSymbolicTrack", "CounterTask", "FakeReasoningTrack", "ProbeComponents",
    "build_probe_loop", "compose_probe", "counter_recovery", "increment", "project",
    "smooth_environment", "sticky_environment", "stop",
]
