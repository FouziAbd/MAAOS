"""Derived domain services (DK2) — `shared.contracts.DomainServices` built from the ONE
thing a domain author actually models: a deterministic symbolic transition.

The author writes a `SymbolicModel`:

    model_version                      the ModelVersion stamped on every trace entry
    project(state) -> sym              authoritative state -> symbolic state (no geometry)
    apply(sym, call) -> sym            the deterministic INTENDED effect of the call
    applicable(sym, call) -> verdict   the typed CallValidation, from the symbolic state only
    plan(sym, identities) -> result    PlanFound / NoPlan / PlannerFailure (closed form, or
                                       `kit.planning.bfs_plan`)

and `DerivedDomainServices(model)` supplies the five runtime operations:

    plan      model.plan(sym, state.identities()) — the authoritative state is read for
              IDENTITIES ONLY (Decision 6; pinned by geometry-invariance in BoxPush)
    ground    kit `ground_by_identity` (identity membership, never feasibility)
    evaluate  model.applicable
    predict   the symbolic-basis key of apply(sym, call); the world-basis key of the
              optional `apply_world(state, call)` when the author declares one (a skill's
              own deterministic world effect — Decision 13 permits declaring it, and it is
              reachable from predict/monitor ONLY, never from planning or applicability)
    monitor   exactly the probe's monitor (`tests/probe_counter.py:454-482`); the same two
              kinds `symbolic/monitor.py` emits, but ONE discrepancy carrying every basis
              where BoxPush emits one per basis (no trace impact: BoxPush does not use the kit):
                non-success of an applicable call -> EXECUTION_FAILURE_OF_APPLICABLE_SKILL
                                                     (evidence = the typed outcome alone)
                realized key != predicted key      -> STATE_EFFECT_MISMATCH with every
                                                     complete pair (both bases when
                                                     apply_world exists, symbolic otherwise)
              An exception escaping the author's `apply`/`project` inside the monitor is
              re-raised as a chained `ValueError`, so the loop's established conversion
              to `EXECUTOR_MONITOR_PROTOCOL_FAILURE` applies (`runtime/loop.py::_monitor`).

Frozen kinds only. `UNEXPECTED_OUTCOME` is unreachable here by construction: the kit has
no "outside the symbolic model" verdict, and the loop gates inapplicable calls before
execution. The kit never constructs an `InfrastructureFault` here; the `except Exception`
in `monitor` is the deliberate conversion of ANY author error (a typed fault included — the
loop has no typed-fault route out of the monitor) into the loop's established `ValueError`
escape.
"""
from __future__ import annotations

from typing import Callable, FrozenSet, Generic, Optional, Protocol, Tuple, TypeVar

from kit.protocols import IdentifiedCall, IdentifiedState, SymbolicKeyed, ground_by_identity
from shared.contracts.domain import Prediction
from shared.discrepancy import DiscrepancyKind, ExecutionDiscrepancy
from shared.execution import ExecutionOutcome, ExecutionResult
from shared.planner_result import PlannerResult
from shared.skills import CallValidation, UngroundedCall
from shared.versioning import ModelVersion

StateT = TypeVar("StateT", bound=IdentifiedState)
SymbolicStateT = TypeVar("SymbolicStateT", bound=SymbolicKeyed)
CallT = TypeVar("CallT", bound=IdentifiedCall)
# the protocol only CONSUMES states and calls, so its parameters are contravariant
StateT_contra = TypeVar("StateT_contra", bound=IdentifiedState, contravariant=True)
CallT_contra = TypeVar("CallT_contra", bound=IdentifiedCall, contravariant=True)


class SymbolicModel(Protocol[StateT_contra, SymbolicStateT, CallT_contra]):
    """What a domain author models. Every method sees the SYMBOLIC state only, except
    `project`, whose whole job is to leave geometry behind."""

    @property
    def model_version(self) -> ModelVersion:
        ...

    def project(self, state: StateT_contra, /) -> SymbolicStateT:
        ...

    def apply(self, sym: SymbolicStateT, call: CallT_contra, /) -> SymbolicStateT:
        ...

    def applicable(self, sym: SymbolicStateT, call: CallT_contra, /) -> CallValidation:
        ...

    def plan(self, sym: SymbolicStateT, identities: FrozenSet[str], /) -> PlannerResult:
        ...


class DerivedDomainServices(Generic[StateT, SymbolicStateT, CallT]):
    """`DomainServices[StateT, SymbolicStateT, CallT]` derived from a `SymbolicModel`."""

    def __init__(
        self,
        model: SymbolicModel[StateT, SymbolicStateT, CallT],
        *,
        apply_world: Optional[Callable[[StateT, CallT], StateT]] = None,
    ) -> None:
        self.model = model
        self._apply_world = apply_world

    @property
    def model_version(self) -> ModelVersion:
        return self.model.model_version

    def plan(self, symbolic_state: SymbolicStateT, state: StateT, /) -> PlannerResult:
        return self.model.plan(symbolic_state, state.identities())      # identities only

    def ground(self, state: StateT, call: CallT, /) -> Optional[UngroundedCall[CallT]]:
        return ground_by_identity(state, call)

    def evaluate(self, symbolic_state: SymbolicStateT, call: CallT, /) -> CallValidation:
        return self.model.applicable(symbolic_state, call)

    def predict(self, symbolic_state: SymbolicStateT, state: StateT, call: CallT, /) -> Prediction:
        return Prediction(
            symbolic_key=self.model.apply(symbolic_state, call).symbolic_key(),
            world_key=(
                self._apply_world(state, call).world_key()
                if self._apply_world is not None else None
            ),
        )

    def monitor(
        self, pre_symbolic: SymbolicStateT, result: ExecutionResult[StateT, CallT], /
    ) -> Tuple[ExecutionDiscrepancy[CallT], ...]:
        call = result.call
        if result.outcome is not ExecutionOutcome.SUCCESS:
            return (ExecutionDiscrepancy(
                kind=DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL, call=call,
                message=f"symbolically applicable {call} did not succeed: outcome="
                        f"{result.outcome}, failure_class={result.failure_class}, "
                        f"detail={result.detail!r}",
                model_version=self.model_version,
            ),)
        try:
            predicted_symbolic = self.model.apply(pre_symbolic, call).symbolic_key()
            observed_symbolic = self.model.project(result.post_state).symbolic_key()
            predicted_world = observed_world = None
            if self._apply_world is not None:
                predicted_world = self._apply_world(result.pre_state, call).world_key()
                observed_world = result.post_state.world_key()
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(
                f"{type(self.model).__name__} raised {type(error).__name__} while the "
                f"monitor predicted the effect of {call}: {error}"
            ) from error
        if predicted_symbolic != observed_symbolic or predicted_world != observed_world:
            return (ExecutionDiscrepancy(
                kind=DiscrepancyKind.STATE_EFFECT_MISMATCH, call=call,
                predicted_world_key=predicted_world, observed_world_key=observed_world,
                predicted_symbolic_key=predicted_symbolic,
                observed_symbolic_key=observed_symbolic,
                message=f"{call} succeeded but realized a different state than the model "
                        f"predicted",
                model_version=self.model_version,
            ),)
        return ()


__all__ = ["DerivedDomainServices", "SymbolicModel"]
