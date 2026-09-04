---
paths:
  - "runtime/**/*"
  - "shared/**/*"
  - "domain/**/*"
  - "symbolic/**/*"
  - "nl/**/*"
  - "functional_layer/custom_env/box_push/env/box_push_v1_*.py"
  - "tests/**/*"
---

# R0-R6 Refactor Architecture Rules

The current architectural program is the behavior-preserving R0-R6 refactor.

## Phase discipline

Treat the supervisor report as a phased migration.

A final-architecture requirement is not automatically a requirement to change
the code in the current phase.

- R0 protects/characterizes the baseline.
- R1 introduces narrow typed contracts without changing behavior.
- R2 extracts orchestration policies.
- R3 corrects the proposal-comparison lifecycle and scopes BoxPush action
  comparison.
- R4 makes domain composition explicit and removes BoxPush/concrete-track
  imports from the generic runtime.
- R5 proves substitutability with a test-only non-BoxPush probe.
- R6 performs correctness/repository hygiene.

Do not implement later-phase work early merely because a target invariant is
visible.

## Final architectural direction

By completion of the responsible phase:

- variable components use narrow typed Protocol contracts;
- state/action/execution types remain domain-owned and typed;
- `ExecutiveLoopManager` receives implementations through constructor
  injection;
- policies are strategy objects and cannot execute the backend;
- comparators produce evidence and cannot choose/execute actions;
- recovery is behind its own provider contract;
- BoxPush equivalence rules stay in BoxPush/domain-owned components;
- the runtime core does not interpret agents, boxes, zones, or geometry;
- R4 removes direct BoxPush/concrete symbolic/concrete NL imports from the core
  runtime;
- R3 ensures requested two-track comparison evidence exists before the final
  policy decision;
- R5 proves the same runtime can execute a non-BoxPush test fixture without
  special cases.

## Generality limits

Do not use `Any` or dictionary-shaped state/action APIs as the primary
abstraction mechanism.

Do not introduce dynamic plugin discovery, asynchronous track execution, a
configuration language, probabilistic semantics, belief reconciliation, or
other speculative frameworks unless explicitly required by a real domain.

Prefer explicit Python composition at the application boundary.

## Compatibility

Preserve existing public imports, CLI behavior, and trace serialization where
practical. When an internal type changes, prefer a compatibility adapter over
an unrelated external-format change.

If clean boundaries materially require breaking an existing public contract,
stop and surface the conflict before proceeding.
