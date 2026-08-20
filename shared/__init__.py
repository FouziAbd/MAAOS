"""Shared typed contracts frozen at P0 for the Symbolic-Twin BoxPush V1 architecture.

This package is env-agnostic. It contains ONLY typed contracts — no environment access,
no planning, no orchestration. The frozen BoxPush V1 domain instance lives in `domain/`.

Authority:
  - `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`  (architecture + V1 semantics)
  - `docs/decisions/P0_V1_DECISIONS.md`             (FINAL V1 design decisions)
  - `docs/handoff/section18.md`                     (code-evidence semantic handoff)

Hard rule for every later phase: nothing in `shared/` or the symbolic track may import the
backend (`functional_layer.*`, `shared_skills`). Symbolic APPLICABILITY and PLANNING must never
consult backend feasibility predicates, reachability, BFS, occupancy, collision or procedural
simulation (Decision 6). Declaring and grounding a skill's own deterministic world effects is a
different act and is permitted (Decision 13).

Every name exported here is part of the frozen contract (:82): layers bind to these, never to
ad hoc strings or privately re-declared look-alikes.
"""

from shared.versioning import ModelVersion, Provenance, ModelPatch
from shared.comparison_keys import ComparisonKey, WorldKey, SymbolicKey
from shared.ids import AgentId, BoxId, ZoneId, Cell, canonical_agent_pair
from shared.state_snapshot import (
    AgentSnapshot,
    BoxSnapshot,
    StaticWorld,
    EpisodeSnapshot,
    StateSnapshot,
)
from shared.skills import (
    REGISTRY,
    SkillName,
    ParameterType,
    ParameterSpec,
    SkillSignature,
    GroundedSkillCall,
    SkillRegistry,
    CallValidation,
    ValidatedCall,
    MalformedCall,
    UngroundedCall,
    SymbolicallyInapplicable,
    OutsideSymbolicModel,
)
from shared.symbolic_state import GroundedLiteral, SymbolicState, ProjectionContract
from shared.skill_ir import (
    PredicateName,
    Predicate,
    PredicateDecl,
    Effect,
    SkillIR,
    DomainIR,
)
from shared.execution import (
    RawLabel,
    NON_TERMINAL_PROGRESS_MARKER,
    PRODUCIBLE_RAW_LABELS,
    ADVERTISED_BUT_NOT_PRODUCIBLE,
    NEVER_OBSERVABLE_RAW,
    UNREACHABLE_IN_BOXPUSH,
    ExecutionOutcome,
    FailureStateClass,
    StepAccounting,
    ExecutionResult,
)
from shared.observation import (
    ObservationChannel,
    Track,
    V1_VISIBILITY,
    V1_NOT_TRACK_VISIBLE,
    is_visible,
    ExecutiveObservation,
)
from shared.task import Task
from shared.planner_result import PlannerResult, PlanFound, NoPlan, PlannerFailure
from shared.discrepancy import ExecutionDiscrepancy, DiscrepancyKind, ComparisonBasis
from shared.divergence import TrackDivergence, DivergenceKind
from shared.faults import InfrastructureFault, FaultKind, PRE_EXECUTION_FAULT_KINDS
from shared.reports import CoverageReport, ConfidenceReport
from shared.trace_schema import TraceEntry
from shared.orchestration_config import (
    OrchestrationConfig,
    OrchestrationPolicy,
    ExecutiveDecision,
)
from shared.backend_contract import V1Environment

__all__ = [
    "ModelVersion", "Provenance", "ModelPatch",
    "ComparisonKey", "WorldKey", "SymbolicKey",
    "AgentId", "BoxId", "ZoneId", "Cell", "canonical_agent_pair",
    "AgentSnapshot", "BoxSnapshot", "StaticWorld", "EpisodeSnapshot", "StateSnapshot",
    "SkillName", "ParameterType", "ParameterSpec", "SkillSignature", "GroundedSkillCall",
    "SkillRegistry", "REGISTRY", "CallValidation", "ValidatedCall", "MalformedCall",
    "UngroundedCall", "SymbolicallyInapplicable", "OutsideSymbolicModel",
    "GroundedLiteral", "SymbolicState", "ProjectionContract",
    "PredicateName", "Predicate", "Effect", "SkillIR", "DomainIR",
    "ObservationChannel", "Track", "V1_VISIBILITY", "V1_NOT_TRACK_VISIBLE", "is_visible",
    "ExecutiveObservation",
    "Task",
    "RawLabel", "NON_TERMINAL_PROGRESS_MARKER", "PRODUCIBLE_RAW_LABELS",
    "ADVERTISED_BUT_NOT_PRODUCIBLE", "NEVER_OBSERVABLE_RAW", "UNREACHABLE_IN_BOXPUSH",
    "ExecutionOutcome", "FailureStateClass", "StepAccounting", "ExecutionResult",
    "PlannerResult", "PlanFound", "NoPlan", "PlannerFailure",
    "ExecutionDiscrepancy", "DiscrepancyKind", "ComparisonBasis",
    "TrackDivergence", "DivergenceKind",
    "InfrastructureFault", "FaultKind", "PRE_EXECUTION_FAULT_KINDS",
    "CoverageReport", "ConfidenceReport",
    "TraceEntry",
    "OrchestrationConfig", "OrchestrationPolicy", "ExecutiveDecision",
    "PredicateDecl", "V1Environment",
]
