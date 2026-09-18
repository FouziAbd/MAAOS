"""The domain declaration record (DK1 — `docs/decisions/DK1_DOMAIN_PACKAGE.md`).

A `DomainPackage` is the ONE object a domain exports: it names the domain's tasks and holds
factories for every component the generic runtime is injected with. It is a record, not a
registry and not a framework — explicit Python composition exactly as `app/box_push_v1.py`
performs it, written down once so that `app.assembly.assemble_loop` (and, later, the
validator and the CLI) can build a loop for ANY domain without the caller knowing the
loop's constructor.

The supervisor report calls this the application-level composition object ("a
`DomainBundle` or equivalent", report Phase 4 item 1). The runtime never consumes it, which
is why it lives in `app/` and not in `shared/contracts`. It imports only `shared`.

Field by field (generic in the five domain-owned types the loop is generic in):

    name              a Python identifier; the key an author registers in `domains/registry.py`
    tasks             the named tasks of the domain (`TaskContract` values), at least one
    default_task      which one `assemble_loop` / validation use when none is named
    environment       factory for the authoritative environment (`shared.contracts.Environment`).
                      A factory, never an instance: the environment is constructed at
                      assembly time, by the composition layer, exactly as the runner does.
    services          factory `task -> DomainServices` (plan / ground / evaluate / predict / monitor)
    symbolic_track    factory for the belief-holding `SymbolicTrack` (fresh per loop)
    recovery_provider optional `RecoveryProvider` value (a plain callable); None = no advice
    comparator        optional factory for the `ProposalComparator`; REQUIRED when a
                      reasoning track is declared (the loop refuses a track without one)
    reasoning_track   optional factory for an advisory `ReasoningTrack`
    examples          optional `DomainExamples` enabling the negative validation checks

Every factory is called by the composition layer only; the environment is never passed to a
domain factory (a domain's services must not be able to close over the backend).
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Optional

from shared.contracts import (
    AdvisoryProposal,
    DomainServices,
    Environment,
    ProposalComparator,
    ReasoningTrack,
    RecoveryProvider,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
)
from shared.execution import ExecutionResult
from shared.skills import MalformedCall, UngroundedCall


@dataclass(frozen=True, slots=True)
class DomainExamples[CallT: RuntimeCall]:
    """Optional author-supplied example calls for the negative validation checks: a call
    naming an identity the initial state lacks, and a call that is symbolically inapplicable
    in the initial symbolic state. Absent examples make those checks SKIPPED, never PASS."""
    ungrounded_call: Optional[CallT] = None
    inapplicable_call: Optional[CallT] = None


#: The typed outcome union an environment returns (the same union `runtime.executor`
#: names as `ExecutionAttempt`, spelled from `shared` so this module stays runtime-free).
type EnvironmentOutcome[StateT: RuntimeState, CallT: RuntimeCall] = (
    ExecutionResult[StateT, CallT] | MalformedCall | UngroundedCall[CallT]
)


@dataclass(frozen=True, slots=True)
class DomainPackage[
    StateT: RuntimeState,
    SymbolicStateT,
    CallT: RuntimeCall,
    TaskT: TaskContract,
    ProposalT: AdvisoryProposal,
]:
    """One domain, declared: its tasks and the factories for its injected components."""
    name: str
    tasks: Mapping[str, TaskT]
    default_task: str
    environment: Callable[[], Environment[StateT, CallT, EnvironmentOutcome[StateT, CallT], object]]
    services: Callable[[TaskT], DomainServices[StateT, SymbolicStateT, CallT]]
    symbolic_track: Callable[[], SymbolicTrack[StateT, SymbolicStateT]]
    recovery_provider: Optional[RecoveryProvider[CallT]] = None
    comparator: Optional[Callable[[], ProposalComparator[CallT, ProposalT]]] = None
    reasoning_track: Optional[Callable[[], ReasoningTrack[StateT, TaskT, ProposalT]]] = None
    examples: Optional[DomainExamples[CallT]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.isidentifier():
            raise ValueError(
                f"DomainPackage.name must be a Python identifier (got {self.name!r}); it is "
                f"the key you register in domains/registry.py"
            )
        if not self.tasks:
            raise ValueError(f"DomainPackage {self.name!r}: declare at least one task in `tasks`")
        object.__setattr__(self, "tasks", MappingProxyType(dict(self.tasks)))
        if self.default_task not in self.tasks:
            raise ValueError(
                f"DomainPackage {self.name!r}: default_task {self.default_task!r} is not one of "
                f"the declared tasks {sorted(self.tasks)}"
            )
        if self.reasoning_track is not None and self.comparator is None:
            raise ValueError(
                f"DomainPackage {self.name!r}: a reasoning_track requires a comparator — the "
                f"loop refuses an advisory track whose proposals cannot be compared"
            )

    def task(self, task_name: Optional[str] = None) -> TaskT:
        """The named task, or the default one; a wrong name is an author-facing error."""
        key = self.default_task if task_name is None else task_name
        try:
            return self.tasks[key]
        except KeyError:
            raise ValueError(
                f"DomainPackage {self.name!r} has no task {key!r}; declared tasks: "
                f"{sorted(self.tasks)}"
            ) from None


__all__ = ["DomainExamples", "DomainPackage", "EnvironmentOutcome"]
