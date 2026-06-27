"""
Box-Push EntitySchema — same grid-belief contract as CST, retargeted for pushing.

Belief is a 12×12 grid of cell labels:
    unknown | empty | wall | delivery_zone | target_N | agent
Object status values for box-push: available | at_goal
"""
import sys
import os

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../.."))
for _p in (_THIS_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_layer.storage.entity_schema import EntitySchema, EntitySpec, FieldSpec

BOX_PUSH_ACTION_NAMES = {
    0: "TURN_LEFT",
    1: "TURN_RIGHT",
    2: "MOVE_FORWARD",
    3: "STAY",
    4: "PICK_OR_INTERACT",   # unused in box-push
    5: "DROP",               # unused in box-push
    6: "COOPERATE",          # unused in box-push
}

_SELF_SPEC = EntitySpec(
    entity_id_pattern="self",
    is_self=True,
    fields=[
        FieldSpec("direction", "int", observable=True,
                  description="Facing: 0=RIGHT 1=DOWN 2=LEFT 3=UP"),
        FieldSpec("position", "list[int]", observable=False,
                  description="[x,y] dead-reckoned via action+reward"),
        FieldSpec("carrying_object_id", "int", observable=False,
                  description="Unused in box-push (no carrying); kept for updater compatibility"),
        FieldSpec("engaged_object_ids", "list[int]", observable=False,
                  description="Unused in box-push; kept for updater compatibility"),
        FieldSpec("delivered_object_ids", "list[int]", observable=False,
                  description="Target boxes this agent has pushed onto the goal"),
    ],
)

_OBJECT_SPEC = EntitySpec(
    entity_id_pattern="object_*",
    fields=[
        FieldSpec("is_target", "bool", observable=False,
                  description="True for TARGET boxes (push to goal); all boxes are targets"),
        FieldSpec("required_agents", "int", observable=False,
                  description="1 = light (one pusher), 2 = heavy (needs both agents)"),
        FieldSpec("status", "str", observable=False,
                  description="available | at_goal"),
    ],
)

_GRID_SPEC = EntitySpec(
    entity_id_pattern="grid",
    fields=[
        FieldSpec("cells", "list[list[str]]", observable=True,
                  description=("12×12 belief grid indexed grid[x][y]. Labels: unknown | "
                               "empty | wall | delivery_zone | target_N | agent")),
    ],
)

BOX_PUSH_ENTITY_SCHEMA = EntitySchema(
    environment_name="BoxPush",
    estimator_type="deterministic_grid",
    entity_specs=[_SELF_SPEC, _OBJECT_SPEC, _GRID_SPEC],
    action_names=BOX_PUSH_ACTION_NAMES,
)

BOX_PUSH_ENTITY_SCHEMA.validate()
