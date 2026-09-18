class ActionExecutor:
    """
    Executes planner-chosen action indices in the functional environment.
    Maps action indices directly to environment.step() calls.
    """

    def __init__(self, env, agent_id: str):
        """
        Args:
            env: PettingZoo environment instance
            agent_id: Unique identifier for this agent in the environment
        """
        self.env = env
        self.agent_id = agent_id

    def execute_action(self, action_index: int) -> dict:
        """
        Execute a planner-chosen action in the environment.
        Pass-through to env.step() using the action index directly.

        Args:
            action_index: Integer action index chosen by planner (must be in valid range for env)

        Returns:
            Result dictionary with keys:
                - 'action': the executed action index
                - 'valid': whether action was valid for this environment
        """
        if not isinstance(action_index, int):
            raise TypeError(f"Action must be integer, got {type(action_index)}")

        if action_index < 0:
            raise ValueError(f"Action index cannot be negative: {action_index}")

        # Validate action against environment's action space
        # Most PettingZoo envs have discrete action spaces
        try:
            action_space = self.env.action_spaces[self.agent_id]
            if hasattr(action_space, 'n'):  # Discrete space
                if action_index >= action_space.n:
                    raise ValueError(
                        f"Action index {action_index} out of range [0, {action_space.n - 1}]"
                    )
        except (AttributeError, KeyError):
            # Could not validate; assume action is valid and let env handle it
            pass

        return {
            "action": action_index,
            "valid": True,
            "agent_id": self.agent_id
        }

    def get_valid_action_range(self) -> tuple:
        """
        Get the valid action range for this environment.

        Returns:
            Tuple of (min_action, max_action)
        """
        try:
            action_space = self.env.action_spaces[self.agent_id]
            if hasattr(action_space, 'n'):  # Discrete space
                return 0, action_space.n - 1
        except (AttributeError, KeyError):
            pass
        return None, None

    def clamp_action(self, action_index: int) -> int:
        """
        Clamp action index to valid range.

        Args:
            action_index: Proposed action index

        Returns:
            Clamped action index within valid range
        """
        min_act, max_act = self.get_valid_action_range()

        if min_act is None or max_act is None:
            return action_index

        if action_index < min_act:
            return min_act
        if action_index > max_act:
            return max_act

        return action_index
