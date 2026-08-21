---
name: acceptance-test
description: Create or run supervisor-style V1 acceptance traces that expose success, optimistic symbolic failure, invalid calls, malformed calls, NoPlan, and exact step/state semantics.
argument-hint: "[optional: create|run|review]"
disable-model-invocation: true
---

# V1 Acceptance Tests

Use the frozen domain and actual backend semantics. Prefer automated tests plus short human-readable traces.

Cover at minimum:

1. normal successful plan/execution;
2. well-formed and symbolically applicable skill that the authoritative backend rejects because of richer feasibility;
3. explicitly symbolically inapplicable call rejected before executor invocation;
4. malformed/invalid grounded call handled by validation/repair/fault contract;
5. `NoPlan` symbolic case if the frozen abstraction has one;
6. deadlock/unsolvable case if the backend/domain has one.

For every executed case record:

- task
- pre-attempt canonical `StateSnapshot`
- grounded executive skill
- symbolic applicability result
- symbolic predicted result/state
- backend terminal label
- post-attempt canonical `StateSnapshot`
- failure classification: unchanged / partial / rejected-before-transition
- primitive step count if available
- whether the executive attempt consumed one executive step
- `ExecutionDiscrepancy`, `TrackDivergence`, or `InfrastructureFault` as applicable
- orchestrator decision/recovery when P4 exists

Critical assertion: the optimistic execution-failure test must pass **without** adding a hidden reachability/feasibility oracle to the symbolic planner.

Use `test-reviewer` after creating/updating tests.
