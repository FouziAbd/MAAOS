from model_layer.maintenance.model_manager import ModelManager
from model_layer.maintenance.reward_manager import RewardManager
from model_layer.storage.belief_state_manager import BeliefStateManager
from model_layer.storage.history import History
from model_layer.planner.DsPy_planner import DSPyPlanner
from collections import deque
import dspy


class Agent:
    """
    this class is the main class for the agent, it has 3 main parts: model manager, belief manager, history manager,reward manager and a planner
    """

    def __init__(self, agent_id, scenario_description, goal_description, action_space: list[str], LLM_model: dspy.LM):
        self.LLM_model = LLM_model
        self.agent_id = agent_id
        self.scenario_description = scenario_description
        self.goal_description = goal_description
        self.action_space = action_space
        self.n_action = len(action_space)
        self.history = list()

        dspy.configure(lm=LLM_model)
        self.reward_manager = RewardManager(scenario_description=scenario_description, LLM_model=LLM_model,
                                            goal_description=goal_description)
        self.model_manager = ModelManager(model="", skills=action_space, goals=goal_description, constraints="")
        self.belief_manager = BeliefStateManager(starting_belief_state="")
        self.history_manager = History()
        self.planner = DSPyPlanner(self.agent_id)
        self.planner.configure_ollama(self.LLM_model)

    def choose_random_action(self):
        return self.model_manager.skills.sample()
    
    def choose_action(self, obs: str):
        belief = self.scenario_description
        action_str = '\n'.join(self.action_space)
        belief = belief + '\n' + action_str
        history_str = "last selected actions:"
        history_str = history_str + "\n".join(self.history) if self.history else "No history yet."
        belief = belief + '\n' + history_str + '\n' + f"agent_id = {self.agent_id}"
        action =  self.planner.selec_action_index(belief, obs, self.goal_description, self.n_action)
        action_summry = f"action {action}"
        self.history.append(action_summry)
        return action


if __name__ == '__main__':
    # We use the generic dspy.LM client pointing to your local Ollama instance.
    lm = dspy.LM(
        model='ollama_chat/qwen2.5-coder:1.5b',  # The model name matches your Ollama tag
        api_base='http://localhost:11434',  # Standard local Ollama port
        api_key=''  # No API key needed for local Ollama
    )
    agent = Agent(scenario_description="the state are the steps for opening a door", LLM_model=lm,action_space=[],
                  goal_description="the goal is to get past the door")
    agent.reward_manager.generate_reward_function()
    print(agent.reward_manager.get_reward_function()("you are close to the door, but the door is locked",
                                                     "breaking the door with a hammer to open a pass to go through"))
