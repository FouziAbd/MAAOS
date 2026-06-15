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
                desc="Task-specific instructions, rules, and action definitions. Include what each action does."
            )
            action_descriptions: str = dspy.InputField(
                desc="Detailed action space: what each action number means and its effects."
            )
            obs_summary: str = dspy.InputField(
                desc="Compact state/observation summary; avoid raw arrays."
            )
            recent_actions: str = dspy.InputField(
                desc="Last few actions taken by this agent and their outcomes."
            )
            objective: str = dspy.InputField(desc="Goal for this episode/agent.")
            n_actions: int = dspy.InputField(desc="Number of discrete actions available.")

            action: int = dspy.OutputField(desc="Return ONLY an integer in [0, n_actions-1]. Choose the action that best achieves the objective given the observation. Follow any SUGGESTED_ACTION or CRITICAL RULES stated in task_instructions or obs_summary.")
        
        self._predict = dspy.ChainOfThought(NextActionSig)
        #self._predict = dspy.Predict(NextActionSig)
    
    def selec_action_index(self, instructions: str, obs_summary: str, action_descriptions: str,
                       objective: str, recent_actions: str, n_actions: int) -> int:
        if self._predict is None:
            raise RuntimeError(f"DSPy planner for {self.agent} not configured. Call configure_ollama().")
        
        try:
            out = self._predict(
                task_instructions=instructions,
                action_descriptions=action_descriptions,
                obs_summary=obs_summary,
                objective=objective,
                recent_actions=recent_actions,
                n_actions=n_actions,
            )
            idx = int(out.action)
            reasoning = getattr(out, "reasoning", "")
        except Exception as e:
            idx = 3
            reasoning = f"[parse-error fallback] {type(e).__name__}"

        log_msg = f"    [Planner {self.agent}] Action: {idx} | Reasoning: {reasoning[:120]}"
        print(log_msg)
        
        # Import and use the log_message function from KAZ if available
        try:
            import sys
            kaz_module = sys.modules.get('__main__')
            if kaz_module and hasattr(kaz_module, 'log_message'):
                kaz_module.log_message(log_msg)
        except:
            pass

        return idx