---
name: implementation-doc
description: Generate the supervisor-facing P0-P4 implementation document from actual repository code, tests, schemas, traces, and Section 18 evidence.
argument-hint: "[optional: refresh]"
disable-model-invocation: true
---

# Generate P0-P4 Implementation Documentation

Generate or refresh:

`docs/implementation/P0_P4_IMPLEMENTATION.md`

Ground every implementation claim in current code/tests. Do not write from memory or intended design alone.

Include:

1. scope and V1 assumptions
2. repository/branch/commit and run/test commands
3. architecture and runtime information flow
4. shared typed contracts
5. canonical `StateSnapshot` and normalization
6. executive skill registry and backend mappings
7. per-skill symbolic preconditions/effects/costs
8. per-skill success/failure labels
9. failure state and executive-step semantics
10. environment wrapper/executor
11. symbolic IR, planner, predictor, monitor
12. NL/DSPy typed modules and offline-test strategy
13. translator and track comparator
14. orchestrator policies and executive loop
15. `PlanFound` / `NoPlan` / `PlannerFailure`
16. `ExecutionDiscrepancy` / `TrackDivergence` / `InfrastructureFault`
17. representative state-by-state acceptance traces
18. test matrix and commands
19. known V1 limitations and intentionally optimistic abstraction
20. file/class/function index
21. explicitly deferred P5+ work

Where low-level behavior is clear in code, point to the file/function rather than restating algorithms.

Run `architecture-reviewer` on the finished document to catch claims that exceed the implementation.
