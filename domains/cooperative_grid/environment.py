"""Domain `cooperative_grid` — the environment (BACKEND-BOUNDARY role).

The adapter between MAAOS and the domain-owned CooperativeGrid backend
(`functional_layer/custom_env/cooperative_grid/grid_env.py`, a PettingZoo ParallelEnv with a
MiniGrid-style renderer). This is the ONLY module of the package that may import it, and it
does so INSIDE `make_environment()` so `import domains.cooperative_grid` stays offline.

The backend is the sole authority on what physically happens. One high-level call runs
several primitive grid steps here (a `Goto` walks a backend-routed path one cell per step;
`CooperateOpen` is one joint PULL step; `ClearJam` is one SHAKE step). After every attempt the
authoritative `State` is derived from a fresh read of the mutable simulator (`snapshot()`),
including the door's jam — the designed hidden condition. `project()` in model.py drops it.

Rendering is the backend's: with `render_mode="human"` it draws and paces itself on every
primitive step; the adapter only passes the high-level call as a caption. Headless
(`render_mode=None`, the default) never imports pygame.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from kit import EnvironmentBase
from shared.execution import FailureStateClass

from .types import DOOR, AgentPose, Call, Cell, Door, Op, Place, State


class _Snapshot(Protocol):
    positions: Tuple[Tuple[str, int, int], ...]
    door_cell: Cell
    door_open: bool
    door_jammed: bool
    places: Tuple[Tuple[str, Tuple[Cell, ...]], ...]
    terminated: bool
    truncated: bool


class GridBackend(Protocol):
    """What the adapter needs from the backend (the PettingZoo env satisfies it)."""
    possible_agents: List[str]

    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None) -> object: ...
    def step(self, actions: Dict[str, int]) -> object: ...
    def snapshot(self) -> _Snapshot: ...
    def route(self, agent: str, targets: Tuple[Cell, ...]) -> Optional[List[int]]: ...
    def annotate(self, caption: str) -> None: ...
    def render(self) -> object: ...
    def close(self) -> None: ...


# the backend's primitive action codes (grid_env.py: NOOP, LEFT, RIGHT, UP, DOWN, PULL, SHAKE)
_NOOP, _PULL, _SHAKE = 0, 5, 6


class Environment(EnvironmentBase[State, Call]):
    call_type = Call

    def __init__(self, backend: GridBackend) -> None:
        super().__init__()
        self._backend = backend

    def close(self) -> None:
        """Release the backend's window, if it opened one (the demo calls this at the end)."""
        self._backend.close()

    # ── the three hooks ───────────────────────────────────────────────────────────────
    def _reset(self, seed: Optional[int]) -> State:
        self._backend.reset(seed=seed)
        return self._read()

    def _is_terminal(self, state: State) -> bool:
        return state.episode_over

    def _attempt(self, call: Call, pre: State):
        self._backend.annotate(str(call))
        if call.op is Op.GOTO:
            return self._goto(call, pre)
        if call.op is Op.COOPERATE_OPEN:
            return self._cooperate_open(call, pre)
        return self._clear_jam(call, pre)

    def _render(self, state: State) -> object:
        return self._backend.render()

    # ── one high-level skill = several primitive backend steps ────────────────────────
    def _goto(self, call: Call, pre: State):
        targets = pre.cells_of(call.target)
        if not targets:
            return self.failed(call, pre, pre, detail=f"{call.target} is not a place",
                               failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION)
        path = self._backend.route(call.agent, targets)
        if path is None:
            return self.failed(call, pre, pre, detail=f"no path to {call.target}",
                               failure_class=FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION)
        for move in path:
            self._backend.step(self._joint({call.agent: move}))
            self.note_primitive_steps(1)
        post = self._read()
        if post.place_of(call.agent) == call.target:
            return self.succeeded(call, pre, post)
        # the kit derives PARTIAL_EXECUTION when the world changed; otherwise nothing moved
        moved = not post.same_world(pre)
        return self.failed(call, pre, post, detail="the walk did not end at the place",
                           failure_class=None if moved else FailureStateClass.UNCHANGED)

    def _cooperate_open(self, call: Call, pre: State):
        partner = call.partner if call.partner is not None else call.agent
        self._backend.step(self._joint({call.agent: _PULL, partner: _PULL}))
        self.note_primitive_steps(1)
        post = self._read()
        if post.door.is_open:
            return self.succeeded(call, pre, post)
        return self.failed(call, pre, post, detail="the door did not move",
                           failure_class=FailureStateClass.UNCHANGED)

    def _clear_jam(self, call: Call, pre: State):
        self._backend.step(self._joint({call.agent: _SHAKE}))
        self.note_primitive_steps(1)
        post = self._read()
        if not post.door.jammed:
            return self.succeeded(call, pre, post)
        return self.failed(call, pre, post, detail="the door is still stuck",
                           failure_class=FailureStateClass.UNCHANGED)

    # ── reading the backend ───────────────────────────────────────────────────────────
    def _joint(self, actions: Dict[str, int]) -> Dict[str, int]:
        """A joint primitive action: NOOP for every agent not named."""
        return {a: actions.get(a, _NOOP) for a in self._backend.possible_agents}

    def _read(self) -> State:
        """The authoritative state as a VALUE derived from a fresh read of the simulator."""
        snap = self._backend.snapshot()
        agents = tuple(AgentPose(name, x, y) for name, x, y in snap.positions)
        dx, dy = snap.door_cell
        door = Door(DOOR, dx, dy, is_open=snap.door_open, jammed=snap.door_jammed)
        places = tuple(Place(name, tuple(cells)) for name, cells in snap.places)
        return State(agents=agents, door=door, places=places,
                     episode_over=snap.terminated or snap.truncated)


def make_environment(render_mode: Optional[str] = None, *, jammed_at_start: bool = True,
                     render_fps: Optional[int] = None,
                     expected_places: Sequence[str] = ("handle_left", "handle_right", "goal"),
                     ) -> Environment:
    """A fresh environment over a fresh backend; the backend is imported HERE, not at module
    level. Headless by default; `render_mode="human"` is the opt-in live view for the demo."""
    from functional_layer.custom_env.cooperative_grid.grid_env import CooperativeGridEnv

    backend = CooperativeGridEnv(render_mode=render_mode, jammed_at_start=jammed_at_start,
                                 render_fps=render_fps)
    provided = {name for name, _ in backend.places}
    missing = [p for p in expected_places if p not in provided]
    if missing:
        raise ValueError(f"the backend layout lacks the places {missing}")
    return Environment(backend)


__all__ = ["Environment", "GridBackend", "make_environment"]
