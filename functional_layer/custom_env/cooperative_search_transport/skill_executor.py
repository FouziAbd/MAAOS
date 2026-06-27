"""
Skill executor for CST centralized runner.

CST-specific skills the centralized LLM composes (carry mechanics):
    explore         -> found_target | found_decoy | explored   (generic, from shared_skills)
    goto_target     -> at_target | none_known | blocked
    goto_delivery   -> at_delivery | blocked
    pick            -> picked_solo | latched_coop | failed
    drop            -> delivered | dropped | nothing
    cooperate_move  -> moved | waiting_partner | arrived
    wait            -> done                                     (generic, from shared_skills)

Each skill runs primitive env steps in an inner loop until it reaches its single
specific outcome, then returns control (and a label) to the LLM.

Env-agnostic scaffolding (BaseSkill, ExploreSkill, WaitSkill, cell decoding and grid
navigation) lives in functional_layer/custom_env/shared_skills.py and is imported —
and re-exported — here so existing `from skill_executor import _cell_desc, …` callers
keep working.
"""

import sys
import os

_PKG_DIR    = os.path.dirname(os.path.abspath(__file__))      # cooperative_search_transport
_CST_ENV    = os.path.join(_PKG_DIR, "env")                   # where constants.py lives
_CUSTOM_ENV = os.path.abspath(os.path.join(_PKG_DIR, ".."))   # functional_layer/custom_env
for _p in (_PKG_DIR, _CST_ENV, _CUSTOM_ENV):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from typing import Optional
from constants import Actions

# Shared scaffolding — imported here AND re-exported (cst_centralized.py and others still
# do `from skill_executor import _cell_desc, _manhattan, …`).
from shared_skills import (  # noqa: F401  (re-exported)
    _cell_desc, _get_front_cell, _manhattan, _dir_to_action,
    _smart_nav_hint, _bfs_next_action, _frontier_explore,
    _target_cells, _decoy_cells, _nearest_target_cell,
    BaseSkill, ExploreSkill, WaitSkill,
)

# ── CST-specific constants ────────────────────────────────────────────────────
_DELIVERY_ZONE = [[1, 1], [2, 1], [1, 2], [2, 2]]


# ── CST-specific skills ───────────────────────────────────────────────────────

class GotoTargetSkill(BaseSkill):
    """Navigate to the nearest discovered target until it is directly in front."""

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        if _get_front_cell(obs) == "TARGET_OBJECT":
            return self._finish("at_target")

        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        grid   = entities.get("grid", {}).get("cells", [])
        goal   = _nearest_target_cell(grid, pos)
        if goal is None:
            return self._finish("none_known")

        self._steps += 1
        if self._timeout():
            self.label = "blocked"
            return int(Actions.STAY)

        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck

        direction = self_e.get("direction", 2)
        action, _ = _bfs_next_action(pos, goal, direction, grid)
        return action


class GotoDeliverySkill(BaseSkill):
    """Navigate to the (known) delivery zone until standing on it."""

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e = entities.get("self", {})
        pos    = self_e.get("position", [0, 0])
        if list(pos) in [list(c) for c in _DELIVERY_ZONE]:
            return self._finish("at_delivery")

        self._steps += 1
        if self._timeout():
            self.label = "blocked"
            return int(Actions.STAY)

        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck

        direction = self_e.get("direction", 2)
        grid      = entities.get("grid", {}).get("cells", [])
        goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
        action, _ = _bfs_next_action(pos, goal, direction, grid)
        return action


class PickSkill(BaseSkill):
    """Issue one PICK_OR_INTERACT and report the outcome read from the belief."""
    _MAX_STEPS = 3

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self._issued = False

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e = entities.get("self", {})
        if self_e.get("carrying_object_id") is not None:
            return self._finish("picked_solo")
        if self_e.get("engaged_object_ids"):
            return self._finish("latched_coop")

        if self._issued:
            # PICK already happened last step but belief shows neither outcome.
            return self._finish("failed")

        self._issued = True
        return int(Actions.PICK_OR_INTERACT)


class DropSkill(BaseSkill):
    """Issue one DROP and report whether it delivered, dropped, or did nothing."""
    _MAX_STEPS = 3

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self._issued = False
        self._had_carry = False

    def step(self, obs: dict, entities: dict) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e   = entities.get("self", {})
        carrying = self_e.get("carrying_object_id")

        if not self._issued:
            if carrying is None:
                return self._finish("nothing")
            self._had_carry = True
            self._issued = True
            return int(Actions.DROP)

        # Post-drop evaluation
        delivered = self_e.get("delivered_object_ids", [])
        if delivered:
            return self._finish("delivered")
        if self._had_carry and carrying is None:
            return self._finish("dropped")
        return self._finish("dropped")


class CooperativeMoveSkill(BaseSkill):
    """
    Joint carry of a fully-held cooperative object toward the delivery zone.
    Both engaged agents must be assigned this skill the same cycle. The move
    direction is derived from the SHARED object position so both agents agree
    (avoids the per-agent-direction deadlock).
    """

    def __init__(self, agent_id: str, partner_id: str):
        super().__init__(agent_id)
        self.partner_id = partner_id

    def step(self, obs: dict, entities: dict, partner_entities: Optional[dict] = None) -> int:
        if self.done:
            return int(Actions.STAY)

        self_e   = entities.get("self", {})
        engaged  = self_e.get("engaged_object_ids", [])
        pos      = self_e.get("position", [0, 0])
        grid     = entities.get("grid", {}).get("cells", [])

        on_delivery = list(pos) in [list(c) for c in _DELIVERY_ZONE]
        if on_delivery:
            return self._finish("arrived")

        # Partner must be engaged for a joint move to be possible.
        partner_engaged = False
        if partner_entities:
            partner_engaged = bool(partner_entities.get("self", {}).get("engaged_object_ids"))
        if not engaged or not partner_engaged:
            self._steps += 1
            if self._timeout():
                self.label = "waiting_partner"
                return int(Actions.STAY)
            return self._finish("waiting_partner")

        self._steps += 1
        if self._timeout():
            self.label = "waiting_partner"
            return int(Actions.STAY)

        # Shared reference position: midpoint of the two agents approximates the
        # held object, giving both agents the SAME BFS goal direction.
        direction = self_e.get("direction", 2)
        goal      = min(_DELIVERY_ZONE, key=lambda c: _manhattan(pos, c))
        action, _ = _bfs_next_action(pos, goal, direction, grid)

        # One leg = progress checkpoint: report 'moved' once we actually advance.
        unstuck = self._check_stuck(pos)
        if unstuck is not None:
            return unstuck
        if action == int(Actions.MOVE_FORWARD) and self._steps > 1:
            return self._finish("moved")
        return action


# ── Factory ───────────────────────────────────────────────────────────────────

def make_skill(agent_id: str, skill_name: str, arg: Optional[str] = None,
               partner_id: Optional[str] = None) -> BaseSkill:
    if skill_name == "explore":
        return ExploreSkill(agent_id)
    if skill_name == "goto_target":
        return GotoTargetSkill(agent_id)
    if skill_name == "goto_delivery":
        return GotoDeliverySkill(agent_id)
    if skill_name == "pick":
        return PickSkill(agent_id)
    if skill_name == "drop":
        return DropSkill(agent_id)
    if skill_name == "cooperate_move":
        return CooperativeMoveSkill(agent_id, partner_id or "")
    return WaitSkill(agent_id)
