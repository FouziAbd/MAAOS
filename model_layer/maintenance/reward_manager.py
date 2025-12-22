import dspy

class RewardManager:
    """
    this class is responsible for generating and updating the reward_function
    """

    # TODO: use LLM for this section

    def __init__(self,scenario_description,goal_description, LLM_model: dspy.LM):
        self.scenario_description = scenario_description
        self.goal_description = goal_description
        self.LLM_model = LLM_model
        self.reward_function = self.generate_reward_function()

    def update_reward(self, user_input):
        """
        given a scenario description and a user input, modify the self.reward_function using an LLM to handle the natual language
        :param user_input:
        :return:
        """
        self.reward_function = lambda state: 2
        return self.reward_function

    def generate_reward_function(self):
        """
        Configures self.reward_function to be a callable that uses the LLM directly
        to calculate (judge) the reward for a given state and action.
        """

        # 1. Define the Signature for 'Judging' a step
        class RewardJudge(dspy.Signature):
            """
            Analyze the state and action based on the scenario and user requirements.
            Assign a numeric reward score (float) indicating how beneficial the action was.
            """
            scenario_context = dspy.InputField(desc=self.scenario_description)
            user_goals = dspy.InputField(desc="the goal is to get a state as large as possible")
            current_state = dspy.InputField()
            action_taken = dspy.InputField()

            # We ask for reasoning first (ChainOfThought) to improve the score's accuracy
            reasoning = dspy.OutputField(desc="Why this score was given")
            reward_score = dspy.OutputField(desc="A single float value (e.g. -1.0, 0.0, 1.0)", prefix="Score:")

        # 2. Instantiate the DSPy program
        # We create it here so we can capture it in the closure below
        judge_program = dspy.ChainOfThought(RewardJudge)

        # 3. Define the wrapper function (Closure)
        # This will become 'self.reward_function(state, action)'
        def llm_reward_wrapper(state, action):
            with dspy.context(lm=self.LLM_model):
                try:
                    # Run the LLM inference
                    pred = judge_program(
                        scenario_context=self.scenario_description,
                        user_goals=self.goal_description,
                        current_state=str(state),
                        action_taken=str(action)
                    )

                    # Parse the output to ensure it is a float
                    # Local models sometimes leave extra text, so we try-catch
                    print(pred)
                    return float(pred.reward_score.strip())
                except ValueError:
                    # Fallback: if model fails to output a number, return 0.0 or print error
                    print(f"Error parsing reward: {pred.reward_score}")
                    return 0.0

        return llm_reward_wrapper

    def get_reward_function(self):
        return self.reward_function
