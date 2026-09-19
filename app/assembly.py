"""Generic loop assembly over a `DomainPackage` (DK1 — `docs/decisions/DK1_DOMAIN_PACKAGE.md`).

`assemble_loop(package)` is `app.box_push_v1.build_loop` generalized: it reads the
declaration instead of the BoxPush module, calls each factory, and hands the results to the
unchanged `ExecutiveLoopManager` through the same keyword seams. The loop, its constructor,
and `build_loop` are untouched; the BoxPush transcripts through this path are pinned
cycle by cycle against the frozen baseline (`tests/test_dk1_domain_package.py`).

Rules this function embodies:

- every keyword override replaces exactly ONE composed component (mirrors `build_loop`;
  no `**overrides`, no dict-shaped surface);
- `provenance` passes straight through, so the loop keeps its own default
  `Provenance(source="runtime/loop.py::ExecutiveLoopManager", ...)` — a trace assembled here
  is indistinguishable from one assembled by `build_loop`;
- the environment is constructed here and given to the loop ONLY; no domain factory ever
  receives it (the symbolic side cannot close over the backend);
- a declared reasoning track is attached by default with the declared comparator;
  `use_reasoning_track=False` assembles the same domain without any advisory track (what the
  offline validation run needs), and an explicit `nl_track=` replaces the declared one.
"""
from __future__ import annotations

from typing import Optional, Type

from runtime.loop import ExecutiveLoopManager
from shared.contracts import (
    AdvisoryProposal,
    DomainServices,
    Environment,
    OrchestrationPolicyContract,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
)
from shared.orchestration_config import OrchestrationConfig
from shared.versioning import Provenance

from app.domain_package import DomainPackage, EnvironmentOutcome


def assemble_loop[
    StateT: RuntimeState,
    SymbolicStateT,
    CallT: RuntimeCall,
    TaskT: TaskContract,
    ProposalT: AdvisoryProposal,
](
    package: DomainPackage[StateT, SymbolicStateT, CallT, TaskT, ProposalT],
    task_name: Optional[str] = None,
    config: Optional[OrchestrationConfig] = None,
    nl_track: Optional[ReasoningTrack[StateT, TaskT, ProposalT]] = None,
    provenance: Optional[Provenance] = None,
    policy: Optional[OrchestrationPolicyContract[StateT, CallT, ProposalT]] = None,
    *,
    loop_class: Type[
        ExecutiveLoopManager[StateT, SymbolicStateT, CallT, TaskT, ProposalT]
    ] = ExecutiveLoopManager,
    environment: Optional[
        Environment[StateT, CallT, EnvironmentOutcome[StateT, CallT], object]
    ] = None,
    domain: Optional[DomainServices[StateT, SymbolicStateT, CallT]] = None,
    symbolic_track: Optional[SymbolicTrack[StateT, SymbolicStateT]] = None,
    comparator: Optional[ProposalComparator[CallT, ProposalT]] = None,
    recovery_provider: Optional[RecoveryProvider[CallT]] = None,
    use_reasoning_track: bool = True,
) -> ExecutiveLoopManager[StateT, SymbolicStateT, CallT, TaskT, ProposalT]:
    """Assemble one executive loop for `package`'s named (or default) task.

    Positional parameters mirror `build_loop` so a call site migrates by swapping the
    first argument; each keyword overrides one component. `loop_class` admits the
    established fault-injection seam of subclassing the loop.
    """
    task = package.task(task_name)
    env = environment if environment is not None else package.environment()
    services = domain if domain is not None else package.services(task)
    track = symbolic_track if symbolic_track is not None else package.symbolic_track()

    advisory: Optional[ReasoningTrack[StateT, TaskT, ProposalT]] = nl_track
    if advisory is None and use_reasoning_track and package.reasoning_track is not None:
        advisory = package.reasoning_track()
    compared = comparator
    if compared is None and package.comparator is not None:
        compared = package.comparator()
    recovery = recovery_provider if recovery_provider is not None else package.recovery_provider

    return loop_class(
        env, task, config, advisory, provenance, policy,
        domain=services,
        symbolic_track=track,
        comparator=compared,
        recovery_provider=recovery,
    )


__all__ = ["assemble_loop"]
