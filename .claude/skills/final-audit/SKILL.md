---
name: final-audit
description: Perform a hostile requirement-by-requirement P0-P4 audit against the supervisor specification, with independent backend, architecture, and test review.
argument-hint: "report|fix"
disable-model-invocation: true
---

# Hostile Final P0-P4 Audit

Mode: `$ARGUMENTS` (default to `report` if omitted).

Assume the implementation may be wrong. Do not give credit based on filenames or intended architecture.

Use independent reviews from:

- `backend-investigator`
- `architecture-reviewer`
- `test-reviewer`

Audit every P0-P4 milestone deliverable, Section 18 item, and V1 regression requirement.

For each requirement return:

- `PASS`, `PARTIAL`, or `FAIL`
- exact implementation evidence
- exact test evidence
- reason
- smallest correction if needed

Explicitly search for:

- primitive actions leaking into executive planning vocabulary
- symbolic code calling backend feasibility/BFS/reachability
- failure states incorrectly assumed unchanged
- primitive and executive step counters being conflated
- monolithic NL planner still acting as sole authority
- live-LM dependency in default tests
- `NoPlan` and `PlannerFailure` conflation
- discrepancy/divergence/fault conflation
- `InfrastructureFault` failing to short-circuit current cycle
- policy logic inside executor
- documentation claiming unimplemented P5+ features

In `report` mode, do not change code.

In `fix` mode, fix only verified P0-P4 violations, run affected tests after each logical correction, then rerun the audit. Do not expand scope.

Finish by refreshing `docs/implementation/P0_P4_IMPLEMENTATION.md` only after the audit is green enough to support its claims.
