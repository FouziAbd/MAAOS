import dspy


class ScenarioSimplifier:
    """
    LLM-based scenario and goal simplifier.
    Condenses verbose scenario descriptions and goal statements into concise, actionable text.
    Results are cached after first simplification.
    """

    def __init__(self, LLM_model: dspy.LM):
        """
        Args:
            LLM_model: DSPy language model instance (e.g., dspy.LM for Ollama)
        """
        self.LLM_model = LLM_model
        self.simplified_scenario = None
        self.simplified_goal = None
        self._simplify_sig = None

    def _configure_signature(self):
        """Define and instantiate the DSPy signature for scenario simplification."""
        if self._simplify_sig is not None:
            return

        class ScenarioSimplificationSignature(dspy.Signature):
            """
            Simplify and condense scenario and goal descriptions into essential, actionable points.
            Remove redundancy, jargon, and verbose explanations while preserving key information.
            Focus on: what the agent controls, what the environment contains, key rules, and the objective.
            """
            scenario_description: str = dspy.InputField(
                desc="Verbose scenario description (may include observation specs, rules, context)"
            )
            goal_description: str = dspy.InputField(
                desc="Goal or objective statement for the agent"
            )
            environment_type: str = dspy.InputField(
                desc="Type of environment (e.g., 'KAZ zombie game', 'Toy Rescue task')"
            )

            simplified_scenario: str = dspy.OutputField(
                desc="Concise scenario summary (< 150 words). Include: agent control, key environment features, hardcoded rules."
            )
            simplified_goal: str = dspy.OutputField(
                desc="Concise goal statement (< 50 words). What does the agent need to achieve?"
            )

        with dspy.context(lm=self.LLM_model):
            self._simplify_sig = dspy.ChainOfThought(ScenarioSimplificationSignature)

    def simplify_scenario_and_goal(
        self,
        scenario_description: str,
        goal_description: str,
        environment_type: str = "generic"
    ) -> tuple:
        """
        Simplify both scenario and goal descriptions.
        Called once at agent initialization.

        Args:
            scenario_description: Verbose scenario description
            goal_description: Goal statement
            environment_type: Type of environment

        Returns:
            Tuple of (simplified_scenario, simplified_goal)
        """
        self._configure_signature()

        # Return cached if already simplified
        if self.simplified_scenario is not None and self.simplified_goal is not None:
            return self.simplified_scenario, self.simplified_goal

        # Run LLM simplification
        with dspy.context(lm=self.LLM_model):
            prediction = self._simplify_sig(
                scenario_description=scenario_description,
                goal_description=goal_description,
                environment_type=environment_type,
            )

        self.simplified_scenario = prediction.simplified_scenario
        self.simplified_goal = prediction.simplified_goal

        return self.simplified_scenario, self.simplified_goal

    def get_simplified_scenario(self) -> str:
        """
        Get the cached simplified scenario.
        Must call simplify_scenario_and_goal() first.

        Returns:
            Simplified scenario description
        """
        if self.simplified_scenario is None:
            raise RuntimeError(
                "Scenario not yet simplified. Call simplify_scenario_and_goal() first."
            )
        return self.simplified_scenario

    def get_simplified_goal(self) -> str:
        """
        Get the cached simplified goal.
        Must call simplify_scenario_and_goal() first.

        Returns:
            Simplified goal description
        """
        if self.simplified_goal is None:
            raise RuntimeError(
                "Goal not yet simplified. Call simplify_scenario_and_goal() first."
            )
        return self.simplified_goal

    def reset(self):
        """Reset cached simplifications for re-initialization."""
        self.simplified_scenario = None
        self.simplified_goal = None
