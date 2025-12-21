class BeliefStateManager:
    """
        this class is the belief state of the agent
    """
    # TODO: not sure if Ronen want it to be Natural language for the beginning
    def __init__(self, starting_belief_state):
        self.current_belief_state = starting_belief_state
        self.other_agent_belief_state = None

    def update_belief_state(self, action,observation):
        """
        this method is responsible for updating the belief state of the model
        :param action:
        :param observation:
        :return:
        """
        # TODO: use particle filter for this section
        return self.current_belief_state

