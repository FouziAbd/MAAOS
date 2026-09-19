"""`kit` — default implementations for domain authors (DK2; `docs/decisions/DK1_DOMAIN_PACKAGE.md`).

Every helper here is EXTRACTED from what BoxPush and the R5 probe both hand-write, except
the four BoxPush-only extractions recorded in `docs/decisions/DK1_DOMAIN_PACKAGE.md` §"DK2 —
kit extraction record" (`bfs_plan`; the case-(c) trio `note_primitive_steps` /
`mid_attempt_fault` / the `_attempt` exception wrap) and two documented conveniences (the
fully-observable `_observe` default; the `executed` diagnostic list). Nothing comes from a
hypothetical domain. The kit imports only the standard library and `shared`; `runtime/`
never imports it.

    keys          digest / world_key / symbolic_key over a `canonical()` payload
    protocols     Identified / SymbolicKeyed and the one `ground_by_identity` check
    environment   EnvironmentBase — the contract's mechanics (refusals, malformed/ungrounded
                  arms, result builders, case-(c) provenance); the only module that raises faults
    track         ProjectionTrack — the exact-projection symbolic track
    services      SymbolicModel (what an author writes) + DerivedDomainServices
    planning      bfs_plan — the frozen planner's result categories, symbolic state only
    comparator    DefaultProposalComparator — the frozen divergence kinds, domain rules opt-in

Rules: no domain vocabulary; no `Any`-primary or dict-shaped API; only `environment.py`
raises faults and it never catches one (its one handler re-raises); the catch-alls in
`services.monitor` and `planning.bfs_plan` convert any author error into the frozen
escapes (`ValueError` / `PlannerFailure`) exactly as `runtime/loop.py` and
`symbolic/planner.py` expect; result builders never default a failure class and never set
`raw_label`; nothing here can reach an environment from planning or applicability.
"""
from kit.comparator import DefaultProposalComparator
from kit.environment import CASE_C_KEY, REFUSED, EnvironmentBase
from kit.keys import digest, symbolic_key, world_key
from kit.planning import NODE_BUDGET, bfs_plan
from kit.protocols import (
    Identified,
    IdentifiedCall,
    IdentifiedState,
    SymbolicKeyed,
    ground_by_identity,
)
from kit.services import DerivedDomainServices, SymbolicModel
from kit.track import ProjectionTrack

__all__ = [
    "CASE_C_KEY",
    "DefaultProposalComparator",
    "DerivedDomainServices",
    "EnvironmentBase",
    "Identified",
    "IdentifiedCall",
    "IdentifiedState",
    "NODE_BUDGET",
    "ProjectionTrack",
    "REFUSED",
    "SymbolicKeyed",
    "SymbolicModel",
    "bfs_plan",
    "digest",
    "ground_by_identity",
    "symbolic_key",
    "world_key",
]
