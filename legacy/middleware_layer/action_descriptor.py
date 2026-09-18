import dspy


class ActionDescriptor:
    """
    LLM-based action descriptor.
    Generates enriched action descriptions with cost, probability, and context information.
    Descriptions are generated once at agent initialization and cached.
    """

    def __init__(self, LLM_model: dspy.LM):
        """
        Args:
            LLM_model: DSPy language model instance (e.g., dspy.LM for Ollama)
        """
        self.LLM_model = LLM_model
        self.cache = {}  # {env_name: enriched_descriptions}
        self._enrich_sig = None

    def _configure_signature(self):
        """Define and instantiate the DSPy signature for action enrichment."""
        if self._enrich_sig is not None:
            return

        class ActionEnrichmentSignature(dspy.Signature):
            """
            Given a list of simple action descriptions, enrich them with important context.
            Include information about costs, success rates, preconditions, and effects.
            Format the output as a numbered list that an LLM decision-maker can easily parse.
            """
            raw_actions: str = dspy.InputField(
                desc="List of basic action descriptions (e.g., '0 -> move forward')"
            )
            environment_name: str = dspy.InputField(
                desc="Name/type of the environment (e.g., 'KAZ zombie game', 'Toy Rescue')"
            )
            action_count: int = dspy.InputField(
                desc="Total number of actions available"
            )

            enriched_descriptions: str = dspy.OutputField(
                desc="Enriched action list with costs, success rates, preconditions, and strategic tips. Numbered 0 to n-1."
            )

        with dspy.context(lm=self.LLM_model):
            self._enrich_sig = dspy.ChainOfThought(ActionEnrichmentSignature)

    def generate_action_descriptions(
        self,
        action_space: list,
        environment_name: str = "generic",
        env_context: str = ""
    ) -> str:
        """
        Generate enriched action descriptions from a basic action space.
        Results are cached per environment.

        Args:
            action_space: List of action descriptions (e.g., ["0 -> move", "1 -> attack"])
            environment_name: Name of the environment (for caching)
            env_context: Optional additional context about the environment

        Returns:
            Enriched action descriptions as a formatted string
        """
        self._configure_signature()

        # Check cache
        cache_key = environment_name.lower().replace(" ", "_")
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Format raw actions
        raw_actions_str = "\n".join(action_space)

        # Generate enriched descriptions
        with dspy.context(lm=self.LLM_model):
            prediction = self._enrich_sig(
                raw_actions=raw_actions_str,
                environment_name=environment_name,
                action_count=len(action_space),
            )

        enriched = prediction.enriched_descriptions

        # Cache result
        self.cache[cache_key] = enriched

        return enriched

    def get_action_descriptions(
        self,
        action_space: list,
        environment_name: str = "generic"
    ) -> str:
        """
        Get cached action descriptions. If not in cache, generate them.

        Args:
            action_space: List of action descriptions
            environment_name: Name of the environment

        Returns:
            Enriched action descriptions
        """
        cache_key = environment_name.lower().replace(" ", "_")

        if cache_key not in self.cache:
            return self.generate_action_descriptions(action_space, environment_name)

        return self.cache[cache_key]

    def clear_cache(self, environment_name: str = None):
        """Clear cached descriptions (for specific env or all)."""
        if environment_name is None:
            self.cache.clear()
        else:
            cache_key = environment_name.lower().replace(" ", "_")
            if cache_key in self.cache:
                del self.cache[cache_key]
