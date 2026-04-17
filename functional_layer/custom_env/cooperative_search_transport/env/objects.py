from minigrid.core.world_object import Box, Floor
from minigrid.core.world_object import WorldObj
from minigrid.core.constants import COLORS
from minigrid.utils.rendering import fill_coords, point_in_triangle, rotate_fn
import math


class TargetPackage(Box):
    """Red box = target object."""
    def __init__(self):
        super().__init__(color="red")


class DecoyPackage(Box):
    """Blue box = non-target object."""
    def __init__(self):
        super().__init__(color="blue")


class DeliveryTile(Floor):
    """Green floor tile for the delivery zone."""
    def __init__(self):
        super().__init__(color="green")


class AgentMarker(WorldObj):
    def __init__(self, color="purple", dir=0):
        super().__init__("agent", color)
        self.dir = dir

    def can_overlap(self):
        return True

    def render(self, img):
        tri_fn = point_in_triangle(
            (0.12, 0.19),
            (0.87, 0.50),
            (0.12, 0.81),
        )
        tri_fn = rotate_fn(tri_fn, cx=0.5, cy=0.5, theta=0.5 * math.pi * self.dir)
        fill_coords(
            img,
            tri_fn,
            COLORS[self.color],
        )