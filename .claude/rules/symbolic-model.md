---
paths:
  - "symbolic/**/*"
  - "domain/**/*"
  - "shared/planner_result.py"
  - "shared/state_snapshot.py"
  - "shared/symbolic_state.py"
  - "tests/**/*symbolic*"
  - "tests/**/*planner*"
---

# Symbolic Model Rules

The current BoxPush V1 symbolic semantics are frozen regression behavior during
R0-R6 unless the supervisor explicitly changes them.

The symbolic model is a deliberately optimistic high-level classical
abstraction, not a duplicate backend simulator.

## No hidden feasibility oracle

Never call or indirectly rely on:

- backend BFS/pathfinding;
- backend reachability/navigation feasibility;
- procedural collision search;
- hidden environment rollouts;
- task-specific execution helpers;

from symbolic applicability or classical planning unless that information is
explicitly represented in the frozen symbolic IR.

A skill can be symbolically applicable and fail in the backend. That is
expected V1 behavior and must remain observable.

## Structured IR

Keep typed skill signatures, declarative preconditions/dependencies,
deterministic success effects for the V1 baseline, frame semantics,
observation metadata, cost/provenance/version information as established by the
current implementation.

Do not replace the typed structured model with unrestricted generated code or a
dictionary-only universal model.

## Planner contract

Preserve the typed distinction:

- `PlanFound(plan)`
- `NoPlan(reason)`
- `PlannerFailure(error_or_timeout)`

`NoPlan` is a semantic result. `PlannerFailure` follows the established
infrastructure-fault path.

## Predictor / monitor boundary

The predictor computes model-relative expected evidence. The monitor compares
that prediction with normalized authoritative execution.

Do not mutate symbolic applicability merely to hide a prediction/execution
mismatch.

R0-R6 architecture extraction must preserve these semantics.
