"""BoxPush V1 as a `DomainPackage` (DK1) — a thin declaration over the FROZEN modules.

Nothing BoxPush moved: the model stays in `domain/box_push_v1.py`, the machinery in
`symbolic/` and `nl/`, the services and the comparator in `app/`. Every factory here
DELEGATES to `app.box_push_v1.compose(task)`, the accepted V1 composition, so this
declaration cannot drift from `build_loop` (the DK1 test pins that a loop assembled from
`DOMAIN` reproduces both baseline transcripts cycle by cycle at the R0 granularity).

`reasoning_track` is None: the only live NL seam sits under `functional_layer/`, which a
composition module may not import — so a loop assembled from this package is offline by
construction (the runner's opt-in `--nl live` path is unchanged and separate).
"""
from __future__ import annotations

from app.box_push_v1 import (
    V1Comparator,
    V1DomainServices,
    V1RecoveryProvider,
    V1SymbolicTrack,
    compose,
)
from app.domain_package import DomainExamples, DomainPackage
from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    DELIVERY_ZONE,
    TASK_DELIVER_BOTH,
    TASKS,
)
from nl.track import NLProposal
from shared.ids import AgentId, BoxId
from shared.skills import GroundedSkillCall, SkillName
from shared.state_snapshot import StateSnapshot
from shared.symbolic_state import SymbolicState
from shared.task import Task

from domains.box_push.environment import make_environment


def _services(task: Task) -> V1DomainServices:
    return compose(task).domain


def _symbolic_track() -> V1SymbolicTrack:
    return compose(TASK_DELIVER_BOTH).symbolic_track


def _comparator() -> V1Comparator:
    return compose(TASK_DELIVER_BOTH).comparator


_RECOVERY: V1RecoveryProvider = compose(TASK_DELIVER_BOTH).recovery_provider

#: Negative examples for validation (DK3): a ghost agent, and a CooperativePush before any
#: pose is established (its `in_pose` preconditions are unsatisfied in the initial symbolic
#: state, while both agents, the heavy box and the zone are grounded).
EXAMPLES = DomainExamples[GroundedSkillCall](
    ungrounded_call=GroundedSkillCall(
        SkillName.PUSH, (AgentId("agent_9"),), BoxId(1), DELIVERY_ZONE
    ),
    inapplicable_call=GroundedSkillCall(
        SkillName.COOPERATIVE_PUSH, (AGENT_0, AGENT_1), BOX_HEAVY, DELIVERY_ZONE
    ),
)

DOMAIN = DomainPackage[StateSnapshot, SymbolicState, GroundedSkillCall, Task, NLProposal](
    name="box_push",
    tasks={t.task_id: t for t in TASKS},
    default_task=TASK_DELIVER_BOTH.task_id,
    environment=make_environment,
    services=_services,
    symbolic_track=_symbolic_track,
    recovery_provider=_RECOVERY,
    comparator=_comparator,
    reasoning_track=None,
    examples=EXAMPLES,
)

__all__ = ["DOMAIN", "EXAMPLES"]
