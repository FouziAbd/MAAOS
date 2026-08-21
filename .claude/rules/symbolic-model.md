---
paths:
  - "symbolic/**/*"
  - "domain/**/*"
  - "model/**/*"
  - "shared/planner_result.py"
  - "shared/state_snapshot.py"
---

# Symbolic Model Rules

The symbolic model is a **high-level classical abstraction**, not a duplicate backend simulator.

## No hidden feasibility oracle

Never call or indirectly rely on:

- backend BFS/pathfinding
- backend `can_reach`/navigation feasibility
- procedural collision search
- hidden environment rollouts
- task-specific execution helpers

from symbolic applicability or the classical planner unless that information is explicitly represented as a symbolic state predicate/dependency in the frozen IR.

A skill can be symbolically applicable and fail in the backend. That is expected V1 behavior.

## Structured IR

Author the deterministic V1 model in the same structured skill IR intended for later probabilistic extension:

- typed skill signature
- declarative preconditions
- explicit dependencies
- one deterministic success outcome for the classical baseline where appropriate
- deterministic effects
- implicit frame conditions for unmentioned variables
- observations
- cost (default 1)
- provenance/version metadata

Do not use unrestricted generated Python/Julia as the authoritative model.

## Planner contract

Return exactly one typed result category:

- `PlanFound(plan)`
- `NoPlan(reason)`
- `PlannerFailure(error_or_timeout)`

`NoPlan` is a semantic planner result. `PlannerFailure` is an infrastructure/computation failure and must be converted to `InfrastructureFault` by the runtime path.

## Predictor and monitor boundary

The predictor computes the model-relative expected successor/event/observation.
The monitor compares prediction to normalized authoritative execution.
Do not mutate applicability to hide a prediction/execution mismatch.
