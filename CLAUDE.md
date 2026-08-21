# MAAOS — Claude Code Project Instructions

## Current objective

Implement the supervisor's **Symbolic-Twin BoxPush V1** architecture.

**Current scope is P0-P4 only.** Do not implement P5-P9 unless the user explicitly asks.

The original specification is stored at:
`docs/supervisor/Symbolic_Twin_BoxPush_Implementation_Plan_Self_Contained_v5.docx`

The working P0-P4 extraction is:
`docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`

Section 18 handoff evidence is maintained in:
`docs/handoff/section18.md`

## Authority and source of truth

1. Existing BoxPush environment/backend code is authoritative for **actual low-level execution behavior**.
2. The supervisor specification is authoritative for the **executive architecture and V1 semantics**.
3. `docs/handoff/section18.md` is the semantic contract mapping the existing code to that architecture.
4. Never invent domain behavior when the code or specification does not establish it. Mark it unresolved.

## Current repository baseline

The active BoxPush/skill work is on the `middleware_layer` branch. The existing repository uses:

- `functional_layer/` — PettingZoo/custom environments
- `middleware_layer/` — observation/belief processing
- `model_layer/` — DSPy/LLM planning
- `utils/` — logging/support

The current architecture is a useful baseline, not the target P0-P4 architecture.

### Current BoxPush entry point

Run from its own directory because the repository currently uses bare imports/path insertion:

```bash
cd functional_layer/custom_env/box_push/env
python box_push_centralized.py
```

Do not perform a broad package/import refactor while implementing P0-P4 unless it is necessary and separately justified.

## Required V1 architecture

Keep these responsibilities conceptually separate even if small adapters share files initially:

- environment/backend wrapper
- executor
- symbolic track
- NL track
- translator
- symbolic predictor
- monitor
- track comparator
- track orchestrator
- executive loop manager
- guards
- trace/history/model versioning contracts

The orchestrator decides between tracks. The executor is policy-independent.

## Critical V1 rule: intentionally optimistic symbolic model

The symbolic model is deliberately a simple high-level classical abstraction.

**Never add backend BFS, reachability, pathfinding, collision feasibility, or another procedural environment oracle to symbolic applicability/planning merely to make plans executable.**

A grounded skill may be symbolically applicable and still fail in the authoritative backend. That must be observable as an `ExecutionDiscrepancy`, especially `ExecutionFailure`, and routed through the orchestrator.

Do not silently strengthen the symbolic model after such a failure.

## Executive skill abstraction

The executive operates on **high-level grounded skills**.

Primitive actions may be composed internally by a backend skill implementation. Do not expose primitive turns/moves as executive planning actions unless the frozen V1 domain explicitly defines them as executive skills.

For every executive skill, establish:

- stable name
- typed arguments
- backend implementation mapping
- symbolic preconditions
- deterministic success effects
- success/failure labels
- true backend feasibility differences
- failure state semantics
- executive-step consumption semantics

## Failure semantics

Never assume a failed skill is a no-op.

For every important failure mode determine whether the backend:

1. leaves world state unchanged,
2. partially executes and returns with changed state, or
3. rejects before any transition.

Also record whether the failed **executive skill attempt** consumes an executive step.

Distinguish:

- `primitive_step`: one low-level environment transition/action cycle
- `executive_step`: one attempted high-level grounded skill at an executive decision boundary

Do not infer one from the other without an explicit contract.

## V1 assumptions

For P0-P4 use:

- deterministic dynamics at the symbolic level
- fully observable exact symbolic state
- canonical typed `StateSnapshot`
- no probabilistic belief requirement
- no asynchronous skill overlap
- deterministic sequential executive decisions
- text/typed NL input only
- no VLM/rendered-image input
- skill cost 1 unless the domain contract says otherwise

Keep existing partial-observation/POMDP code for later work; use an adapter/mode for classical V1 rather than deleting it.

## Required typed distinctions

Never conflate:

- `PlanFound(plan)`
- `NoPlan(reason)`
- `PlannerFailure(error_or_timeout)`

Never conflate:

- `ExecutionDiscrepancy` — symbolic prediction/model vs authoritative execution
- `TrackDivergence` — NL track vs symbolic track disagreement/coverage/translation issue
- `InfrastructureFault` — API/backend/serialization/protocol/runtime fault

A current `InfrastructureFault` short-circuits the normal current cycle. `PlannerFailure` becomes `InfrastructureFault`; `NoPlan` is a legitimate symbolic result for the orchestrator.

## Change policy

Before changing existing environment behavior:

1. inspect and document the current behavior;
2. identify the precise architectural mismatch;
3. prefer a wrapper/adapter;
4. preserve backend execution semantics where possible;
5. change backend semantics only when explicitly necessary.

Do not modify code simply to make a symbolic test pass if the test is exposing a legitimate execution discrepancy.

## NL/DSPy policy

The V1 NL track is a peer reasoning track, not the sole executive planner.

Prefer small typed modules over one monolithic prompt. Default P0-P4 tests must not require a live LM. Provide deterministic stub/recorded responses; live calls belong in separately marked integration tests.

Malformed NL skill calls must be typed validation/repair/rejection cases. Do not silently convert malformed output into an unrelated valid skill such as `explore`.

## Documentation and evidence

When claiming a requirement is satisfied, point to exact files/classes/functions/tests.

Do not document intended behavior as implemented behavior.

Keep `docs/handoff/section18.md` and the final implementation document synchronized with actual code.

## Testing

Every P0-P4 architectural addition requires tests.

Required acceptance coverage includes:

- normal successful execution
- symbolically applicable but backend-infeasible skill
- symbolically inapplicable call
- malformed call
- `NoPlan` case when available
- explicit failure state and executive-step-consumption evidence

Use `/handoff-audit`, `/implement-phase`, `/consistency-check`, `/acceptance-test`, and `/final-audit` as the primary project workflows.
