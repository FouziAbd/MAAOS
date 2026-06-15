"""
DeterministicGridUpdater — grid-based belief state for MiniGrid-style POMDP envs.

Maintains an N×M belief grid where each cell stores what the agent believes
occupies that location:
    unknown       — never observed
    empty         — observed as floor / empty
    wall          — observed as wall
    delivery_zone — delivery zone cell (prior knowledge)
    target_N      — target object N is at this cell
    decoy_N       — decoy object N is at this cell
    agent         — another agent last observed here

The grid is initialised from prior knowledge passed via initial_entities["grid"]
and is updated every step by sweeping the agent's partial local view (obs image)
into world coordinates.

Agent self-state (position, carrying) is dead-reckoned from action + reward.
"""
import sys
import os
from copy import deepcopy
from typing import Any, Dict, List, Optional

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
for _p in (_THIS_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_layer.storage.base_belief_updater import BaseBeliefUpdater

# ── Direction / action constants ──────────────────────────────────────────────
_DIR_VECTORS = {
    0: ( 1,  0),   # RIGHT
    1: ( 0,  1),   # DOWN
    2: (-1,  0),   # LEFT
    3: ( 0, -1),   # UP
}

_RIGHT_VEC = {
    0: ( 0,  1),   # facing RIGHT → right side is DOWN
    1: (-1,  0),   # facing DOWN  → right side is LEFT
    2: ( 0, -1),   # facing LEFT  → right side is UP
    3: ( 1,  0),   # facing UP    → right side is RIGHT
}

_ACTION_TURN_LEFT        = 0
_ACTION_TURN_RIGHT       = 1
_ACTION_MOVE_FORWARD     = 2
_ACTION_STAY             = 3
_ACTION_PICK_OR_INTERACT = 4
_ACTION_DROP             = 5
_ACTION_COOPERATE        = 6

_MOVE_SUCCESS_THRESHOLD = -0.06   # reward > this → MOVE_FORWARD succeeded

# MiniGrid cell type / colour indices
_TYPE_UNSEEN = 0
_TYPE_EMPTY  = 1
_TYPE_WALL   = 2
_TYPE_FLOOR  = 3
_TYPE_BOX    = 7
_TYPE_AGENT  = 10
_COLOR_GREEN = 1   # delivery zone floor
_COLOR_RED   = 0   # TARGET_OBJECT box
_COLOR_BLUE  = 2   # DECOY_OBJECT box


class DeterministicGridUpdater(BaseBeliefUpdater):
    """
    Grid-based belief updater for CooperativeSearchTransport.

    Parameters
    ----------
    initial_entities : dict
        Must contain:
          "self":     { direction, position, carrying_object_id,
                        engaged_object_ids, delivered_object_ids }
          "grid":     { "cells": [[label, ...], ...] }   — W×H list-of-lists
          "object_N": { is_target, required_agents, status }
    grid_width, grid_height : int
        Dimensions for boundary clamping (default 12).
    """

    estimator_type: str = "deterministic_grid"

    def __init__(
        self,
        initial_entities: Dict[str, Any],
        grid_width:  int = 12,
        grid_height: int = 12,
    ):
        self._width  = grid_width
        self._height = grid_height
        self._initial  = deepcopy(initial_entities)
        self._entities = deepcopy(initial_entities)

        # Extract grid from initial entities; create blank if absent
        init_cells = self._entities.get("grid", {}).get("cells")
        if init_cells:
            self._grid: List[List[str]] = [list(col) for col in init_cells]
        else:
            self._grid = [["unknown"] * grid_height for _ in range(grid_width)]

    # ── BaseBeliefUpdater interface ───────────────────────────────────────────

    def update_entity(self, entity_snapshot: dict) -> None:
        action   = entity_snapshot.get("action")
        reward   = entity_snapshot.get("reward", 0.0)
        self_obs = entity_snapshot.get("entities", {}).get("self", {})

        # 1. Update direction from observation (always authoritative)
        if "direction" in self_obs:
            self._entities["self"]["direction"] = int(self_obs["direction"])

        # 2. Dead-reckon self state from action + reward FIRST — the observation
        #    image is generated from the post-action position, so the position must
        #    be updated before projecting the image into world coordinates.
        self._apply_action(action, reward)

        # 3. Update belief grid from raw local-view image (uses updated position)
        image = self_obs.get("image")
        if image is not None:
            pos       = self._entities["self"].get("position")
            direction = self._entities["self"].get("direction", 0)
            if pos is not None:
                self._update_grid_from_image(image, pos, direction)

        # 4. Sync grid entity so get_all_entities() stays current
        self._entities["grid"] = {"cells": [list(col) for col in self._grid]}

    def get_entity_state(self, entity_id: str) -> dict:
        if entity_id == "grid":
            return {"cells": [list(col) for col in self._grid]}
        return deepcopy(self._entities.get(entity_id, {}))

    def get_all_entities(self) -> dict:
        result = deepcopy(self._entities)
        result["grid"] = {"cells": [list(col) for col in self._grid]}
        return result

    def get_uncertainty(self, entity_id: str) -> float:
        if entity_id == "grid":
            known = sum(
                1 for x in range(self._width)
                for y in range(self._height)
                if self._grid[x][y] != "unknown"
            )
            return known / (self._width * self._height)
        return 1.0 if entity_id in self._entities else 0.0

    def reset(self) -> None:
        self._entities = deepcopy(self._initial)
        init_cells = self._entities.get("grid", {}).get("cells")
        if init_cells:
            self._grid = [list(col) for col in init_cells]
        else:
            self._grid = [["unknown"] * self._height for _ in range(self._width)]

    # ── Grid update from local view ───────────────────────────────────────────

    def _update_grid_from_image(self, image, pos: list, direction: int) -> None:
        """Convert each cell in the partial view image to a world (x,y) and update the grid."""
        V   = len(image)
        mid = V // 2
        fwd = _DIR_VECTORS[direction % 4]
        rgt = _RIGHT_VEC[direction % 4]

        for r in range(V):
            for c in range(V):
                # MiniGrid image convention: first index = lateral (left/right),
                # second index = depth (0 = farthest ahead, V-1 = agent's row).
                ahead = (V - 1) - c   # 0 = agent's row, V-1 = farthest ahead
                side  = r - mid       # negative = left, 0 = center, positive = right

                if ahead == 0 and side == 0:
                    continue          # agent's own cell (lateral=mid, depth=V-1) — skip

                wx = pos[0] + ahead * fwd[0] + side * rgt[0]
                wy = pos[1] + ahead * fwd[1] + side * rgt[1]

                if not (0 <= wx < self._width and 0 <= wy < self._height):
                    continue

                label = self._image_cell_to_label(image[r][c], wx, wy)
                if label is not None:
                    self._grid[wx][wy] = label

    def _image_cell_to_label(self, cell, wx: int, wy: int) -> Optional[str]:
        """Translate one MiniGrid (type, color, state) cell to a grid label."""
        t = int(cell[0])
        c = int(cell[1])

        if t == _TYPE_UNSEEN:
            return None                           # unlit cell — don't overwrite
        if t == _TYPE_WALL:
            return "wall"
        if t == _TYPE_EMPTY:
            return "empty"
        if t == _TYPE_FLOOR:
            return "delivery_zone" if c == _COLOR_GREEN else "empty"
        if t == _TYPE_BOX:
            existing = self._grid[wx][wy]
            if c == _COLOR_RED:                   # TARGET_OBJECT
                if existing.startswith("target_"):
                    return existing               # preserve known identity
                oid = self._find_object_near([wx, wy], is_target=True)
                return f"target_{oid}" if oid is not None else "target_?"
            if c == _COLOR_BLUE:                  # DECOY_OBJECT
                if existing.startswith("decoy_"):
                    return existing
                oid = self._find_object_near([wx, wy], is_target=False)
                return f"decoy_{oid}" if oid is not None else "decoy_?"
        if t == _TYPE_AGENT:
            return "agent"
        return "empty"

    # ── Object position helpers ───────────────────────────────────────────────

    def get_object_grid_pos(self, oid: int) -> Optional[List[int]]:
        """Return [x, y] of object_N from the grid, or None if not on grid."""
        obj  = self._entities.get(f"object_{oid}", {})
        kind = "target" if obj.get("is_target") else "decoy"
        lbl  = f"{kind}_{oid}"
        for x in range(self._width):
            for y in range(self._height):
                if self._grid[x][y] == lbl:
                    return [x, y]
        return None

    def _find_object_near(self, pos: list, is_target: bool) -> Optional[int]:
        """
        Find the oid of the closest available object of the given type.
        Searches by current grid position (Manhattan distance).
        """
        best_oid, best_dist = None, float("inf")
        for eid, edata in self._entities.items():
            if not eid.startswith("object_"):
                continue
            if edata.get("is_target") != is_target:
                continue
            if edata.get("status") in ("delivered", "carried_by_self"):
                continue
            oid     = int(eid.split("_")[1])
            obj_pos = self.get_object_grid_pos(oid)
            if obj_pos is not None:
                d = abs(obj_pos[0] - pos[0]) + abs(obj_pos[1] - pos[1])
                if d < best_dist:
                    best_dist, best_oid = d, oid
        return best_oid

    def _on_delivery_zone(self, pos: list) -> bool:
        x, y = int(pos[0]), int(pos[1])
        return (0 <= x < self._width and 0 <= y < self._height
                and self._grid[x][y] == "delivery_zone")

    # ── Dead-reckoning ────────────────────────────────────────────────────────

    def _apply_action(self, action: Optional[int], reward: float) -> None:
        if action is None:
            return

        self_state = self._entities.setdefault("self", {})
        direction  = self_state.get("direction", 0)

        if action == _ACTION_MOVE_FORWARD:
            if reward > _MOVE_SUCCESS_THRESHOLD:
                pos = self_state.get("position")
                if pos is not None:
                    dx, dy = _DIR_VECTORS[direction % 4]
                    nx = max(0, min(self._width  - 1, pos[0] + dx))
                    ny = max(0, min(self._height - 1, pos[1] + dy))
                    self_state["position"] = [nx, ny]

        elif action == _ACTION_PICK_OR_INTERACT:
            if reward > 0:
                pos = self_state.get("position")
                if pos is not None:
                    dx, dy = _DIR_VECTORS[direction % 4]
                    fx, fy = pos[0] + dx, pos[1] + dy
                    if 0 <= fx < self._width and 0 <= fy < self._height:
                        label = self._grid[fx][fy]
                        if label.startswith("target_") or label.startswith("decoy_"):
                            try:
                                oid = int(label.split("_")[1])
                            except (IndexError, ValueError):
                                return
                            obj = self._entities.setdefault(f"object_{oid}", {})
                            req = obj.get("required_agents", 1)
                            if req <= 1:
                                # Solo pickup: object is gone from the grid immediately.
                                self._grid[fx][fy] = "empty"
                                obj["status"] = "carried_by_self"
                                self_state["carrying_object_id"] = oid
                            else:
                                # Cooperative partial latch: in the real env the object
                                # stays on the grid until ALL required agents have latched.
                                # Do NOT clear the grid cell — the image update will keep
                                # it accurate.  Switch to full-hold only when the image
                                # later shows the cell as empty (both agents latched).
                                obj["status"] = "engaged_by_self"
                                eng = self_state.get("engaged_object_ids", [])
                                if oid not in eng:
                                    eng.append(oid)
                                self_state["engaged_object_ids"] = eng

        elif action == _ACTION_DROP:
            cid = self_state.get("carrying_object_id")
            pos = self_state.get("position")
            if cid is not None:
                obj = self._entities.get(f"object_{cid}", {})
                if pos and self._on_delivery_zone(pos):
                    obj["status"] = "delivered"
                    delivered = self_state.get("delivered_object_ids", [])
                    if cid not in delivered:
                        delivered.append(cid)
                    self_state["delivered_object_ids"] = delivered
                else:
                    obj["status"] = "available"
                    # Put object back on grid at agent's current position
                    if pos:
                        kind = "target" if obj.get("is_target") else "decoy"
                        px, py = int(pos[0]), int(pos[1])
                        if 0 <= px < self._width and 0 <= py < self._height:
                            self._grid[px][py] = f"{kind}_{cid}"
                self_state["carrying_object_id"] = None

            for oid in list(self_state.get("engaged_object_ids", [])):
                obj = self._entities.get(f"object_{oid}", {})
                obj["status"] = "available"
            self_state["engaged_object_ids"] = []
