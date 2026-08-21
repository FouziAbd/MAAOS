---
paths:
  - "orchestration/**/*"
  - "monitoring/**/*"
  - "runtime/**/*"
  - "shared/trace_schema.py"
  - "shared/**/*fault*"
  - "shared/**/*divergence*"
---

# Orchestration, Monitoring, and Runtime Rules

Keep the **track orchestrator** separate in responsibility from the **executive loop manager**.

The orchestrator combines proposals/evidence and returns an executive decision. It does not directly call the backend or advance time.

The executive loop owns runtime progression, current-cycle fault short-circuiting, step budget, repeated-failure bookkeeping, state synchronization, and trace/history updates.

## Three distinct report channels

### ExecutionDiscrepancy
Model/prediction versus authoritative execution, including:

- unexpected outcome
- state effect mismatch
- duration anomaly later
- execution failure of a symbolically applicable skill

### TrackDivergence
NL/VLM versus symbolic track disagreement/representation issues, including:

- contradiction
- coverage gap
- translation residual
- confidence mismatch
- benign abstraction mismatch

### InfrastructureFault
Interface/runtime failures such as:

- malformed backend result
- serialization failure
- backend/API exception
- missing grounding
- executor/monitor protocol failure
- `PlannerFailure`

A newly raised `InfrastructureFault` short-circuits the normal current cycle. Do not pass it as a third competing current-cycle track proposal. Log it and expose recent fault history on the following cycle after state re-synchronization as needed.

## Repeated failures

Key repeated failed grounded skills by canonical pre-attempt `StateSnapshot` plus grounded skill call. Do not turn this bookkeeping into a hidden symbolic feasibility predicate.
