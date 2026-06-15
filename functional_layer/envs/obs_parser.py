"""
KAZ observation parser — converts a raw KAZ vector observation into the
standard entity-snapshot format consumed by BeliefStateManager.

KAZ uses vector_state=True, so each observation is a (N+1) x 5 numpy array.
Row layout:
  [0]       current agent: [0, pos_x, pos_y, heading_x, heading_y]
  [1..A]    archers:        [dist, rel_x, rel_y, dir_x, dir_y]
  [A+1..K]  knights:        [dist, rel_x, rel_y, dir_x, dir_y]
  [K+1..S]  swords:         [dist, rel_x, rel_y, dir_x, dir_y]  (S == num_knights)
  [S+1..AR] arrows:         [dist, rel_x, rel_y, dir_x, dir_y]
  [AR+1..Z] zombies:        [dist, rel_x, rel_y, dir_x, dir_y]

All distances / positions are normalised to [0, 1].  Inactive slots are all-zero.

Only observable fields are populated here.  Internal fields (attack_ok,
turn_hint, blocks_attack, is_nearest) are computed by ParticleFilterUpdater.

Usage
-----
    from obs_parser import parse_kaz_obs
    snapshot = parse_kaz_obs(obs, agent_id="archer_0",
                             num_archers=2, num_knights=2,
                             max_arrows=10, max_zombies=10)
    belief_manager.update(action, reward, snapshot)
"""
import sys
import os
import numpy as np

_ENV_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_ENV_DIR, "../.."))
for _p in (_ENV_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def parse_kaz_obs(
    obs,
    agent_id: str,
    num_archers: int,
    num_knights: int,
    max_arrows: int,
    max_zombies: int,
) -> dict:
    """
    Parse a raw KAZ vector observation into the standard entity-snapshot dict.

    Parameters
    ----------
    obs : array-like, shape (N+1, 5)
        Raw observation from knights_archers_zombies with vector_state=True.
    agent_id : str
        Identifier of the observing agent (e.g. "archer_0", "knight_1").
    num_archers, num_knights, max_arrows, max_zombies : int
        Environment configuration values — used to compute row offsets.

    Returns
    -------
    dict
        Entity snapshot with step/action/reward set to None.
        Entities populated:
          "self"      — position and heading
          "zombie_0".."zombie_K" — active zombies (dist > 0)
          "ally_0".."ally_M"    — active allies (dist > 0)
    """
    obs = np.asarray(obs, dtype=float)

    # ── self ──────────────────────────────────────────────────────────────────
    pos_x, pos_y = float(obs[0, 1]), float(obs[0, 2])
    hx,    hy    = float(obs[0, 3]), float(obs[0, 4])

    entities: dict = {
        "self": {
            "position": [pos_x, pos_y],
            "heading":  [hx, hy],
        }
    }

    # ── allies (archers + knights rows) ───────────────────────────────────────
    ally_start = 1
    ally_end   = 1 + num_archers + num_knights
    ally_idx   = 0
    for r in range(ally_start, ally_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        entities[f"ally_{ally_idx}"] = {
            "distance": dist,
            "rel_pos":  [float(obs[r, 1]), float(obs[r, 2])],
            "heading":  [float(obs[r, 3]), float(obs[r, 4])],
        }
        ally_idx += 1

    # ── zombies ───────────────────────────────────────────────────────────────
    zombie_start = 1 + num_archers + num_knights + num_knights + max_arrows
    zombie_end   = zombie_start + max_zombies
    zombie_idx   = 0
    for r in range(zombie_start, zombie_end):
        dist = float(obs[r, 0])
        if dist <= 0:
            continue
        entities[f"zombie_{zombie_idx}"] = {
            "distance": dist,
            "rel_pos":  [float(obs[r, 1]), float(obs[r, 2])],
            "heading":  [float(obs[r, 3]), float(obs[r, 4])],
        }
        zombie_idx += 1

    return {
        "step":     None,
        "action":   None,
        "reward":   None,
        "entities": entities,
    }
