import dspy
# DSPy planners (one per agent) using Ollama
class DSPyPlanner:
    def __init__(self, agent: str):
        self.agent = agent
        self._predict  = None

    def configure_ollama(self, LLM_model: dspy.LM) -> None:
        dspy.configure(lm=LLM_model)

        class NextActionSig(dspy.Signature):
            # Generic agent planner: works for ANY env as long as you pass instructions + action map + obs summary.
            task_instructions: str = dspy.InputField(
                desc="Task-specific instructions and rules. Include output format requirements."
            )
            obs_summary: str = dspy.InputField(
                desc="Compact state/observation summary; avoid raw arrays."
            )
            #action_map: str = dspy.InputField(
            #    desc="Discrete action mapping, one per line: 'i -> meaning'."
            #)
            recent_actions: str = dspy.InputField(
                desc="Last few actions taken by this agent."
            )
            objective: str = dspy.InputField(desc="Goal for this episode/agent.")
            n_actions: int = dspy.InputField(desc="Number of discrete actions available.")

            action: int = dspy.OutputField(desc="Return ONLY an integer in [0, n_actions-1].")
            rationale: str = dspy.OutputField(desc="<= 12 words.")
        
        self._predict = dspy.ChainOfThought(NextActionSig)
        #self._predict = dspy.Predict(NextActionSig)
    
    def selec_action_index(self, instructions: str, obs_summary: str, #action_map: str,
                       objective: str, recent_actions: str, n_actions: int) -> int:
        if self._predict is None:
            raise RuntimeError(f"DSPy planner for {self.agent} not configured. Call configure_ollama().")
        
        out = self._predict(
            task_instructions=instructions,
            obs_summary=obs_summary,
            #action_map=action_map,
            objective=objective,
            recent_actions=recent_actions,
            n_actions=n_actions,
        )

        try:
            idx = int(out.action)
        except Exception:
            idx = n_actions - 1  # fallback to last action (often NOOP)
        print(f"LLM returnd {idx}| {out.rationale}")

        return idx