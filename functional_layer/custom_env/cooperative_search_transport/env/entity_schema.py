"""
CST EntitySchema — declares every entity, its fields, and the estimator type.

Belief state is a 12×12 grid where each cell stores a label:
    unknown       — never observed
    empty         — observed as floor/empty
    wall          — observed as wall
    delivery_zone — known from prior knowledge
    target_N      — target object N is at this cell
    decoy_N       — decoy object N is at this cell
    agent         — another agent observed here

The grid is initialized from prior knowledge and updated each step as the
agent's 3×3 partial view sweeps new cells.
"""
import sys
import os

_ENV_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_ENV_DIR, "../../../.."))
for _p in (_ENV_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_layer.storage.entity_schema import EntitySchema, EntitySpec, FieldSpec

# ── Action map ────────────────────────────────────────────────────────────────
CST_ACTION_NAMES = {
    0: "TURN_LEFT",
    1: "TURN_RIGHT",
    2: "MOVE_FORWARD",
    3: "STAY",
    4: "PICK_OR_INTERACT",
    5: "DROP",
    6: "COOPERATE",
}

# ── Entity specs ──────────────────────────────────────────────────────────────

_SELF_SPEC = EntitySpec(
    entity_id_pattern="self",
    is_self=True,
    fields=[
        # Observable: from obs["direction"]
        FieldSpec("direction",            "int",       observable=True,
                  description="Facing: 0=RIGHT 1=DOWN 2=LEFT 3=UP"),
        # Internal: dead-reckoned from MOVE_FORWARD + reward
        FieldSpec("position",             "list[int]", observable=False,
                  description="[x,y] dead-reckoned via action+reward"),
        FieldSpec("carrying_object_id",   "int",       observable=False,
                  description="Object id currently carried solo, or None"),
        FieldSpec("engaged_object_ids",   "list[int]", observable=False,
                  description="Cooperative objects this agent has latched onto"),
        FieldSpec("delivered_object_ids", "list[int]", observable=False,
                  description="Objects this agent has successfully delivered"),
    ],
)

# One spec covers all numbered objects via wildcard.
# Position is stored in the grid, NOT here.
_OBJECT_SPEC = EntitySpec(
    entity_id_pattern="object_*",
    fields=[
        FieldSpec("is_target",       "bool", observable=False,
                  description="True for TARGET objects, False for DECOYs"),
        FieldSpec("required_agents", "int",  observable=False,
                  description="How many agents are needed to carry this object"),
        FieldSpec("status",          "str",  observable=False,
                  description="available | carried_by_self | engaged_by_self | delivered"),
    ],
)

# The 12×12 belief grid — the main spatial belief state.
_GRID_SPEC = EntitySpec(
    entity_id_pattern="grid",
    fields=[
        FieldSpec(
            "cells", "list[list[str]]", observable=True,
            description=(
                "12×12 belief grid indexed grid[x][y]. "
                "Labels: unknown | empty | wall | delivery_zone | "
                "target_N | decoy_N | agent"
            ),
        ),
    ],
)

# ── Module-level schema instance ──────────────────────────────────────────────

CST_ENTITY_SCHEMA = EntitySchema(
    environment_name="CooperativeSearchTransport",
    estimator_type="deterministic_grid",
    entity_specs=[_SELF_SPEC, _OBJECT_SPEC, _GRID_SPEC],
    action_names=CST_ACTION_NAMES,
)

CST_ENTITY_SCHEMA.validate()
