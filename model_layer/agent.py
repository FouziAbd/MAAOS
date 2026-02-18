from model_layer.maintenance.model_manager import ModelManager
from model_layer.maintenance.reward_manager import RewardManager
from model_layer.storage.belief_state_manager import BeliefStateManager
from model_layer.storage.history import History
from model_layer.planner.DsPy_planner import DSPyPlanner
from collections import deque
import dspy
import numpy as np


class Agent:
    """
    This class is the main class for the agent, it has 3 main parts: model manager, belief manager, history manager,reward manager and a planner.
    Optionally integrates with MiddlewareOrchestrator to simplify observations, scenarios, and actions via LLM.
    """

    def __init__(
        self,
        agent_id,
        scenario_description,
        goal_description,
        action_space: list[str],
        LLM_model: dspy.LM,
        middleware=None
    ):
        self.LLM_model = LLM_model
        self.agent_id = agent_id
        self.scenario_description = scenario_description
        self.goal_description = goal_description
        self.action_space = action_space
        self.n_action = len(action_space)
        self.history = list()
        self.middleware = middleware

        dspy.configure(lm=LLM_model)
        self.reward_manager = RewardManager(
            scenario_description=scenario_description,
            LLM_model=LLM_model,
            goal_description=goal_description
        )
        self.model_manager = ModelManager(
            model="",
            skills=action_space,
            goals=goal_description,
            constraints=""
        )
        self.belief_manager = BeliefStateManager(starting_belief_state="")
        self.history_manager = History()
        self.planner = DSPyPlanner(self.agent_id)
        self.planner.configure_ollama(self.LLM_model)
        self.rng = np.random.default_rng()

    def choose_random_action(self):
        #return self.model_manager.skills.sample()
        return self.rng.integers(0, self.n_action)
    
    def choose_action(self, obs):
        """
        Choose an action based on observation using the planner.
        
        If middleware is available, uses simplified observation, scenario, goal, and actions.
        Otherwise, uses raw inputs (legacy behavior).
        
        Args:
            obs: Raw observation from environment (can be array, dict, or string)
        
        Returns:
            Action index (integer in [0, n_actions-1])
        """
        return self.choose_action_with_tactical_info(obs, tactical_summary="")
    
    def choose_action_with_tactical_info(self, obs, tactical_summary: str = ""):
        """
        Choose an action based on observation + optional tactical summary.
        
        If middleware is available, uses simplified observation, scenario, goal, and actions.
        Otherwise, uses raw inputs (legacy behavior).
        
        Args:
            obs: Raw observation from environment (can be array, dict, or string)
            tactical_summary: Optional pre-computed tactical assessment (e.g., from summarize_kaz_obs)
        
        Returns:
            Action index (integer in [0, n_actions-1])
        """
        # Use middleware if available, otherwise fall back to raw inputs
        if self.middleware is not None:
            # Simplify observation via middleware (with optional tactical info)
            obs_summary = self.middleware.process_observation(obs, tactical_summary=tactical_summary)
            
            # Get simplified scenario, goal, and actions from middleware
            scenario = self.middleware.get_simplified_scenario()
            goal = self.middleware.get_simplified_goal()
            # Use raw action space (not enriched) to preserve action-index mapping
            action_descriptions = "Actions:\n" + "\n".join(self.action_space)
        else:
            # Legacy behavior: use raw inputs without simplification
            obs_summary = str(obs) if not isinstance(obs, str) else obs
            scenario = self.scenario_description
            goal = self.goal_description
            action_descriptions = "Actions:\n" + "\n".join(self.action_space)

        # Format history
        history_str = "\n".join(self.history) if self.history else "none"

        action = self.planner.selec_action_index(
            instructions=scenario,
            obs_summary=obs_summary,
            action_descriptions=action_descriptions,
            objective=goal,
            recent_actions=history_str,
            n_actions=self.n_action,
        )

        self.history.append(f"action {action}")
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
