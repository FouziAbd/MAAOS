from enum import IntEnum


class Actions(IntEnum):
    TURN_LEFT = 0
    TURN_RIGHT = 1
    MOVE_FORWARD = 2
    STAY = 3
    PICK_OR_INTERACT = 4
    DROP = 5
    COOPERATE = 6


class Directions(IntEnum):
    # MiniGrid-style ordering
    RIGHT = 0
    DOWN = 1
    LEFT = 2
    UP = 3


class CellType(IntEnum):
    EMPTY = 0
    WALL = 1
    DELIVERY = 2
    AGENT = 3
    TARGET_OBJECT = 4
    NON_TARGET_OBJECT = 5

# Direction vectors that match Directions
DIRECTION_VECTORS = {
    Directions.RIGHT: (1, 0),
    Directions.DOWN: (0, 1),
    Directions.LEFT: (-1, 0),
    Directions.UP: (0, -1)
}

ACTION_NAMES = {
    Actions.TURN_LEFT: "TURN_LEFT",
    Actions.TURN_RIGHT: "TURN_RIGHT",
    Actions.MOVE_FORWARD: "MOVE_FORWARD",
    Actions.STAY: "STAY",
    Actions.PICK_OR_INTERACT: "PICK_OR_INTERACT",
    Actions.DROP: "DROP",
    Actions.COOPERATE: "COOPERATE",
}


DIRECTION_NAMES = {
    Directions.RIGHT: "RIGHT",
    Directions.DOWN: "DOWN",
    Directions.LEFT: "LEFT",
    Directions.UP: "UP",
}