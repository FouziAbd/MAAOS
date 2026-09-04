---
paths:
  - "functional_layer/custom_env/box_push/env/**/*"
  - "shared/backend_contract.py"
  - "shared/state_snapshot.py"
  - "shared/symbolic_state.py"
  - "tests/**/*adapter*"
  - "tests/**/*backend*"
---

# Environment and Backend Rules

The existing BoxPush backend/environment is the source of truth for realized
physical execution behavior.

R0-R6 is primarily an architectural refactor around that behavior.

Do not duplicate or reimplement backend behavior when the existing code already
defines it.

## Executive boundary

The executive sees grounded high-level skills/actions and typed terminal
execution evidence. A skill may internally execute multiple primitive actions.

Preserve:

- grounded arguments;
- terminal/success/failure labels;
- true pre/post state;
- primitive-step information when tracked;
- executive-attempt semantics;
- raw/public observation vs debug/full-state distinctions.

Never normalize all failures into unchanged state. A multi-step skill may
partially execute before failure.

Backend feasibility/pathfinding remains behind execution and must not become a
symbolic applicability oracle.

## R6-specific correctness work

Observation immutability/defensive-copy changes and malformed-backend-return
normalization belong to R6 unless an earlier assigned phase requires a minimal
adapter for compatibility.

Do not change these semantics early just to satisfy the final R6 target.

When R6 is assigned:

- returned observations must not alias authoritative mutable backend state;
- unexpected backend return values must enter the established typed fault
  channel instead of leaking raw attribute/type exceptions.

Preserve the established step-consumption semantics while making those
boundaries safer.
