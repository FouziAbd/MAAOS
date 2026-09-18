import json
import collections
from typing import Dict, List, Optional

from model_layer.storage.base_belief_updater import BaseBeliefUpdater


class BeliefStateManager:
    """
    Maintains an agent's belief state as a rolling window of entity JSON
    snapshots.  Environment- and middleware-agnostic: all domain logic
    lives inside the injected BaseBeliefUpdater.

    Usage pattern
    -------------
    At each step the caller should:
        1. Parse the raw observation into an entity_snapshot dict.
        2. Call  belief_manager.update(action, reward, entity_snapshot).
        3. Call  belief_manager.get_belief_context()  and pass the result
           to the LLM planner as the observation summary.
    """

    def __init__(
        self,
        updater: BaseBeliefUpdater,
        history_window: int = 6,
        prior_knowledge: str = "",
        action_names: Optional[Dict[int, str]] = None,
    ):
        """
        Parameters
        ----------
        updater : BaseBeliefUpdater
            Domain-specific state estimator (deterministic grid, particle
            filter, etc.).  Injected by the middleware layer.
        history_window : int
            Number of past steps to keep in the rolling history.
        prior_knowledge : str
            Static natural-language facts about the environment (grid
            layout, initial object positions, rules).  Prepended to every
            belief context string so the LLM always has this background.
        action_names : dict[int, str], optional
            Maps action indices to readable names for the history log.
            If omitted, the raw integer is shown.
        """
        self.updater        = updater
        self.prior_knowledge = prior_knowledge
        self.action_names   = action_names or {}
        self._history: collections.deque = collections.deque(maxlen=history_window)

    # ── public API ────────────────────────────────────────────────────────────

    def update(self, action: int, reward: float, entity_snapshot: dict) -> None:
        """
        Ingest the outcome of one env step.

        Attaches action and reward to the snapshot (if not already set),
        forwards it to the updater, then stores it in the history window.

        Parameters
        ----------
        action : int
            The action the agent just executed.
        reward : float
            The reward signal received after the action.
        entity_snapshot : dict
            Parsed observation in the standard entity JSON format.  The
            "step" field is auto-incremented if not provided.
        """
        snapshot = dict(entity_snapshot)   # shallow copy — don't mutate caller's dict

        # Fill in bookkeeping fields if the parser left them as None / missing
        if snapshot.get("action") is None:
            snapshot["action"] = action
        if snapshot.get("reward") is None:
            snapshot["reward"] = reward
        if snapshot.get("step") is None:
            snapshot["step"] = (
                self._history[-1]["step"] + 1 if self._history else 1
            )

        self.updater.update_entity(snapshot)
        self._history.append(snapshot)

    def get_belief_context(self) -> str:
        """
        Build a compact belief context string for the LLM.

        Structure
        ---------
        === PRIOR KNOWLEDGE ===   (static, from constructor)

        === RECENT ACTIONS ===
        Step K | action=<name> | reward=<+X.XX>   (no entity dump — too verbose)
        ...

        === CURRENT ESTIMATED STATE ===
        <filtered entity state: omits None values, empty lists, visible_cells>
        """
        parts: List[str] = []

        # 1. Prior knowledge
        if self.prior_knowledge:
            parts.append("=== PRIOR KNOWLEDGE ===")
            parts.append(self.prior_knowledge.strip())
            parts.append("")

        # 2. Rolling history — action + reward only (entity JSON is too large)
        if self._history:
            parts.append(f"=== RECENT ACTIONS (last {len(self._history)} steps) ===")
            for entry in self._history:
                action_int  = entry.get("action")
                action_name = self.action_names.get(action_int, str(action_int))
                reward_val  = entry.get("reward", 0.0)
                step_idx    = entry.get("step", "?")
                parts.append(
                    f"Step {step_idx} | {action_name} | reward={reward_val:+.2f}"
                )
            parts.append("")

        # 3. Current estimated state — filter verbose / null fields
        parts.append("=== CURRENT ESTIMATED STATE ===")
        parts.append(json.dumps(self._compact_entities(), indent=2))

        return "\n".join(parts)

    def _compact_entities(self) -> dict:
        """Return entity state with None values, empty collections, and
        verbose fields (visible_cells, detected_objects) removed."""
        _SKIP_FIELDS = {"visible_cells", "detected_objects"}
        result = {}
        for eid, edata in self.updater.get_all_entities().items():
            compact = {
                k: v for k, v in edata.items()
                if v is not None
                and v != []
                and k not in _SKIP_FIELDS
            }
            result[eid] = compact
        return result

    def reset(self, seed: Optional[int] = None) -> None:
        """Clear history and reset the updater to prior-knowledge defaults."""
        self._history.clear()
        self.updater.reset()

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def history_as_json(self) -> List[dict]:
        """Raw entity JSON history as a list — useful for logging / debugging."""
        return list(self._history)
