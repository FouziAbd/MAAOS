# Short Claude Code Prompts for the Supervisor P0-P4 Work

With the included Skills/rules, prefer the slash workflows; they carry the detailed instructions.

## 0. Initial audit

```text
/handoff-audit
```

Fallback if Skills are not loaded:

```text
Audit this repo against Section 18 and P0-P4. Do not modify product code. For every item give status, exact file/function evidence, current semantics, gap, and minimum change. Deeply verify skill-vs-primitive mapping, failure post-state, executive-step consumption, and hidden feasibility logic.
```

## P0

```text
/implement-phase P0
```

Fallback:

```text
Implement P0 only from the supervisor contract and handoff audit. Freeze typed names/schemas, canonical StateSnapshot, deterministic structured skill IR contracts, PlannerResult/CoverageReport/ConfidenceReport, task examples, and backend contract. Reuse existing backend; add tests. Do not start P1-P4.
```

## P1

```text
/implement-phase P1
```

Fallback:

```text
Implement P1 only. Wrap existing BoxPush behind reset/observe/execute_skill/export_full_state/is_terminal, normalize exact V1 state to StateSnapshot, reuse high-level skills, preserve actual partial-failure semantics, separate primitive from executive steps, and add deterministic tests. Do not implement symbolic planning.
```

## P2

```text
/implement-phase P2
```

Fallback:

```text
Implement P2 only: deterministic structured symbolic model, applicability, planner, predictor, exact symbolic state, and monitor. Never call backend BFS/reachability/feasibility from symbolic applicability. PlanFound/NoPlan/PlannerFailure must be explicit. Add an optimistic symbolic-plan execution-failure test producing ExecutionDiscrepancy.
```

## P3

```text
/implement-phase P3
```

Fallback:

```text
Implement P3 only. Refactor/reuse DSPy behind small typed NL modules, with typed skill proposal/repair, translator residuals and recovery. V1 is text/typed only. Pin deterministic runtime, cache, recorded/mock responses and stub NL track. Default tests must run offline.
```

## P4

```text
/implement-phase P4
```

Fallback:

```text
Implement P4 only: track comparator, three typed report channels, symbolic-primary + advisory policy, executive loop, NoPlan vs PlannerFailure routing, current InfrastructureFault short-circuit, repeated-failure bookkeeping, executive-step budget and policy-independent executor. Run end-to-end V1 tests.
```

## Acceptance

```text
/acceptance-test create
/acceptance-test run
```

## Consistency

```text
/consistency-check all
```

## Final hostile review

```text
/final-audit report
```

Then, only if the report finds genuine violations:

```text
/final-audit fix
```

## Final implementation document

```text
/implementation-doc
```

## Four questions to compare Claude's analysis quality

Ask Claude to answer these from code with exact evidence:

1. Which existing BoxPush functions/classes can P1 reuse directly?
2. Which executive skills can modify world state before eventually returning failure?
3. Where are primitive steps counted today, and how should the new executive-step budget differ?
4. Which existing pathfinding/feasibility helpers would become a forbidden hidden oracle if reused in P2 symbolic applicability?
