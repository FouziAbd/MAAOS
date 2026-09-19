"""Domain `lamp` — the environment (BACKEND-BOUNDARY role).

This is the ONLY module of the package that may import a backend or a framework (your
simulator, numpy, ...). It must never import `model`, `app`, or `runtime`. Import a backend
INSIDE `make_environment()` so `import domains.lamp` stays offline; if the backend is
a framework the import guard bans (numpy, pettingzoo, ...), `validate-domain` tells you the
one line to add under tests/.

The environment is the sole authority on what physically happens. `kit.EnvironmentBase`
supplies the contract's mechanics (refusals, malformed/ungrounded calls, result assembly,
typed faults); you write three hooks.
"""
from __future__ import annotations

from typing import Optional

from kit import EnvironmentBase
from shared.execution import FailureStateClass

from .types import Call, Op, State


class Environment(EnvironmentBase[State, Call]):
    call_type = Call

    def _reset(self, seed: Optional[int]) -> State:
        # TODO(author): the initial authoritative state (deterministic unless you use `seed`)
        return State(switch_id="s1", on=False)

    def _is_terminal(self, state: State) -> bool:
        # TODO(author): when no further attempt is possible (the goal is NOT terminal by
        # itself; the runtime tests the goal separately)
        return False

    def _attempt(self, call: Call, pre: State):
        """One executive attempt. Return `self.succeeded(...)` when the intended effect was
        realized, `self.failed(...)` otherwise (say whether the world changed: the kit derives
        PARTIAL_EXECUTION when it did; otherwise choose UNCHANGED or
        BACKEND_REJECTED_BEFORE_TRANSITION). Call `self.note_primitive_steps(n)` as primitive
        steps run. A physical failure the symbolic model does not know about is EXPECTED —
        it is what the runtime reports as an ExecutionDiscrepancy."""
        # TODO(author): drive your backend here
        self.note_primitive_steps(1)
        post = State(pre.switch_id, on=call.op is Op.TURN_ON, tick=pre.tick + 1)
        if post.same_world(pre):
            return self.failed(call, pre, post, failure_class=FailureStateClass.UNCHANGED,
                               detail="already in the requested position")
        return self.succeeded(call, pre, post)


def make_environment() -> Environment:
    """A fresh environment; construct/import your backend HERE, not at module level."""
    return Environment()


__all__ = ["Environment", "make_environment"]
