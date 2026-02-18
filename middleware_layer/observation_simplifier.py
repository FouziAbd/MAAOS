import dspy
import hashlib
import numpy as np


class ObservationSimplifier:
    """
    Generic LLM-based observation simplifier.
    Converts raw observations (numpy arrays or structured data) into human-readable summaries.
    Caches results to avoid redundant LLM calls for identical observations.
    """

    def __init__(self, LLM_model: dspy.LM):
        """
        Args:
            LLM_model: DSPy language model instance (e.g., dspy.LM for Ollama)
        """
        self.LLM_model = LLM_model
        self.cache = {}  # {(obs_hash, env_id): simplified_text}
        self._simplify_sig = None

    def _configure_signature(self):
        """Define and instantiate the DSPy signature for observation simplification."""
        if self._simplify_sig is not None:
            return

        class ObservationSummarySignature(dspy.Signature):
            """
            Simplify and summarize a complex raw observation into an LLM-friendly format.
            Focus on the most relevant entities, positions, threats, and state information.
            Keep the output concise and actionable.
            """
            raw_observation: str = dspy.InputField(
                desc="Raw observation data (array, structured text, or formatted dump)"
            )
            environment_context: str = dspy.InputField(
                desc="Description of the environment type and what the observation represents"
            )
            agent_instructions: str = dspy.InputField(
                desc="Task-specific instructions or role description for this agent"
            )

            simplified_summary: str = dspy.OutputField(
                desc="Concise, human-readable summary of the observation (< 200 words, actionable items only)"
            )

        with dspy.context(lm=self.LLM_model):
            self._simplify_sig = dspy.ChainOfThought(ObservationSummarySignature)

    def _hash_observation(self, obs):
        """
        Create a hash of the observation for caching.
        Handles numpy arrays, lists, and primitive types.
        """
        try:
            if isinstance(obs, np.ndarray):
                obs_str = np.array2string(obs, separator=',')
            else:
                obs_str = str(obs)
            return hashlib.md5(obs_str.encode()).hexdigest()
        except Exception:
            return None

    def simplify_raw_observation(
        self,
        raw_observation,
        environment_context: str,
        agent_instructions: str = "",
        env_id: str = "default",
        use_cache: bool = True
    ) -> str:
        """
        Simplify a raw observation using LLM.

        Args:
            raw_observation: Numpy array, list, dict, or string representation of observation
            environment_context: Description of the environment (e.g., "KAZ zombie survival game")
            agent_instructions: Role/task-specific instructions for the agent (optional)
            env_id: Unique identifier for the environment (for cache key)
            use_cache: Whether to use cached results for identical observations

        Returns:
            Simplified observation summary as a string
        """
        self._configure_signature()

        # Check cache
        if use_cache:
            obs_hash = self._hash_observation(raw_observation)
            if obs_hash and (obs_hash, env_id) in self.cache:
                return self.cache[(obs_hash, env_id)]

        # Convert observation to string format
        if isinstance(raw_observation, np.ndarray):
            obs_str = self._format_numpy_observation(raw_observation)
        elif isinstance(raw_observation, dict):
            obs_str = self._format_dict_observation(raw_observation)
        else:
            obs_str = str(raw_observation)

        # Run LLM simplification
        with dspy.context(lm=self.LLM_model):
            prediction = self._simplify_sig(
                raw_observation=obs_str,
                environment_context=environment_context,
                agent_instructions=agent_instructions,
            )

        simplified = prediction.simplified_summary

        # Cache result
        if use_cache:
            obs_hash = self._hash_observation(raw_observation)
            if obs_hash:
                self.cache[(obs_hash, env_id)] = simplified

        return simplified

    def _format_numpy_observation(self, obs: np.ndarray) -> str:
        """Format numpy array for LLM consumption."""
        obs = np.asarray(obs, dtype=float)
        if obs.ndim == 1:
            return f"Array shape {obs.shape}: {obs.round(3)}"
        elif obs.ndim == 2:
            return f"Matrix shape {obs.shape}:\n{obs.round(3)}"
        elif obs.ndim == 3:
            shape = obs.shape
            return f"Tensor shape {shape} (too large for full display; showing summary instead)"
        else:
            return str(obs)

    def _format_dict_observation(self, obs: dict) -> str:
        """Format dictionary observation for LLM consumption."""
        lines = []
        for key, value in obs.items():
            if isinstance(value, np.ndarray):
                val_str = f"array shape {value.shape}"
            else:
                val_str = str(value)
            lines.append(f"{key}: {val_str}")
        return "\n".join(lines)

    def clear_cache(self, env_id: str = None):
        """Clear cached observations (for specific env or all)."""
        if env_id is None:
            self.cache.clear()
        else:
            self.cache = {k: v for k, v in self.cache.items() if k[1] != env_id}
