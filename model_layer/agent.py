from model_layer.maintenance.model_manager import ModelManager
from model_layer.maintenance.reward_manager import RewardManager
from model_layer.storage.belief_state_manager import BeliefStateManager
from model_layer.storage.history import History
import dspy


class Agent:
    """
    this class is the main class for the agent, it has 3 main parts: model manager, belief manager, history manager,reward manager and a planner
    """

    def __init__(self, scenario_description, goal_description, LLM_model: dspy.LM):
        self.LLM_model = LLM_model
        dspy.configure(lm=lm)
        self.reward_manager = RewardManager(scenario_description=scenario_description, LLM_model=LLM_model,
                                            goal_description=goal_description)
        self.model_manager = ModelManager(model="", skills=[], goals=goal_description, constraints="")
        self.belief_manager = BeliefStateManager(starting_belief_state="")
        self.history_manager = History()
        self.planner = None  # still no class for it


if __name__ == '__main__':
    # We use the generic dspy.LM client pointing to your local Ollama instance.
    lm = dspy.LM(
        model='ollama_chat/qwen2.5-coder:1.5b',  # The model name matches your Ollama tag
        api_base='http://localhost:11434',  # Standard local Ollama port
        api_key=''  # No API key needed for local Ollama
    )
    agent = Agent(scenario_description="the state are the steps for opening a door", LLM_model=lm, goal_description="the goal is to get past the door")
    agent.reward_manager.generate_reward_function()
    print(agent.reward_manager.get_reward_function()("you are close to the door, but the door is locked","breaking the door with a hammer to open a pass to go through"))
