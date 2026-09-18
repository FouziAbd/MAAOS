from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FieldSpec:
    """
    Describes one field on an entity.

    Parameters
    ----------
    name : str
        Field key used in entity JSON dicts.
    dtype : str
        Logical type hint: "int", "float", "str", "bool",
        "list[int]", "list[float]", "list[list[int]]".
    observable : bool
        True  — value appears directly in the raw observation.
        False — value is computed internally by the updater
                (dead-reckoned, inferred from rewards, prior-only, etc.).
    description : str
        Human-readable note for documentation / LLM prompts.
    """

    name: str
    dtype: str
    observable: bool
    description: str = ""


@dataclass
class EntitySpec:
    """
    Describes one class of entities tracked by the belief system.

    The ``entity_id_pattern`` may use Unix shell-style wildcards so that
    a single spec can cover a family of entities:
        "object_*"  matches "object_0", "object_1", …
        "self"      matches exactly the agent's own state entity.

    Parameters
    ----------
    entity_id_pattern : str
        Glob pattern matched against entity IDs in a snapshot.
    fields : list[FieldSpec]
        All fields (observable + internal) for this entity class.
    is_self : bool
        Exactly one EntitySpec per schema should set this to True.
        It marks the entity that represents the agent itself.
    """

    entity_id_pattern: str
    fields: List[FieldSpec]
    is_self: bool = False

    def matches(self, entity_id: str) -> bool:
        """Return True if *entity_id* matches this spec's pattern."""
        return fnmatch.fnmatch(entity_id, self.entity_id_pattern)

    @property
    def observable_fields(self) -> List[FieldSpec]:
        return [f for f in self.fields if f.observable]

    @property
    def internal_fields(self) -> List[FieldSpec]:
        return [f for f in self.fields if not f.observable]


@dataclass
class EntitySchema:
    """
    Full contract between an environment and the belief system.

    Every environment exposes exactly one EntitySchema.  The middleware
    reads it to:
      1. Instantiate the correct BaseBeliefUpdater subclass via
         ``estimator_type``.
      2. Build ``initial_entities`` from prior-knowledge field values.
      3. Configure BeliefStateManager with ``action_names``.

    Parameters
    ----------
    environment_name : str
        Human-readable environment identifier.
    estimator_type : str
        Key used by BeliefUpdaterFactory to select the right updater.
        Defined values: "deterministic_grid" | "particle_filter".
    entity_specs : list[EntitySpec]
        One spec per entity class.  Order does not matter.
    action_names : dict[int, str]
        Maps action indices to readable names.
        Used only for history formatting in BeliefStateManager.
    """

    environment_name: str
    estimator_type: str
    entity_specs: List[EntitySpec]
    action_names: Dict[int, str] = field(default_factory=dict)

    # ── lookup helpers ────────────────────────────────────────────────────────

    def get_spec(self, entity_id: str) -> Optional[EntitySpec]:
        """
        Return the first EntitySpec whose pattern matches *entity_id*.
        Returns None if no spec matches.
        """
        for spec in self.entity_specs:
            if spec.matches(entity_id):
                return spec
        return None

    def get_self_spec(self) -> Optional[EntitySpec]:
        """Return the EntitySpec flagged as is_self=True, or None."""
        for spec in self.entity_specs:
            if spec.is_self:
                return spec
        return None

    def all_entity_id_patterns(self) -> List[str]:
        """Return every entity_id_pattern declared in this schema."""
        return [spec.entity_id_pattern for spec in self.entity_specs]

    def observable_fields_for(self, entity_id: str) -> List[FieldSpec]:
        """Shortcut: observable fields for a specific entity ID."""
        spec = self.get_spec(entity_id)
        return spec.observable_fields if spec else []

    def internal_fields_for(self, entity_id: str) -> List[FieldSpec]:
        """Shortcut: internal (non-observable) fields for a specific entity ID."""
        spec = self.get_spec(entity_id)
        return spec.internal_fields if spec else []

    def validate(self) -> None:
        """
        Raise ValueError if the schema is misconfigured.
        Called by the middleware before instantiating an updater.
        """
        self_specs = [s for s in self.entity_specs if s.is_self]
        if len(self_specs) != 1:
            raise ValueError(
                f"EntitySchema '{self.environment_name}': exactly one EntitySpec "
                f"must have is_self=True, found {len(self_specs)}."
            )
        if not self.estimator_type:
            raise ValueError(
                f"EntitySchema '{self.environment_name}': estimator_type must not be empty."
            )
        if not self.entity_specs:
            raise ValueError(
                f"EntitySchema '{self.environment_name}': entity_specs must not be empty."
            )
