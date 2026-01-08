import dspy
# DSPy planners (one per agent) using Ollama
class DSPyPlanner:
    def __init__(self, agent: str):
        self.agent = agent
        self._predict  = None

    def configure_ollama(self, LLM_model: dspy.LM) -> None:
        dspy.configure(lm=LLM_model)

        class NextActionSig(dspy.Signature):
            belief_summary: str = dspy.InputField(desc="Short summary of agent belief (for now it's a text with all the info about the environment)")
            observation_summary: str = dspy.InputField(desc="summary of current observation")
            n_actions: int = dspy.InputField(desc="Number of discrete actions available")
            objective: str = dspy.InputField(desc="Overall objective")
            action: int = dspy.OutputField(desc="An integer action index in [0, n_actions-1]")
            rationale: str = dspy.OutputField(desc="One short sentence why")
        
        self._predict = dspy.ChainOfThought(NextActionSig)
    
    def selec_action_index(self, belief: str, obs: str, objective: str, n_actions: int) -> int:
        if self._predict is None:
            raise RuntimeError(f"DSPy planner for {self.agent} not configured. Call configure_ollama().")
        
        out = self._predict(
            belief_summary=belief,
            observation_summary=obs,
            n_actions=n_actions,
            objective=objective,
        )

        idx = out.action
        print(f"LLM returnd {idx}| {out.rationale}")
        #if not txt or any(c not in "-0123456789" for c in txt):
        #    raise ValueError(f"LLM returned non-integer action_index='{txt}' for agent={self.agent}")

        return idx