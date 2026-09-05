"""Domain-services contract (R4 — report Phase 4 item 1: "a `DomainBundle` or equivalent
application-level composition object containing only the domain services the runtime
needs").

Through R3 the executive loop reached the BoxPush model directly: it imported the frozen
domain constants and the concrete symbolic planner/applicability/predictor/monitor functions
and applied them itself, and it performed the identity grounding check over agents, boxes,
and the task zone in its own body. R4 moves every one of those domain-owned operations
behind this narrow protocol so the loop can hold an injected implementation and never name
a domain concept.

The surface is exactly the set of domain operations the V1 cycle performs, in the order it
performs them — nothing hypothetical was added:

    plan      — the symbolic plan channel (PlanFound / NoPlan / PlannerFailure) for the
                current symbolic state; the authoritative state is passed alongside because
                a domain may need it to fix the grounding universe (BoxPush does);
    ground    — grounding-before-applicability (P4 decisions §19.1 item 5): is every
                identity in the call known to the authoritative state? A typed
                `UngroundedCall` is the domain's answer when not;
    evaluate  — symbolic applicability (the typed `CallValidation` verdict);
    predict   — the recorded, post-decision prediction keys on both Decision-13 bases;
    monitor   — typed execution discrepancies for one realized result against the belief
                the attempt was chosen under. May raise `ValueError` for a wiring error;
                the loop converts that escape into the established infrastructure fault.

Obligations carried from the frozen V1 contract:

- `plan` and `evaluate` decide from declarative symbolic literals; no implementation may
  consult backend reachability/feasibility/rollout (the forbidden oracle). Nothing in this
  protocol gives an implementation an environment handle.
- `predict` is computed AFTER the policy decision by the loop; it records expectations for
  the monitor and the trace and is never consulted while choosing.
- Prediction keys are the frozen typed comparison keys (`WorldKey` / `SymbolicKey`) so a
  domain cannot silently mix the two bases.

Generic only in the domain-owned types the report names: the authoritative state, the
symbolic state, and the grounded call. The verdict/result/discrepancy channels stay the
existing shared typed results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Tuple, TypeVar, runtime_checkable

from shared.comparison_keys import SymbolicKey, WorldKey
from shared.discrepancy import ExecutionDiscrepancy
from shared.execution import ExecutionResult
from shared.planner_result import PlannerResult
from shared.skills import CallValidation, UngroundedCall
from shared.value_contracts import RuntimeCall, RuntimeState
from shared.versioning import ModelVersion

# R6: bounded by the structural value protocols so `monitor` can be typed on the generic
# `ExecutionResult[StateT, CallT]` — the runtime only ever handles states/calls that satisfy
# them anyway (they are the bounds of the loop's own parameters).
StateT_contra = TypeVar("StateT_contra", bound=RuntimeState, contravariant=True)
SymbolicStateT_contra = TypeVar("SymbolicStateT_contra", contravariant=True)
CallT_contra = TypeVar("CallT_contra", bound=RuntimeCall, contravariant=True)


@dataclass(frozen=True, slots=True)
class Prediction:
    """The recorded post-decision expectation on both Decision-13 bases. Either key is
    None exactly when the domain has no prediction on that basis (e.g. a skill outside
    the symbolic model)."""
    symbolic_key: Optional[SymbolicKey] = None
    world_key: Optional[WorldKey] = None


@runtime_checkable
class DomainServices(Protocol[StateT_contra, SymbolicStateT_contra, CallT_contra]):
    """The domain-owned operations one executive cycle needs, and nothing else."""

    @property
    def model_version(self) -> ModelVersion:
        """The symbolic model version stamped on every trace entry and provenance."""
        ...

    def plan(
        self, symbolic_state: SymbolicStateT_contra, state: StateT_contra, /
    ) -> PlannerResult:
        """The typed plan channel for the current symbolic state.

        `state` is supplied for IDENTITY grounding only (which objects exist, so the
        planner can enumerate grounded calls). An implementation must not consult it for
        geometry, occupancy, reachability, or any other feasibility signal: planning
        decides from the declarative symbolic literals alone (Decision 6). For a fixed
        set of identities the result must not depend on `state`.
        """
        ...

    def ground(
        self, state: StateT_contra, call: CallT_contra, /
    ) -> Optional[UngroundedCall]:
        """Identity grounding against the authoritative state: the typed rejection when
        the call names an unknown identity, None when every identity is known."""
        ...

    def evaluate(
        self, symbolic_state: SymbolicStateT_contra, call: CallT_contra, /
    ) -> CallValidation:
        """Symbolic applicability verdict for the call against the symbolic state."""
        ...

    def predict(
        self,
        symbolic_state: SymbolicStateT_contra,
        state: StateT_contra,
        call: CallT_contra,
        /,
    ) -> Prediction:
        """Post-decision expectation keys for the call (recorded, never consulted)."""
        ...

    def monitor(
        self,
        pre_symbolic: SymbolicStateT_contra,
        result: ExecutionResult[StateT_contra, CallT_contra],
        /,
    ) -> Tuple[ExecutionDiscrepancy, ...]:
        """Typed discrepancies between the model's prediction (from the symbolic state the
        attempt was chosen under) and the authoritative realized result."""
        ...
