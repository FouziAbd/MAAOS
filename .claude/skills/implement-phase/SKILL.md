---
name: implement-phase
description: Implement exactly one supervisor milestone P0, P1, P2, P3, or P4 using the frozen handoff contract and maximum reuse of the existing BoxPush backend.
argument-hint: "P0|P1|P2|P3|P4"
disable-model-invocation: true
---

# Implement One P0-P4 Phase

Target phase: `$ARGUMENTS`

Accept only `P0`, `P1`, `P2`, `P3`, or `P4`. Do not implement later phases in the same invocation.

Before editing:

1. Read the exact milestone in `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`.
2. Read `docs/handoff/section18.md`.
3. Inspect relevant existing code; use `backend-investigator` when behavior is unclear.
4. Check git status/branch and avoid overwriting unrelated user changes.
5. Define the smallest implementation that satisfies this phase and reuses existing BoxPush behavior.

## Phase boundaries

### P0 — Domain freeze

Freeze typed shared schemas, stable names, deterministic structured skill IR shape, `StateSnapshot` normalization/serialization, `PlannerResult`, `CoverageReport`, `ConfidenceReport`, task examples, backend contract, and documented skill/failure semantics. Resolve code-vs-doc vocabulary inconsistencies explicitly.

Do not build the environment wrapper/planner/orchestrator beyond what is needed to validate contracts.

### P1 — Classical environment

Wrap the deterministic BoxPush backend behind the V1 environment contract. Reuse existing high-level skill implementations. Add exact-state -> canonical `StateSnapshot` adaptation and deterministic transition/round-trip tests. Preserve partial-observation code for later. Distinguish primitive steps from executive attempts.

Do not implement symbolic planning.

### P2 — Symbolic baseline

Implement structured deterministic skill model, classical projection/applicability, planner, predictor, symbolic exact-state belief, and monitor.

**Never use backend BFS/reachability/procedural feasibility in symbolic applicability.**

The planner must return `PlanFound`, `NoPlan`, or `PlannerFailure`. Add an acceptance test where a symbolically applicable skill fails in the backend and produces `ExecutionDiscrepancy`.

### P3 — DSPy/NL baseline

Refactor/reuse existing DSPy work behind small typed modules. Add task/observation interpretation, semantic belief, typed skill proposal, repair, translator residuals, recovery, pinned deterministic runtime configuration, recorded/mock fixtures, and a stub NL track.

Default tests must run offline. V1 input is text/typed data only. Do not make the NL track the executor or sole symbolic planner.

### P4 — Orchestrator + loop

Implement track comparator, typed report channels, symbolic-primary and advisory/two-track policy, executive loop manager, explicit `NoPlan` vs `PlannerFailure` routing, current-cycle `InfrastructureFault` short-circuiting, repeated-failure bookkeeping, executive-step budget, trace/history wiring, and policy-independent executor behavior.

## Completion procedure

After implementation:

1. run the relevant unit/integration/acceptance tests;
2. use `test-reviewer` to challenge the tests;
3. use `architecture-reviewer` to search for architectural violations;
4. run `/consistency-check $ARGUMENTS` or perform the equivalent checks;
5. update `docs/handoff/section18.md` status/evidence where this phase resolves items;
6. summarize changed files, tests, remaining gaps, and intentionally deferred items.

Do not claim the phase complete if required tests fail or a supervisor contract item for that phase remains knowingly violated.
