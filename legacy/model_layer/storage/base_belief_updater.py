from abc import ABC, abstractmethod


class BaseBeliefUpdater(ABC):
    """
    Abstract state estimator for one agent's self-belief.

    Subclasses implement the mathematics appropriate to their domain
    (deterministic dead-reckoning, particle filter, etc.).
    All I/O uses plain Python dicts — no environment or middleware imports.

    Entity snapshot contract
    ------------------------
    Every call to update_entity receives a dict of the form:
        {
            "step":   int,
            "action": int,
            "reward": float,
            "entities": {
                "self":     { <field>: <value>, ... },
                "object_0": { <field>: <value>, ... },
                ...
            }
        }
    The "entities" sub-dict contains only the fields that were observable
    in the raw observation.  Internal fields (e.g. dead-reckoned position)
    are added by the updater itself.
    """

    # ── subclasses declare this as a class-level string ──────────────────────
    estimator_type: str = ""

    # ── abstract methods ──────────────────────────────────────────────────────

    @abstractmethod
    def update_entity(self, entity_snapshot: dict) -> None:
        """
        Ingest the latest entity snapshot and update internal estimates.

        Parameters
        ----------
        entity_snapshot : dict
            Parsed observation in the standard entity JSON format.
        """

    @abstractmethod
    def get_entity_state(self, entity_id: str) -> dict:
        """
        Return the current best-estimate state for a single entity.

        Parameters
        ----------
        entity_id : str
            Key matching one of the entities tracked by this updater
            (e.g. "self", "object_0", "nearest_zombie").

        Returns
        -------
        dict
            Estimated field values.  Returns an empty dict if the entity
            is not yet known.
        """

    @abstractmethod
    def get_all_entities(self) -> dict:
        """
        Return the complete estimated world model.

        Returns
        -------
        dict
            Mapping entity_id → estimated state dict for every tracked entity.
        """

    @abstractmethod
    def get_uncertainty(self, entity_id: str) -> float:
        """
        Return a normalised confidence score for a single entity.

        Returns
        -------
        float
            Value in [0.0, 1.0].
            1.0 = fully certain (e.g. directly observed or deterministically
                  tracked).
            0.0 = completely unknown.
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset all internal state to prior-knowledge defaults."""
