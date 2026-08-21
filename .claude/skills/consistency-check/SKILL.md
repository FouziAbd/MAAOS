---
name: consistency-check
description: Cross-check P0-P4 schemas, skill vocabulary, backend behavior, symbolic model, NL interfaces, orchestration, traces, docs, and tests for semantic drift.
argument-hint: "[optional: P0|P1|P2|P3|P4|all]"
disable-model-invocation: true
---

# P0-P4 Consistency Check

Perform a read-first consistency audit. Do not silently fix issues while discovering them.

Compare the same concepts across:

- domain/skill/object/state/observation/execution-label schemas
- canonical `StateSnapshot`
- backend wrappers and existing BoxPush skills
- symbolic IR / classical projection / planner / predictor
- NL typed signatures and parsers
- executor and monitor
- track comparator/orchestrator/executive loop
- traces/history
- tests
- handoff and implementation documentation

Check at minimum:

- identical skill names and typed argument meanings
- actual backend return labels vs declared labels
- symbolic success effects vs observed successful successor state
- no hidden feasibility oracle in symbolic applicability
- exact distinction of primitive vs executive step
- consistent object identifiers and coordinate conventions
- all failure-state semantics documented and tested
- `PlanFound` / `NoPlan` / `PlannerFailure` routing
- `ExecutionDiscrepancy` / `TrackDivergence` / `InfrastructureFault` routing
- deterministic/offline NL tests
- V1 fully-observable symbolic state path
- no accidental P5+ dependency in P0-P4

Ask `architecture-reviewer` to perform an independent pass on high-risk findings.

Output a table of `PASS / WARN / FAIL`, evidence, and minimum correction. If the user explicitly asked to fix, apply only verified fixes and rerun relevant tests; otherwise report only.
