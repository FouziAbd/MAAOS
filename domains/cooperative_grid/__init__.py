"""Domain `cooperative_grid` — the declaration (COMPOSITION role).

Two agents, one heavy door, one goal room. The door opens only when both agents pull it
together from the two handle cells; then both walk into the goal room. The designed hidden
condition: the door starts JAMMED. The symbolic model does not know jams exist, so it plans
`CooperateOpen` as soon as both handles are held; the backend refuses the pull, the runtime
reports an ExecutionDiscrepancy, and (under advisory_two_track) the recovery advice below
shakes the jam loose so the next `CooperateOpen` succeeds.

This is the one module of the package that may import `app` and the sibling `environment`.
"""
from __future__ import annotations

from app.domain_package import DomainExamples, DomainPackage
from kit import DefaultProposalComparator, DerivedDomainServices, ProjectionTrack
from shared.contracts import AdvisoryProposal
from shared.discrepancy import ExecutionDiscrepancy

from .environment import make_environment
from .model import MODEL, SymbolicState
from .types import DOOR, GOAL, Call, Op, State, Task

# ── tasks ─────────────────────────────────────────────────────────────────────────────
TASKS = {
    "reach_goal": Task(task_id="reach_goal",
                       description="Open the heavy door together, then both reach the goal room."),
}

# ── examples for validate-domain ──────────────────────────────────────────────────────
EXAMPLES = DomainExamples(
    ungrounded_call=Call(Op.GOTO, "C", GOAL),                      # there is no agent C
    inapplicable_call=Call(Op.COOPERATE_OPEN, "A", DOOR, partner="B"),   # nobody holds a handle
)


# ── recovery advice ───────────────────────────────────────────────────────────────────
def recover(discrepancy: ExecutionDiscrepancy[Call]) -> tuple[Call, ...]:
    """After `CooperateOpen` has failed repeatedly, advise the pulling agent to shake the door
    (`ClearJam`) — a call with no symbolic effect that the planner never picks on its own.
    It is ADVICE: it passes the same grounding/applicability gates and the same executor as
    any call, and the planner runs again afterwards (retrying `CooperateOpen`). The
    environment's hidden reason is not visible here; only the failed call is."""
    failed = discrepancy.call
    if failed.op is Op.COOPERATE_OPEN:
        return (Call(Op.CLEAR_JAM, failed.agent, failed.target),)
    return ()


DOMAIN: DomainPackage[State, SymbolicState, Call, Task, AdvisoryProposal] = DomainPackage(
    name="cooperative_grid",
    tasks=TASKS,
    default_task="reach_goal",
    environment=make_environment,
    services=lambda task: DerivedDomainServices(MODEL),
    symbolic_track=lambda: ProjectionTrack(MODEL.project),
    recovery_provider=recover,
    comparator=lambda: DefaultProposalComparator[Call, AdvisoryProposal](),
    reasoning_track=None,
    examples=EXAMPLES,
)

__all__ = ["DOMAIN", "EXAMPLES", "TASKS", "recover"]
