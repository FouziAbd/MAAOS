---
paths:
  - "functional_layer/custom_env/box_push/**/*"
  - "functional_layer/custom_env/shared_skills.py"
  - "environment/**/*"
  - "shared/state_snapshot.py"
---

# Environment and Backend Rules

Existing BoxPush code is the source of truth for realized execution.

Prefer introducing a V1 wrapper/adapter with a contract equivalent to:

- `reset()`
- `observe()`
- `execute_skill(call)`
- `export_full_state()`
- `is_terminal()`
- optional `render()`

Do not duplicate/reimplement backend behavior when an existing function/class already defines it.

## High-level skills

The executive sees grounded high-level skills and terminal execution results. A skill may internally execute multiple primitive actions.

For every skill wrapper preserve and expose:

- grounded typed arguments
- terminal label
- state before/after
- primitive step count if useful
- executive attempt semantics
- raw/public observation
- debug/full-state data separately

## Failure

Never normalize all failure into an unchanged state without evidence.

A multi-step skill may move/turn/push before later failing. Preserve the true post-failure state and label it as partial execution when appropriate.

Do not use backend BFS/pathfinding as a symbolic precondition. Backend pathfinding belongs behind execution.

## StateSnapshot

Backend state must be normalized into a typed canonical `StateSnapshot` at the wrapper boundary.

Use normalized structural equality for predicted-vs-observed comparisons. Raw backend serialization is not the equality criterion.
