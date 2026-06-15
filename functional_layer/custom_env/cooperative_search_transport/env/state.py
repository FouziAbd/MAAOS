from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict

from constants import Directions


Position = Tuple[int, int]

@dataclass
class EnvCoreConfig:
    width: int = 12
    height: int = 12
    agent_start_pos: Optional[Position] = (10, 10)
    agent_start_dir: int = Directions.LEFT
    num_objects: int = 4
    num_target_objects: int = 2
    max_steps: int = 100
    agent_view_size: int = 3
    delivery_zone_size: int = 2
    render_mode: Optional[str] = "text"
    seed: Optional[int] = None

    def validate(self) -> None:
        if self.width < 6:
            raise ValueError("width must be >= 6")
        if self.height < 6:
            raise ValueError("height must be >= 6")
        if self.num_objects < 1:
            raise ValueError("num_objects must be >= 1")
        if not (0 <= self.num_target_objects <= self.num_objects):
            raise ValueError("num_target_objects must be between 0 and num_objects")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be > 0")
        if self.agent_view_size <= 0 or self.agent_view_size % 2 == 0:
            raise ValueError("agent_view_size must be a positive odd number")
        if self.delivery_zone_size < 1:
            raise ValueError("delivery_zone_size must be >= 1")
        if self.render_mode not in (None, "human", "rgb_array", "text"):
            raise ValueError("render_mode must be one of: None, 'human', 'rgb_array', 'text'")

@dataclass
class EnvConfig(EnvCoreConfig):
    num_agents: int = 2

    def validate(self) -> None:
        super().validate()
        if self.num_agents < 2:
            raise ValueError("num_agents must be >= 2")
@dataclass
class AgentState:
    agent_id: str
    position: Position
    direction: int = Directions.RIGHT
    carrying_object_id: Optional[int] = None
    active: bool = True

    # for later extensions
    cooperating: bool = False
    last_action: Optional[int] = None

@dataclass
class ObjectState:
    object_id: int
    position: Position
    is_target: bool
    required_agents: int = 1
    delivered: bool = False

    # v1: single carrier or None
    carried_by: Optional[str] = None

    # later for multi-agent transport
    engaged_agents: List[str] = field(default_factory=list)

@dataclass
class EpisodeState:
    step_count: int = 0
    delivered_target_count: int = 0
    terminated: bool = False
    truncated: bool = False


@dataclass
class StaticWorld:
    walls: List[Position] = field(default_factory=list)
    delivery_zone: List[Position] = field(default_factory=list)


@dataclass
class WorldState:
    agents: Dict[str, AgentState] = field(default_factory=dict)
    objects: Dict[int, ObjectState] = field(default_factory=dict)
    static: StaticWorld = field(default_factory=StaticWorld)
    episode: EpisodeState = field(default_factory=EpisodeState)