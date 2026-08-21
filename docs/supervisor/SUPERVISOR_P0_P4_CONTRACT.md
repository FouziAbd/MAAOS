# Supervisor Symbolic-Twin BoxPush — Working P0-P4 Contract

> Working extraction for Claude Code. The original supervisor document in this directory remains authoritative if this summary is incomplete or conflicts with it.

## Goal of V1

Build a runnable end-to-end **deterministic, fully observable, classical grid-world** version before adding stochastic outcomes, partial observability, temporal duration, asynchronous concurrency, Julia MDP/POMDP solving, or learned DBN structure.

The V1 interfaces must already preserve the future architecture: shared skill registry, separate NL and symbolic tracks, translator, orchestrator, executor, monitor, trace/history, model versions, and structured model IR.

## Core architecture

### NL/VLM track

Maintains semantic/open-world belief, interprets tasks and observations, and may propose skills, explanations, ambiguity reports, recovery ideas, or provisional symbolic changes.

For V1 this is **NL/text/typed data only**. Rendered images and VLM input are out of scope.

### Symbolic track

Maintains formal state/model and performs planning, symbolic applicability, transition prediction, monitor support, model-relative explanation, and later learning.

### Translator

Maps between NL and symbolic vocabulary and returns both a translated artifact and an explicit residual for unsupported/ambiguous/lossy information.

### Track orchestrator

Combines the two reasoning tracks under a configured policy. It chooses executive consequences such as execute/start, continue, interrupt, replan/request proposal, ask user, update task, or halt.

It does not directly call the environment or advance time.

### Executive loop manager

Owns the runtime cycle, including decision context, proposals, orchestration, validation, execution, observations, monitoring, belief/state updates, traces/history, episode step budget, repeated-failure bookkeeping, and current-cycle `InfrastructureFault` control flow.

### Executor

Calls the selected grounded high-level skill in the backend and returns execution feedback/status. It is policy-independent.

### Monitor

Compares symbolic prediction with authoritative execution and emits typed `ExecutionDiscrepancy` when they differ.

### Track comparator

Compares NL and symbolic beliefs/proposals/translations and emits typed `TrackDivergence`. It does **not** classify environment-vs-model prediction errors.

## Critical V1 abstraction rule

The symbolic model is intentionally simple and may be optimistic.

A high-level skill such as `Navigate(target)` may be symbolically applicable even when the richer backend cannot actually reach the target.

**Do not add a hidden reachability/feasibility oracle to the symbolic planner.**

When a symbolically applicable skill fails in the authoritative backend, the monitor reports an execution discrepancy and the orchestrator decides the executive response.

This limitation is intentional and is expected to become richer in later probabilistic/learned milestones.

## Shared artifacts P0 must freeze

The project needs stable typed schemas/contracts equivalent to:

- skill registry (`skills.yaml` or typed equivalent)
- objects/types
- state schema
- observations
- execution labels
- trace schema
- orchestration configuration
- structured probabilistic/symbolic model IR, used deterministically in V1
- canonical typed `StateSnapshot`
- `PlannerResult`
- `CoverageReport`
- `ConfidenceReport`
- typed `ExecutionDiscrepancy`
- typed `TrackDivergence`
- typed `InfrastructureFault`
- model patch/version/provenance support sufficient for the interfaces

Names used by prompts, backend wrappers, symbolic variables, traces, and tests should come from these contracts rather than ad hoc strings.

## Canonical StateSnapshot

The environment wrapper converts backend state into a normalized typed `StateSnapshot`.

Predicted and observed states are compared structurally in this form. Deterministic normalization/serialization is used for equality/hashing/replay/trace keys. Raw backend serialization is not the equality criterion.

## Executive skills

Each skill must have:

- stable name/signature
- typed parameters
- acting agent/resource as applicable
- declarative symbolic preconditions/applicability
- explicit dependencies
- deterministic V1 success effects/outcome
- observations
- cost, default 1 unless specified
- provenance/version metadata
- success/failure labels at the execution interface
- mapping to backend implementation

The backend may implement one executive skill by multiple primitive movements/actions internally. The executive should see the high-level skill call and terminal result.

## Failure semantics

For each important backend failure, the domain contract must say whether execution:

1. leaves state unchanged/no-op,
2. partially executes and leaves changed state, or
3. rejects before any transition.

It must also say whether the failed high-level attempt consumes an executive step.

The executive loop owns the episode step budget and repeated `(pre-attempt StateSnapshot, grounded skill)` failure bookkeeping. This must not become a hidden symbolic feasibility predicate.

## Planner result contract

The classical planner returns exactly one typed result:

- `PlanFound(plan)`
- `NoPlan(reason)`
- `PlannerFailure(error_or_timeout)`

`NoPlan` is a legitimate symbolic-track result and is routed to the orchestrator.
`PlannerFailure` is a computation/infrastructure problem and becomes `InfrastructureFault`; it must never be treated as evidence that the task is symbolically unsolvable.

## Three distinct evidence/fault channels

### ExecutionDiscrepancy

Model/prediction versus actual execution, including:

- unexpected outcome
- state-effect mismatch
- execution failure of a symbolically applicable skill
- duration anomaly in later temporal versions

### TrackDivergence

NL/VLM versus symbolic track disagreement/representation issues, including:

- contradiction
- coverage gap
- translation residual
- confidence mismatch
- benign abstraction mismatch

### InfrastructureFault

Technical/interface/runtime fault, including:

- malformed backend result
- serialization failure
- backend/API exception
- missing grounding
- executor/monitor protocol failure
- planner computation failure

A newly raised `InfrastructureFault` aborts the normal current cycle at the point of detection. No further skill command is issued until synchronization as required. It is logged and may appear as recent fault history in the following cycle; it is not a third competing current-cycle reasoning proposal.

## V1 observation and multi-agent assumptions

- Symbolic state is exact/fully observable after wrapper normalization.
- Existing partial-observation behavior may remain in the backend for later milestones.
- V1 NL input is text/typed data only.
- No asynchronous skill overlap is required.
- If multiple agents exist, the domain must define deterministic sequential executive decision/execution behavior.
- A high-level joint skill may internally coordinate multiple agents while still presenting one executive skill lifecycle.

## P0 — Domain freeze

Goal: receive/freeze the precise V1 domain package and all shared typed contracts.

Deliverables include:

- validated object/state/observation/skill/execution/orchestration/report schemas
- canonical `StateSnapshot` and deterministic normalization/serialization contract
- deterministic structured skill IR schema
- `PlannerResult`, `CoverageReport`, `ConfidenceReport`
- representative task examples
- backend contract
- Section 18 semantic handoff

## P1 — Classical environment

Goal: implement or wrap the deterministic grid world and skill executor.

Deliverables include:

- reset/observe/execute/export-state behavior
- backend-state -> `StateSnapshot` normalization tests
- serialization round-trip tests
- deterministic skill transition tests
- exact failure-state semantics preserved

## P2 — Symbolic baseline

Goal: encode the classical symbolic model directly in the structured skill IR and implement:

- classical projection/applicability
- planner
- predictor
- monitor
- exact-state symbolic belief

Deliverables include:

- plans use the same executive skill vocabulary as the executor
- successful transitions match predictions
- backend rejection of an optimistic symbolic plan produces typed `ExecutionDiscrepancy`
- no hidden backend feasibility oracle

## P3 — DSPy/NL baseline

Goal: implement typed, testable NL modules with small responsibilities.

Relevant modules include:

- TaskInterpreter
- ObservationInterpreter
- SemanticBeliefUpdater
- SkillSelector
- RepairSkillCall
- Translator with residual
- RecoveryProposer
- ambiguity/model-hypothesis/monitor-obligation modules as needed by the selected V1 path

Runtime/test policy:

- pin DSPy/runtime dependency versions
- temperature 0 baseline
- response caching
- deterministic mock/recorded LM fixtures
- stub NL track
- default tests run offline
- live model calls only in separately marked integration tests

## P4 — Orchestrator + executive loop

Goal: implement:

- track comparator
- typed report channels
- symbolic-primary policy
- advisory/two-track policy
- executive loop manager
- explicit `NoPlan` vs `PlannerFailure` routing
- policy-independent executor
- current-cycle `InfrastructureFault` short-circuit
- repeated-failure bookkeeping
- executive step budget
- trace/history wiring

## Required V1 acceptance/regression scenarios

At minimum exercise:

1. normal success;
2. well-formed, symbolically applicable but backend-infeasible skill;
3. symbolically inapplicable call;
4. malformed call;
5. `NoPlan` case where the symbolic abstraction has one;
6. deadlock/unsolvable case if the domain defines one.

For failed skills record post-state behavior and executive-step consumption.

Successful deterministic backend transitions must match symbolic predicted normalized successor state. Optimistic execution failures are expected discrepancies, not reasons to add an oracle.

## Section 18 handoff checklist summary

The repository/domain owner must provide or point to:

- repository/archive access, branch/commit, install/run/test commands, Python/package/OS constraints
- executive skill vocabulary and mapping to backend implementation
- typed skill arguments, symbolic preconditions/effects, success/failure labels
- whether each skill is directly implemented or composed from primitives
- richer backend feasibility behavior absent from symbolic abstraction
- per-failure state behavior and executive-step consumption
- complete state representation, backend export, stable IDs, reset, terminal/deadlock, fluents/non-fluents and modifying skills
- V1 agent count and deterministic sequential rule
- observation contract: execution result/public observation/debug full state/symbolic visibility/NL visibility
- 3-5 representative task instances and state-by-state acceptance traces
- optional existing PDDL/domain model
- non-unit costs and hard prohibitions, otherwise cost 1
