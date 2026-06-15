"""
ParticleFilterUpdater — stub BaseBeliefUpdater for continuous-space envs.

Currently used for KAZ where positions are noisy normalised floats.
The "filter" is trivial: we simply track the last-observed values and
compute derived tactical fields (attack_ok, turn_hint, blocks_attack).
A true particle filter can replace the internals without changing the API.
"""
import sys
import os
import math
from copy import deepcopy
from typing import Any, Dict, Optional

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
for _p in (_THIS_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_layer.storage.base_belief_updater import BaseBeliefUpdater

# ── Tactical thresholds (mirrored from KAZ.py) ───────────────────────────────
_ARCHER_MAX_DIST   = 0.85
_ARCHER_MAX_ANGLE  = 20.0
_KNIGHT_MAX_DIST   = 0.60
_KNIGHT_MAX_ANGLE  = 100.0
_ALLY_BLOCK_DIST_A = 0.20
_ALLY_BLOCK_ANG_A  = 15.0
_ALLY_BLOCK_DIST_K = 0.15
_ALLY_BLOCK_ANG_K  = 25.0


def _angle_and_dot(u, v):
    import numpy as np
    u = [float(x) for x in u]
    v = [float(x) for x in v]
    nu = math.sqrt(u[0]**2 + u[1]**2) + 1e-9
    nv = math.sqrt(v[0]**2 + v[1]**2) + 1e-9
    u = [u[0]/nu, u[1]/nv]
    v = [v[0]/nv, v[1]/nv]
    dot  = max(-1.0, min(1.0, u[0]*v[0] + u[1]*v[1]))
    angle = math.degrees(math.acos(dot))
    return angle, dot


class ParticleFilterUpdater(BaseBeliefUpdater):
    """
    Lightweight belief tracker for KAZ (continuous-space, vector obs).

    Stores last-seen entity data directly.  Derived tactical booleans
    (attack_ok, turn_hint, ally.blocks_attack, zombie.is_nearest) are
    computed after each update.

    Parameters
    ----------
    initial_entities : dict
        Prior-knowledge entity states.  Typically just {"self": {}}.
    agent_role : str
        "archer" or "knight" — controls distance/angle thresholds.
    """

    estimator_type: str = "particle_filter"

    def __init__(
        self,
        initial_entities: Dict[str, Dict[str, Any]],
        agent_role: str = "archer",
    ):
        self._initial  = deepcopy(initial_entities)
        self._entities: Dict[str, Dict[str, Any]] = deepcopy(initial_entities)
        self._role     = agent_role.lower()

    # ── BaseBeliefUpdater interface ───────────────────────────────────────────

    def update_entity(self, entity_snapshot: dict) -> None:
        obs_ents = entity_snapshot.get("entities", {})

        # 1. Merge observable fields from each entity
        for eid, edata in obs_ents.items():
            if eid not in self._entities:
                self._entities[eid] = {}
            self._entities[eid].update(edata)

        # 2. Remove entities that were present before but absent now
        #    (they are out of range / dead) — only for zombie_* / ally_*
        current_ids  = set(obs_ents.keys())
        to_remove = [
            eid for eid in self._entities
            if eid != "self"
            and (eid.startswith("zombie_") or eid.startswith("ally_"))
            and eid not in current_ids
        ]
        for eid in to_remove:
            del self._entities[eid]

        # 3. Recompute derived tactical fields
        self._compute_tactical()

    def get_entity_state(self, entity_id: str) -> dict:
        return deepcopy(self._entities.get(entity_id, {}))

    def get_all_entities(self) -> dict:
        return deepcopy(self._entities)

    def get_uncertainty(self, entity_id: str) -> float:
        # All data is directly observed → 1.0 if present, else 0.0
        return 1.0 if entity_id in self._entities else 0.0

    def reset(self) -> None:
        self._entities = deepcopy(self._initial)

    # ── tactical computation ──────────────────────────────────────────────────

    def _compute_tactical(self) -> None:
        self_state = self._entities.get("self", {})
        heading    = self_state.get("heading", [1.0, 0.0])

        if self._role == "archer":
            max_dist  = _ARCHER_MAX_DIST
            max_angle = _ARCHER_MAX_ANGLE
            ab_dist   = _ALLY_BLOCK_DIST_A
            ab_angle  = _ALLY_BLOCK_ANG_A
        else:
            max_dist  = _KNIGHT_MAX_DIST
            max_angle = _KNIGHT_MAX_ANGLE
            ab_dist   = _ALLY_BLOCK_DIST_K
            ab_angle  = _ALLY_BLOCK_ANG_K

        # nearest zombie
        nearest_z  = None
        nearest_zd = float("inf")
        for eid, edata in self._entities.items():
            if not eid.startswith("zombie_"):
                continue
            d = edata.get("distance", 0.0)
            if d > 0 and d < nearest_zd:
                nearest_zd = d
                nearest_z  = eid
            edata["is_nearest"] = False
        if nearest_z:
            self._entities[nearest_z]["is_nearest"] = True

        # ally blocking
        ally_block = False
        for eid, edata in self._entities.items():
            if not eid.startswith("ally_"):
                continue
            ad       = edata.get("distance", 0.0)
            rel      = edata.get("rel_pos", [0.0, 0.0])
            angle, dot = _angle_and_dot(heading, rel)
            blocks   = (ad <= ab_dist) and (dot > 0) and (angle <= ab_angle)
            edata["blocks_attack"] = blocks
            if blocks:
                ally_block = True

        # attack_ok + turn_hint
        if nearest_z is not None:
            zdata    = self._entities[nearest_z]
            zd       = zdata.get("distance", 0.0)
            rel      = zdata.get("rel_pos", [0.0, 0.0])
            angle, dot = _angle_and_dot(heading, rel)
            in_front = (dot > 0) and (angle <= max_angle)
            attack_ok = bool(in_front and (zd <= max_dist) and not ally_block)

            # turn hint: cross product z-component
            h  = heading
            cross = h[0] * rel[1] - h[1] * rel[0]
            turn  = "LEFT" if cross > 0 else "RIGHT"
        else:
            attack_ok = False
            turn      = "NONE"

        self_state["attack_ok"]  = attack_ok
        self_state["turn_hint"]  = turn
