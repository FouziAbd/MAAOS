"""
CST observation parser — converts a raw MiniGrid obs dict into the
standard entity-snapshot format consumed by BeliefStateManager.

POMDP-correct: only parses fields directly visible in obs["image"]
and obs["direction"].  Internal fields (position, carrying status,
object status) are NOT set here; they are added by DeterministicGridUpdater.

Usage
-----
    from obs_parser import parse_cst_obs
    snapshot = parse_cst_obs(obs, agent_id="agent_0", view_size=3)
    belief_manager.update(action, reward, snapshot)
"""
import sys
import os

_ENV_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_ENV_DIR, "../../../.."))
for _p in (_ENV_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── MiniGrid encoding tables ──────────────────────────────────────────────────

_OBJ_TYPE_IDX = {
    0: "unseen", 1: "empty",  2: "wall", 3: "floor", 4: "door",
    5: "key",    6: "ball",   7: "box",  8: "goal",  9: "lava", 10: "agent",
}
_COLOR_IDX = {0: "red", 1: "green", 2: "blue", 3: "purple", 4: "yellow", 5: "grey"}

# CST-specific colour conventions (from objects.py)
# box red   → TARGET_OBJECT (requires ≥1 agent)
# box blue  → DECOY_OBJECT
# floor green → DELIVERY_ZONE

def _cell_desc(cell) -> str:
    """Translate a MiniGrid (type, color, state) cell to a readable label."""
    t, c = int(cell[0]), int(cell[1])
    if t == 0:  return "unseen"
    if t == 1:  return "empty"
    if t == 2:  return "WALL"
    if t == 3 and c == 1: return "DELIVERY_ZONE"
    if t == 3:  return "floor"
    if t == 7 and c == 0: return "TARGET_OBJECT"
    if t == 7 and c == 2: return "DECOY_OBJECT"
    if t == 10: return f"AGENT({_COLOR_IDX.get(c, '?')})"
    return f"{_OBJ_TYPE_IDX.get(t, '?')}({_COLOR_IDX.get(c, '?')})"


# ── Public API ────────────────────────────────────────────────────────────────

def parse_cst_obs(obs: dict, agent_id: str, view_size: int = 3) -> dict:
    """
    Parse a raw MiniGrid observation into the standard entity-snapshot dict.

    Parameters
    ----------
    obs : dict
        Raw observation from MultiAgentCooperativeSearchTransportEnv.
        Expected keys: "image" (ndarray shape (V,V,3)), "direction" (int),
        "mission" (str, ignored).
    agent_id : str
        Identifier of the observing agent (e.g. "agent_0").  Not embedded
        in the snapshot itself but may be used for logging.
    view_size : int
        Side length V of the partial observation grid (default 3).

    Returns
    -------
    dict
        Entity snapshot with step/action/reward set to None (filled in by
        BeliefStateManager.update).  Only observable fields are populated.

        {
            "step":   None,
            "action": None,
            "reward": None,
            "entities": {
                "self": {
                    "direction":    <int 0-3>,
                    "visible_cells": {
                        "front_center":  <label>,
                        "front_left":    <label>,
                        "front_right":   <label>,
                        "front2_center": <label>,   # only if view_size >= 4
                        "self_left":     <label>,
                        "self_right":    <label>,
                    }
                }
            }
        }

    Notes
    -----
    MiniGrid image axes: image[row][col] where row 0 = furthest ahead,
    row V-1 = the agent's own cell.  col V//2 = straight ahead (centre column).
    The agent occupies image[V-1][V//2].
    """
    image  = obs["image"]          # shape (V, V, 3)
    V      = view_size
    mid    = V // 2

    # Row indices (from agent's perspective)
    agent_row  = V - 1             # agent's own cell
    front1_row = V - 2             # 1 step ahead
    front2_row = V - 3             # 2 steps ahead (only valid if V >= 4)

    visible_cells: dict = {}

    if front1_row >= 0:
        visible_cells["front_center"] = _cell_desc(image[front1_row][mid])
        if mid - 1 >= 0:
            visible_cells["front_left"]  = _cell_desc(image[front1_row][mid - 1])
        if mid + 1 < V:
            visible_cells["front_right"] = _cell_desc(image[front1_row][mid + 1])

    if front2_row >= 0:
        visible_cells["front2_center"] = _cell_desc(image[front2_row][mid])

    # Cells to the agent's immediate left and right (same row as agent)
    if mid - 1 >= 0:
        visible_cells["self_left"]  = _cell_desc(image[agent_row][mid - 1])
    if mid + 1 < V:
        visible_cells["self_right"] = _cell_desc(image[agent_row][mid + 1])

    # Scan every cell for objects — record relative position so the updater
    # can convert to absolute world coordinates once it knows the agent's position.
    detected_objects = []
    for r in range(V):
        for c in range(V):
            if r == agent_row and c == mid:
                continue   # skip agent's own cell
            label = _cell_desc(image[r][c])
            if "TARGET_OBJECT" in label or "DECOY_OBJECT" in label:
                detected_objects.append({
                    "label":     label,
                    "rel_ahead": (V - 1) - r,   # >0 = ahead, 0 = same row
                    "rel_side":  c - mid,         # <0 = left, >0 = right
                })

    return {
        "step":   None,
        "action": None,
        "reward": None,
        "entities": {
            "self": {
                "direction":        int(obs["direction"]),
                "visible_cells":    visible_cells,
                "detected_objects": detected_objects,
                "image":            image,   # raw array — DeterministicGridUpdater uses this
            }
        },
    }
