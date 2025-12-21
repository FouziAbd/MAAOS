
class RewardManager:
    """
    this class is responsible for generating and updating the reward_function
    """

    # TODO: use LLM for this section

    def __init__(self,scenario_description):
        self.scenario_description = scenario_description
        self.reward_function = None

    def update_reward(self, user_input):
        """
        given a scenario description and a user input, modify the self.reward_function using an LLM to handle the natual language
        :param user_input:
        :return:
        """
        self.reward_function = lambda state: 2
        return self.reward_function


    def generate_reward_function(self, user_input):
        """
        given a scenario description and a user input, generate a reward function using an LLM and stores it on self.reward_function

        :param user_input:
        :return:
        """
        self.reward_function = lambda state:1
        return self.reward_function

    def get_reward_function(self):
        return self.reward_function
