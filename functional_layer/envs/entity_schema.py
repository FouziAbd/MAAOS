"""
KAZ EntitySchema — declares every entity, its fields, and the estimator type.
Imported by the middleware to wire up the belief system.

KAZ uses a particle-filter estimator because agent positions are noisy
and there is no ground-truth observation of the full world state.
"""
import sys
import os

_ENV_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_ENV_DIR, "../.."))
for _p in (_ENV_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_layer.storage.entity_schema import EntitySchema, EntitySpec, FieldSpec

# ── Action map ────────────────────────────────────────────────────────────────
KAZ_ACTION_NAMES = {
    0: "MOVE_FORWARD",
    1: "MOVE_BACKWARD",
    2: "ROTATE_LEFT",
    3: "ROTATE_RIGHT",
    4: "ATTACK",
    5: "NOOP",
}

# ── Entity specs ──────────────────────────────────────────────────────────────

_SELF_SPEC = EntitySpec(
    entity_id_pattern="self",
    is_self=True,
    fields=[
        # Observable: comes directly from obs row 0
        FieldSpec("position",     "list[float]", observable=True,
                  description="Normalised [x, y] absolute position (0-1 range)"),
        FieldSpec("heading",      "list[float]", observable=True,
                  description="Unit-vector heading [hx, hy] in world coordinates"),
        # Internal: derived in tactical summary
        FieldSpec("attack_ok",    "bool",         observable=False,
                  description="True when a zombie is in front, close, and no ally blocking"),
        FieldSpec("turn_hint",    "str",           observable=False,
                  description="LEFT or RIGHT — which way to rotate to face nearest zombie"),
    ],
)

_ZOMBIE_SPEC = EntitySpec(
    entity_id_pattern="zombie_*",
    fields=[
        # Observable: raw rows from obs array
        FieldSpec("distance",  "float",       observable=True,
                  description="Normalised distance to this agent (0-1)"),
        FieldSpec("rel_pos",   "list[float]", observable=True,
                  description="Relative [x, y] position to self"),
        FieldSpec("heading",   "list[float]", observable=True,
                  description="Unit-vector heading [dx, dy]"),
        # Internal: flag set during tactical processing
        FieldSpec("is_nearest", "bool",        observable=False,
                  description="True for the zombie closest to this agent"),
    ],
)

_ALLY_SPEC = EntitySpec(
    entity_id_pattern="ally_*",
    fields=[
        FieldSpec("distance",           "float",       observable=True,
                  description="Normalised distance to this agent"),
        FieldSpec("rel_pos",            "list[float]", observable=True,
                  description="Relative [x, y] position to self"),
        FieldSpec("heading",            "list[float]", observable=True,
                  description="Unit-vector heading [dx, dy]"),
        FieldSpec("blocks_attack",      "bool",        observable=False,
                  description="True when this ally is between self and the nearest zombie"),
    ],
)

# ── Module-level schema instance ──────────────────────────────────────────────

KAZ_ENTITY_SCHEMA = EntitySchema(
    environment_name="KnightsArchersZombies",
    estimator_type="particle_filter",
    entity_specs=[_SELF_SPEC, _ZOMBIE_SPEC, _ALLY_SPEC],
    action_names=KAZ_ACTION_NAMES,
)

# Validate at import time so misconfiguration is caught early
KAZ_ENTITY_SCHEMA.validate()
