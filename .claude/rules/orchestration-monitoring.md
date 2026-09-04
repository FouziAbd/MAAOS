---
paths:
  - "runtime/**/*"
  - "shared/**/*fault*"
  - "shared/**/*divergence*"
  - "shared/**/*report*"
  - "shared/**/*trace*"
  - "tests/**/*orchestrat*"
  - "tests/**/*runtime*"
---

# Orchestration, Monitoring, and Runtime Rules

Keep policy, runtime progression, execution, monitoring, and evidence channels
separate.

## Permanent responsibilities

The policy/orchestrator decides. It does not directly call the backend or
advance physical time.

The executor/backend path performs validated physical execution and remains
policy-independent.

The loop owns runtime progression, synchronization, step budget,
current-cycle fault routing, failure history, and trace/history assembly.

Preserve the three distinct evidence channels:

- `ExecutionDiscrepancy`: symbolic prediction/model vs authoritative execution;
- `TrackDivergence`: NL vs symbolic proposal/representation evidence;
- `InfrastructureFault`: runtime/interface/backend/protocol failure.

Do not convert one channel into another merely to simplify control flow.

A newly raised current-cycle infrastructure fault follows the existing
fail-closed short-circuit behavior.

Repeated-failure bookkeeping must not become a hidden symbolic feasibility
predicate.

## Phase-owned changes

R2 owns extraction of policy strategies and policy input requirements.

R3 owns comparison-before-final-decision for policies that request both tracks.

R4 owns removal of BoxPush/concrete-track knowledge from the generic runtime and
application-level composition/injection.

Before those phases, known existing coupling is scheduled debt, not permission
to implement all later work early.

Policies must remain pure transformations of immutable context into typed
decisions. Illegal decision states should be unrepresentable once the assigned
phase introduces typed variants.
