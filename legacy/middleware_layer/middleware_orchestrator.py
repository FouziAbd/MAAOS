from typing import Callable, Dict, Optional

import dspy
from middleware_layer.observation_simplifier import ObservationSimplifier
from middleware_layer.action_descriptor import ActionDescriptor
from middleware_layer.scenario_simplifier import ScenarioSimplifier
from middleware_layer.action_executor import ActionExecutor


class MiddlewareOrchestrator:
    """
    Central orchestrator for middleware layer.
    Coordinates observation simplification, scenario/goal simplification, action description enrichment,
    and action execution. Manages caching and provides unified interface for the agent.
    """

    def __init__(
        self,
        env,
        agent_id: str,
        LLM_model: dspy.LM,
        scenario_description: str,
        goal_description: str,
        action_space: list,
        environment_name: str = "generic",
        observation_spec: str = "",
        use_observation_cache: bool = True,
        # ── belief system (optional) ──────────────────────────────────────────
        entity_schema=None,
        initial_entities: Optional[Dict] = None,
        obs_parser_fn: Optional[Callable] = None,
        prior_knowledge: str = "",
        history_window: int = 6,
        belief_updater_kwargs: Optional[Dict] = None,
    ):
        """
        Initialize middleware orchestrator.
        Performs one-time simplifications at initialization.

        Args:
            env: PettingZoo environment instance
            agent_id: Unique identifier for this agent
            LLM_model: DSPy language model for LLM-based components
            scenario_description: Verbose scenario description
            goal_description: Goal statement
            action_space: List of action descriptions (e.g., ["0 -> move forward", ...])
            environment_name: Name/type of environment (for caching and context)
            observation_spec: Detailed description of observation structure
            use_observation_cache: Whether to cache observation simplifications
            entity_schema: EntitySchema instance; if provided the belief system is enabled.
            initial_entities: Prior-knowledge entity dict forwarded to BeliefUpdaterFactory.
            obs_parser_fn: Callable(obs, agent_id) -> entity_snapshot.
                           Required when entity_schema is provided.
            prior_knowledge: Static natural-language facts prepended to every
                             belief context (grid layout, object positions, rules).
            history_window: Rolling history length for BeliefStateManager.
            belief_updater_kwargs: Extra kwargs forwarded to the concrete updater
                                   (e.g. grid_width/height for DeterministicGridUpdater,
                                   agent_role for ParticleFilterUpdater).
        """
        self.env = env
        self.agent_id = agent_id
        self.LLM_model = LLM_model
        self.environment_name = environment_name
        self.observation_spec = observation_spec
        self.use_observation_cache = use_observation_cache

        # Initialize middleware components
        self.obs_simplifier = ObservationSimplifier(LLM_model)
        self.action_descriptor = ActionDescriptor(LLM_model)
        self.scenario_simplifier = ScenarioSimplifier(LLM_model)
        self.action_executor = ActionExecutor(env, agent_id)

        # ── Belief system (wired only when entity_schema is supplied) ─────────
        self.belief_manager = None
        self._obs_parser_fn = obs_parser_fn
        if entity_schema is not None:
            from middleware_layer.belief_updaters.factory import BeliefUpdaterFactory
            from model_layer.storage.belief_state_manager import BeliefStateManager
            updater = BeliefUpdaterFactory.create(
                schema=entity_schema,
                initial_entities=initial_entities or {},
                **(belief_updater_kwargs or {}),
            )
            self.belief_manager = BeliefStateManager(
                updater=updater,
                history_window=history_window,
                prior_knowledge=prior_knowledge,
                action_names=entity_schema.action_names,
            )

        # Perform one-time simplifications
        print(f"[Middleware] Initializing for agent {agent_id}...")

        print(f"[Middleware] Simplifying scenario and goal...")
        self.simplified_scenario, self.simplified_goal = (
            self.scenario_simplifier.simplify_scenario_and_goal(
                scenario_description=scenario_description,
                goal_description=goal_description,
                environment_type=environment_name,
            )
        )

        print(f"[Middleware] Generating enriched action descriptions...")
        self.enriched_actions = self.action_descriptor.generate_action_descriptions(
            action_space=action_space,
            environment_name=environment_name,
        )

        print(f"[Middleware] Initialization complete.")

    def process_observation(
        self,
        raw_observation,
        agent_instructions: str = "",
        tactical_summary: str = ""
    ) -> str:
        """
        Simplify a raw observation using LLM.

        Args:
            raw_observation: Raw observation from environment (numpy array, dict, or other)
            agent_instructions: Optional role/task-specific context for the agent
            tactical_summary: Optional pre-computed tactical summary (e.g., from summarize_kaz_obs)
                            If provided, this will be passed directly instead of computing from raw obs

        Returns:
            Simplified observation summary as string
        """
        # If tactical summary is provided, return it directly (no duplication)
        if tactical_summary:
            return tactical_summary
        
        # Otherwise, compute simplification from raw observation
        context = f"Environment: {self.environment_name}"
        if self.observation_spec:
            context = f"{context}\n\n{self.observation_spec}"
        
        return self.obs_simplifier.simplify_raw_observation(
            raw_observation=raw_observation,
            environment_context=context,
            agent_instructions=agent_instructions,
            env_id=self.environment_name,
            use_cache=self.use_observation_cache,
        )

    def get_simplified_scenario(self) -> str:
        """
        Get the cached simplified scenario description.

        Returns:
            Simplified scenario text
        """
        return self.scenario_simplifier.get_simplified_scenario()

    def get_simplified_goal(self) -> str:
        """
        Get the cached simplified goal description.

        Returns:
            Simplified goal text
        """
        return self.scenario_simplifier.get_simplified_goal()

    def get_enriched_actions(self) -> str:
        """
        Get the cached enriched action descriptions.

        Returns:
            Enriched action descriptions (formatted for LLM)
        """
        return self.enriched_actions

    def execute_action(self, action_index: int) -> dict:
        """
        Execute a planner-chosen action in the environment.

        Args:
            action_index: Integer action index from planner

        Returns:
            Execution result dictionary
        """
        # Clamp action to valid range as safety measure
        clamped_action = self.action_executor.clamp_action(action_index)

        if clamped_action != action_index:
            print(
                f"[Middleware] Warning: Action {action_index} out of range. "
                f"Clamped to {clamped_action}."
            )

        return self.action_executor.execute_action(clamped_action)

    def get_valid_action_range(self) -> tuple:
        """
        Get valid action index range for this environment.

        Returns:
            Tuple of (min_action, max_action)
        """
        return self.action_executor.get_valid_action_range()

    def update_belief(self, action: int, reward: float, obs) -> None:
        """
        Parse *obs* with obs_parser_fn then forward to BeliefStateManager.
        No-op if the belief system was not configured.
        """
        if self.belief_manager is None:
            return
        if self._obs_parser_fn is None:
            raise RuntimeError(
                "[Middleware] entity_schema provided but obs_parser_fn is None. "
                "Pass obs_parser_fn= to MiddlewareOrchestrator.__init__."
            )
        snapshot = self._obs_parser_fn(obs, self.agent_id)
        self.belief_manager.update(action, reward, snapshot)

    def get_belief_context(self) -> str:
        """
        Return the formatted belief context string for the LLM.
        Returns an empty string if the belief system was not configured.
        """
        if self.belief_manager is None:
            return ""
        return self.belief_manager.get_belief_context()

    def reset_belief(self, seed=None) -> None:
        """Reset belief history and updater to prior-knowledge defaults."""
        if self.belief_manager is not None:
            self.belief_manager.reset(seed=seed)

    def clear_caches(self):
        """Clear all middleware caches (observation simplifications)."""
        self.obs_simplifier.clear_cache(env_id=self.environment_name)
        print(f"[Middleware] Caches cleared for {self.environment_name}")

    def __repr__(self):
        return (
            f"MiddlewareOrchestrator("
            f"agent_id={self.agent_id}, "
            f"env={self.environment_name})"
        )
