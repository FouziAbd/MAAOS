import re
import dspy


class CentralizedDSPyPlanner:
    """
    Reusable CENTRALIZED DSPy planner: one LLM call sees the combined situation of ALL
    agents and returns ONE decision per agent. Sibling of the per-agent ``DSPyPlanner``
    (which returns a single int for a single agent).

    Like ``DSPyPlanner`` the signature is GENERIC and never rewritten per environment —
    all task-specificity is passed in as input VALUES (task_instructions, decision_space,
    team_situation, …). Configure once, then call :meth:`decide` each cycle/step.

    Typical use::

        planner = CentralizedDSPyPlanner()
        planner.configure_ollama(lm)
        reasoning, decisions = planner.decide(
            task_instructions=RULES,
            decision_space=ACTION_MENU,
            team_situation=combined_view,
            objective="deliver both boxes",
            agents=["agent_0", "agent_1"],
            recent_feedback=last_outcomes,
            parser=lambda aid, raw: NAME_TO_INT.get(raw.upper(), STAY),
        )
        # decisions == {"agent_0": <parsed>, "agent_1": <parsed>}
    """

    def __init__(self, name: str = "team"):
        self.name = name
        self._predict = None

    def configure_ollama(self, LLM_model: dspy.LM) -> None:
        dspy.configure(lm=LLM_model)

        class TeamActionSig(dspy.Signature):
            # Generic CENTRALIZED planner: works for ANY env / decision vocabulary as long as
            # you pass the rules, the decision menu, the combined situation, and the agent ids.
            task_instructions: str = dspy.InputField(
                desc="Task rules, goal, and what each decision means. Include all constraints."
            )
            decision_space: str = dspy.InputField(
                desc="The menu of valid decisions an agent may take (actions or skills) and "
                     "their effects/labels."
            )
            team_situation: str = dspy.InputField(
                desc="Combined state/belief of ALL agents (shared map + per-agent info). "
                     "Avoid raw arrays."
            )
            recent_feedback: str = dspy.InputField(
                desc="Each agent's last decision(s) and their outcomes."
            )
            objective: str = dspy.InputField(desc="Goal for this episode/team.")
            agents: str = dspy.InputField(
                desc="Comma-separated agent ids. Output EXACTLY one decision line per id."
            )

            reasoning: str = dspy.OutputField(
                desc="1-2 sentences: what each agent should do this step and why."
            )
            decisions: str = dspy.OutputField(
                desc="One line PER agent, formatted exactly 'agent_id: DECISION' (one decision "
                     "per agent, chosen from the decision_space). No extra lines."
            )

        self._predict = dspy.ChainOfThought(TeamActionSig)

    @staticmethod
    def _parse_decisions(text: str, agents: list) -> dict:
        """Split the model's 'agent_id: DECISION' lines into {agent_id: raw_decision}.
        Agents with no parseable line are omitted (caller applies its own default)."""
        result = {}
        for aid in agents:
            m = re.search(rf'{re.escape(aid)}\s*[:=]\s*(.+)', text)
            if m:
                val = m.group(1).strip()
                if val:
                    result[aid] = val
        return result

    def decide(self, task_instructions: str, decision_space: str, team_situation: str,
               objective: str, agents: list, recent_feedback: str = "", parser=None):
        """Run one centralized LLM call → (reasoning, {agent_id: decision}).

        ``parser`` (optional): ``parser(agent_id, raw_str) -> typed_decision`` applied to
        each parsed value. Without it, raw decision strings are returned. On any LLM/parse
        error returns ("[error] …", {}) so the caller can default every agent safely.
        """
        if self._predict is None:
            raise RuntimeError(
                f"CentralizedDSPyPlanner '{self.name}' not configured. Call configure_ollama()."
            )
        try:
            out = self._predict(
                task_instructions=task_instructions,
                decision_space=decision_space,
                team_situation=team_situation,
                recent_feedback=recent_feedback or "none yet",
                objective=objective,
                agents=", ".join(agents),
            )
            reasoning = getattr(out, "reasoning", "")
            raw = self._parse_decisions(out.decisions, agents)
        except Exception as e:  # noqa: BLE001 — mirror DSPyPlanner's graceful fallback
            print(f"    [CentralizedPlanner {self.name}] error: {type(e).__name__}: {e}")
            return f"[error] {type(e).__name__}", {}

        decisions = ({aid: parser(aid, val) for aid, val in raw.items()}
                     if parser is not None else raw)

        preview = " | ".join(f"{aid}={raw.get(aid, '∅')}" for aid in agents)
        print(f"    [CentralizedPlanner {self.name}] {preview}  | {reasoning[:100]}")
        return reasoning, decisions
