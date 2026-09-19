"""The environment base (DK2) — `shared.contracts.Environment` with the mechanics that
BoxPush's adapter and the R5 probe both hand-write (plus the BoxPush-only case-(c) helpers,
recorded in `docs/decisions/DK1_DOMAIN_PACKAGE.md` §"DK2 — kit extraction record"), so an
author supplies only the parts that are genuinely theirs:

    _reset(seed) -> state            the initial authoritative state
    _attempt(call, pre) -> result    ONE executive attempt against the author's backend,
                                     returning `self.succeeded(...)` / `self.failed(...)`
                                     (or a MalformedCall / UngroundedCall of their own)
    _is_terminal(state) -> bool      the terminal test
    _observe(state) -> object        optional: the public observation. The default returns
                                     the state's `canonical()` (a FULLY OBSERVABLE default —
                                     the V1 assumption `ProjectionTrack` also makes; a domain
                                     with a narrower public channel overrides it); always
                                     deep-copied on the way out (R6)
    _render(state) -> object         optional: never a state source

AUTHORITY MODEL — value-state domains. The base holds the authoritative state as a VALUE:
`reset` installs `_reset(seed)`, and after a completed attempt the value the author returned
in `result.post_state` becomes the current state. That is exactly the probe's model, where
`_attempt` IS the backend. It is NOT the adapter's model: the adapter re-reads a mutable
external simulator after every attempt (`box_push_v1_adapter.py:170-173,267`), so a
mid-attempt fault there leaves a changed world that the next cycle's sync re-reads. With
this base a mid-attempt raise leaves the cached pre-attempt value in place. A domain that
wraps an EXTERNAL MUTABLE simulator must therefore either keep its authoritative state as a
value derived inside `_attempt` from a fresh read, or not use this base as-is; a re-read
hook is deliberately not added until a real such domain exists (DEFERRED, owner choice).
Only `_attempt` is wrapped into the typed fault channel; a raise from `_reset`, `_observe`
or `_is_terminal` escapes untyped, as in the probe.

What the base does, extracted from `box_push_v1_adapter.py` (line refs) and
`tests/probe_counter.py::CounterEnvironment`:

- reset-before-use latch: any other call first raises the typed refusal whose message
  begins `"refused:"` (adapter `:704-711`, probe `:345-352`; `shared/faults.py:69-71`);
- post-terminal refusal, same kind and prefix (adapter `:230-239`, probe `:290-295`);
- call type check -> `MalformedCall` RETURNED, never raised (adapter `:240-244`, probe `:296`);
- identity grounding -> `UngroundedCall`, via the one kit `ground_by_identity` (adapter
  `:274-294`, probe `:298-299`) — identity membership only, never feasibility;
- the authoritative state advances to `result.post_state` after a completed attempt;
- `succeeded` / `failed` result builders with `StepAccounting(executive_steps=1, ...)`
  (adapter `:481-490`, probe `:307-336`). `failed` derives `PARTIAL_EXECUTION` only when the
  world changed and otherwise REQUIRES the author to choose `UNCHANGED` vs
  `BACKEND_REJECTED_BEFORE_TRANSITION` — never a default (environment-backend rule: "Never
  normalize all failures into unchanged state"). Builders never set `raw_label`;
- an exception escaping `_attempt` becomes the typed `BACKEND_API_EXCEPTION` fault carrying
  the case-(c) provenance key `primitive_steps_before_failure=N` (`shared/faults.py:69-74`;
  parsed by `runtime/loop.py`), N being the primitives the author reported through
  `note_primitive_steps` before the raise — never a `FAILURE` result (that would conflate
  the fault and discrepancy channels). A typed `InfrastructureFaultError` raised by the
  author passes through untouched: this module never catches one. From inside `_attempt`
  an author raises `self.mid_attempt_fault(...)` (which carries the key) — never a refusal,
  and never a `MalformedCall`/`UngroundedCall` after primitives ran (an attempt that reached
  the executor consumes one step, Decision 2);
- `executed` is a per-episode DIAGNOSTIC list of completed calls (the probe's convenience),
  reset by `reset()`; nothing in the kit or runtime reads it.

This is the ONLY kit module that raises faults (imports `shared.faults`).
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Generic, List, Optional, Type, TypeVar

from kit.protocols import IdentifiedCall, IdentifiedState, ground_by_identity
from shared.execution import (
    ExecutionOutcome,
    ExecutionResult,
    FailureStateClass,
    StepAccounting,
)
from shared.faults import FaultKind, InfrastructureFault, InfrastructureFaultError
from shared.skills import MalformedCall, UngroundedCall

StateT = TypeVar("StateT", bound=IdentifiedState)
CallT = TypeVar("CallT", bound=IdentifiedCall)

#: The exact case-(c) provenance key the loop parses (`runtime/loop.py::_CASE_C_KEY`).
CASE_C_KEY = "primitive_steps_before_failure"
#: The refusal prefix the fault channel documents (`shared/faults.py:69-71`).
REFUSED = "refused:"


class EnvironmentBase(ABC, Generic[StateT, CallT]):
    """Subclass, set `call_type`, implement the three hooks."""

    #: the domain's grounded call type — anything else is a `MalformedCall`
    call_type: Type[CallT]

    def __init__(self) -> None:
        if not hasattr(type(self), "call_type"):
            raise TypeError(
                f"{type(self).__name__} must set `call_type` to the domain's call class"
            )
        self._state: Optional[StateT] = None
        self._primitive_steps = 0
        self.executed: List[CallT] = []

    # ── author hooks ──────────────────────────────────────────────────────────────
    @abstractmethod
    def _reset(self, seed: Optional[int]) -> StateT:
        """The initial authoritative state (deterministic unless the domain uses `seed`)."""

    @abstractmethod
    def _attempt(
        self, call: CallT, pre: StateT
    ) -> ExecutionResult[StateT, CallT] | MalformedCall | UngroundedCall[CallT]:
        """One executive attempt. Return `self.succeeded(...)` or `self.failed(...)`; call
        `self.note_primitive_steps(n)` as primitives run so a raise mid-attempt carries the
        right provenance."""

    @abstractmethod
    def _is_terminal(self, state: StateT) -> bool:
        ...

    def _observe(self, state: StateT) -> object:
        canonical = getattr(state, "canonical", None)
        return canonical() if callable(canonical) else state

    def _render(self, state: StateT) -> object:
        return str(state)

    # ── the contract ──────────────────────────────────────────────────────────────
    def reset(self, *, seed: Optional[int] = None) -> StateT:
        self._state = self._reset(seed)
        self.executed = []
        return self._state

    def observe(self) -> object:
        return copy.deepcopy(self._observe(self._require()))

    def export_full_state(self) -> StateT:
        return self._require()

    def execute_skill(
        self, call: CallT, /
    ) -> ExecutionResult[StateT, CallT] | MalformedCall | UngroundedCall[CallT]:
        state = self._require()
        if self._is_terminal(state):
            raise self._refuse("execution after the terminal state")
        if not isinstance(call, self.call_type):
            return MalformedCall(
                reason=f"execute_skill requires a {self.call_type.__name__}, "
                       f"got {type(call).__name__}",
                raw=repr(call),
            )
        ungrounded = ground_by_identity(state, call)
        if ungrounded is not None:
            return ungrounded
        self._primitive_steps = 0
        try:
            result = self._attempt(call, state)
        except InfrastructureFaultError:
            raise                                   # already typed: never re-wrap
        except Exception as error:
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.BACKEND_API_EXCEPTION,
                message=f"{type(self).__name__}._attempt raised "
                        f"{type(error).__name__}: {error}",
                detail=f"{CASE_C_KEY}={self._primitive_steps}",
                source=f"{type(self).__name__}._attempt",
            )) from error
        if isinstance(result, ExecutionResult):
            self._state = result.post_state
            self.executed.append(call)
        return result

    def is_terminal(self) -> bool:
        return self._is_terminal(self._require())

    def render(self) -> object:
        return self._render(self._require())

    # ── helpers for `_attempt` ────────────────────────────────────────────────────
    def note_primitive_steps(self, count: int = 1) -> None:
        """Record primitives that ran in the current attempt (case-(c) provenance)."""
        if count < 0:
            raise ValueError("primitive step count cannot be negative")
        self._primitive_steps += count

    @property
    def primitive_steps_this_attempt(self) -> int:
        return self._primitive_steps

    def succeeded(
        self, call: CallT, pre: StateT, post: StateT, *,
        primitive_steps: Optional[int] = None, detail: str = "",
    ) -> ExecutionResult[StateT, CallT]:
        """The intended effect was realized. `primitive_steps` defaults to those noted."""
        return ExecutionResult(
            call=call, outcome=ExecutionOutcome.SUCCESS, pre_state=pre, post_state=post,
            accounting=self._accounting(primitive_steps), detail=detail,
        )

    def failed(
        self, call: CallT, pre: StateT, post: StateT, *,
        failure_class: Optional[FailureStateClass] = None,
        outcome: ExecutionOutcome = ExecutionOutcome.FAILURE,
        primitive_steps: Optional[int] = None, detail: str = "",
    ) -> ExecutionResult[StateT, CallT]:
        """The intended effect was NOT realized. When the world changed the class is
        `PARTIAL_EXECUTION`; when it did not, the author must say whether the backend
        declined before any transition or attempted one and changed nothing."""
        if outcome is ExecutionOutcome.SUCCESS:
            raise ValueError("failed() cannot build a SUCCESS result; use succeeded()")
        changed = not pre.same_world(post)
        if changed:
            if failure_class is not None and failure_class is not FailureStateClass.PARTIAL_EXECUTION:
                raise ValueError(
                    f"the world changed during {call}, so the failure class is "
                    f"PARTIAL_EXECUTION, not {failure_class}"
                )
            failure_class = FailureStateClass.PARTIAL_EXECUTION
        elif failure_class is None:
            raise ValueError(
                f"{call} failed without changing the world: pass failure_class="
                f"FailureStateClass.UNCHANGED (the backend attempted and changed nothing) or "
                f"FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION (it declined before "
                f"attempting) — the kit never assumes which"
            )
        return ExecutionResult(
            call=call, outcome=outcome, pre_state=pre, post_state=post,
            accounting=self._accounting(primitive_steps), failure_class=failure_class,
            detail=detail,
        )

    def _refuse(self, what: str, detail: str = "") -> InfrastructureFaultError:
        """A pre-attempt caller-protocol refusal (zero steps, world untouched). Private:
        never raise a refusal from `_attempt` — the loop would charge zero steps for an
        attempt that reached the executor; use `mid_attempt_fault` there."""
        return InfrastructureFaultError(InfrastructureFault(
            kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
            message=f"{REFUSED} {what}", detail=detail,
            source=f"{type(self).__name__}.execute_skill",
        ))

    def mid_attempt_fault(
        self, kind: FaultKind, message: str, *, source: str = ""
    ) -> InfrastructureFaultError:
        """A fault raised MID-attempt by the author's backend code (a malformed backend
        value, a runaway cap): carries the case-(c) key with the primitives noted so far."""
        return InfrastructureFaultError(InfrastructureFault(
            kind=kind, message=message, detail=f"{CASE_C_KEY}={self._primitive_steps}",
            source=source or f"{type(self).__name__}._attempt",
        ))

    # ── internals ─────────────────────────────────────────────────────────────────
    def _accounting(self, primitive_steps: Optional[int]) -> StepAccounting:
        steps = self._primitive_steps if primitive_steps is None else primitive_steps
        return StepAccounting(executive_steps=1, primitive_steps=steps)

    def _require(self) -> StateT:
        if self._state is None:
            raise InfrastructureFaultError(InfrastructureFault(
                kind=FaultKind.EXECUTOR_MONITOR_PROTOCOL_FAILURE,
                message=f"{REFUSED} reset() must precede any other environment call",
                source=f"{type(self).__name__}._require",
            ))
        return self._state


__all__ = ["CASE_C_KEY", "EnvironmentBase", "REFUSED"]
