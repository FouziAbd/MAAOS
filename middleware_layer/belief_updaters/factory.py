"""
BeliefUpdaterFactory — instantiates the correct BaseBeliefUpdater subclass
from an EntitySchema's estimator_type string.

Usage
-----
    updater = BeliefUpdaterFactory.create(
        schema=CST_ENTITY_SCHEMA,
        initial_entities=prior_knowledge_dict,
        **kwargs,                      # forwarded to the concrete updater
    )
"""
from __future__ import annotations

import sys
import os

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
for _p in (_THIS_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model_layer.storage.base_belief_updater import BaseBeliefUpdater
from model_layer.storage.entity_schema import EntitySchema
from middleware_layer.belief_updaters.deterministic_grid_updater import DeterministicGridUpdater
from middleware_layer.belief_updaters.particle_filter_updater import ParticleFilterUpdater


_REGISTRY: dict[str, type] = {
    "deterministic_grid": DeterministicGridUpdater,
    "particle_filter":    ParticleFilterUpdater,
}


class BeliefUpdaterFactory:
    """Static factory for belief updater instantiation."""

    @staticmethod
    def create(
        schema: EntitySchema,
        initial_entities: dict,
        **kwargs,
    ) -> BaseBeliefUpdater:
        """
        Instantiate the updater declared in *schema.estimator_type*.

        Parameters
        ----------
        schema : EntitySchema
            Schema from the environment (provides estimator_type).
        initial_entities : dict
            Prior-knowledge state { entity_id: { field: value } }.
        **kwargs
            Additional keyword arguments forwarded to the updater constructor.
            For DeterministicGridUpdater: grid_width, grid_height.
            For ParticleFilterUpdater:    agent_role.

        Returns
        -------
        BaseBeliefUpdater
            Instantiated and ready-to-use updater.

        Raises
        ------
        ValueError
            If schema.estimator_type is not registered.
        """
        key = schema.estimator_type
        cls = _REGISTRY.get(key)
        if cls is None:
            raise ValueError(
                f"BeliefUpdaterFactory: unknown estimator_type '{key}'. "
                f"Registered types: {list(_REGISTRY)}"
            )
        return cls(initial_entities=initial_entities, **kwargs)

    @staticmethod
    def register(estimator_type: str, cls: type) -> None:
        """Register a custom updater class at runtime."""
        _REGISTRY[estimator_type] = cls
