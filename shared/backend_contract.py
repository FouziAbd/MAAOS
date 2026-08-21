"""The V1 backend contract (SUPERVISOR_P0_P4_CONTRACT.md:185, :192-198).

P0 freezes the INTERFACE only. P1 implements it as a wrapper over the existing BoxPush backend,
reusing the existing composed skill implementations rather than reimplementing them.

Shape required by the project environment-backend rule:
    reset() / observe() / execute_skill(call) / export_full_state() / is_terminal() / render()

Obligations any implementation must satisfy (all traceable to P0_V1_DECISIONS):

  D4  `export_full_state()` builds the snapshot EXCLUSIVELY from `core_env.world`. Never from
      `core_env.grid`, never from the reward-derived belief layer, never from observations.
  D3  `execute_skill()` returns the raw backend label as provenance AND an authoritative typed
      outcome derived from world state. Crucially, `too_heavy` vs `blocked` must be re-derived
      from `world` (`required_agents` + actual post-transition state), because the backend's own
      inference reads the belief grid and is provably wrong when the partner blocks the landing
      cell (section18.md headline 0).
  D2  `execute_skill()` reports StepAccounting with executive_steps == 1 and a primitive count the
      WRAPPER measured by counting `env.step()` calls. Never `BaseSkill._steps`.
  D7  Malformed or ungrounded calls are rejected BEFORE execution and never re-grounded onto a
      different object. `_resolve_box`'s silent substitution must not survive the wrapper.
  D8  Execution after a terminal state is refused as an InfrastructureFault.
  D1  `CooperativePush` is executed as ONE executive skill; the wrapper owns both per-agent
      backend skill instances and latches the PAIR ORDERING / `partner_id` plumbing at invocation.
      It does NOT latch the front/rear tandem roles: `_assign_slots` re-derives those from live
      Manhattan distance on every `step()`, so they can flip mid-skill — which is exactly why
      `CooperativePush.predicted_world_effects` states the two terminal slots as a SET.
  D14 The adapter dispatches EXHAUSTIVELY on `SkillSignature.backend_dispatch_key`, over every
      registry skill including `Wait`, and keeps NO fallback arm. The existing factory
      `skill_executor_push.make_skill` has arms for only four tokens and silently returns
      `WaitSkill` for everything else (:373-386), which makes `"wait"`, `"Push"` and `""`
      observationally identical. An unknown token is a `MalformedCall`, never a substitution.
  D16 Argument translation is EXPLICIT and PER-SKILL. The adapter never calls
      `skill_executor_push.make_skill`, whose single `arg` means the box cell for
      `goto_push_pose`/`cooperate_push`, the DESTINATION cell for `push`, and falls back to
      nearest-target when `None`. It constructs the concrete skill classes directly:
      `GotoPushPoseSkill(agent_id, box=<cell of the grounded BoxId>)`,
      `CooperativePushSkill(agent_id, partner_id, box=<same cell>)` for both agents, and
      `PushSkill(agent_id, dest=None)` — the explicit encoding of push-to-zone, reached by
      validating `zone` against the single frozen delivery zone and refusing any other.
      Cells are DERIVED from the snapshot, never taken from a caller-supplied tuple. The pre-flight
      resolves IDENTITY ONLY and never gates the attempt on feasibility — an optimistic `in_pose`
      that is false in the world must surface as an ExecutionDiscrepancy (one executive step), not
      as a grounding fault. Post-flight verification is PER SKILL, because `GotoPushPose` moves no
      object: for the push skills, check that the box that moved is the grounded one; for
      `GotoPushPose`, compare the terminal agent cell against the grounded box's pose cell. A
      substitution is an InfrastructureFault with kind EXECUTOR_MONITOR_PROTOCOL_FAILURE —
      MISSING_GROUNDING is pre-execution and cannot coexist with an ExecutionResult. `_resolve_box`
      re-runs every step() against whatever grid the adapter supplies — falling back to
      `_nearest_undelivered_target` whenever the supplied cell is not a known undelivered target
      there — so a one-time pre-flight cannot close it and the adapter must supply a
      `world`-derived view, never the reward-derived belief grid. `Push` has no `_resolve_box`; its
      distinct hazard is `dest=None` pushing whatever occupies the front cell (Decision 16).

The contract deliberately exposes NO reachability, occupancy, collision or feasibility query.
Symbolic applicability must never be able to ask the backend whether something will work
(Decision 6 / supervisor :55).

That is a prohibition on ASKING WHETHER A SKILL WILL SUCCEED, not on geometry as such. The wrapper
sits on the grid and is *required* to compute geometry: deriving `GotoPushPose`'s authoritative
typed outcome from world state means comparing the agent's post-state against the pose cell
`B - D`, and D3's `too_heavy`-vs-`blocked` re-derivation means inspecting the landing cell. Both
are mandatory (Decision 13.5). What must never happen is a query, in either direction, that lets
symbolic applicability or the planner consult that geometry before choosing.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from shared.execution import ExecutionResult
from shared.skills import GroundedSkillCall, MalformedCall, UngroundedCall
from shared.state_snapshot import StateSnapshot


@runtime_checkable
class V1Environment(Protocol):
    """The only environment surface the executive layer may use."""

    def reset(self, *, seed: Optional[int] = None) -> StateSnapshot:
        """Reset and return the canonical initial state.

        Must be called before any other method: the backend's `world.agents` changes type from
        list to dict during reset (multi_agent_box_push_env.py:78-79 vs box_push_env.py:119-125),
        so stepping before reset raises.
        """
        ...

    def observe(self) -> Mapping[str, Any]:
        """Public per-agent observation channel.

        Kept separate from `export_full_state()` so the exact/debug state never leaks into a
        partial-observation consumer. V1's symbolic track does not read this.
        """
        ...

    def export_full_state(self) -> StateSnapshot:
        """Authoritative exact state, normalized from `core_env.world` only."""
        ...

    def execute_skill(
        self, call: GroundedSkillCall
    ) -> ExecutionResult | MalformedCall | UngroundedCall:
        """Execute one grounded executive skill.

        Returns `ExecutionResult` when the call reached the executor (one executive step), or a
        `MalformedCall`/`UngroundedCall` rejection when it did not (zero executive steps).

        `SymbolicallyInapplicable` is deliberately NOT in this union: symbolic applicability is
        the symbolic track's job, evaluated before the executor is ever called. Admitting it here
        would invite the wrapper — which sits on top of the geometry-bearing backend — to evaluate
        symbolic preconditions, and that is the oracle Decision 6 forbids.

        `OutsideSymbolicModel` is likewise absent, for the opposite reason: `Explore` and `Wait`
        are registry-valid and fully executable. Being outside the symbolic model is a symbolic-
        track verdict about prediction, not a reason for the executor to refuse the call.
        """
        ...

    def is_terminal(self) -> bool:
        ...

    def render(self) -> Any:
        """Optional. Note the backend's render path incidentally repairs `core_env.grid`
        (multi_agent_box_push_env.py:57-75), so rendered and headless runs can differ in grid
        contents. This does not affect `world` and therefore does not affect V1 state."""
        ...
