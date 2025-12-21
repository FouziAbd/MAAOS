from model_layer.maintenance.model_manager import ModelManager
from model_layer.maintenance.reward_manager import RewardManager
from model_layer.storage.belief_state_manager import BeliefStateManager
from model_layer.storage.history import History


class Agent:
    """
    this class is the main class for the agent, it has 3 main parts: model manager, belief manager, history manager,reward manager and a planner
    """

    def __init__(self, reward_manager: RewardManager, model_manager: ModelManager, belief_manager: BeliefStateManager,
                 history_manager: History, planner):
        self.reward_manager = reward_manager
        self.model_manager = model_manager
        self.belief_manager = belief_manager  # not sure if we want it inside  the model manager
        self.history_manager = history_manager
        self.planner = planner  # still no class for it
