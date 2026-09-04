---
name: refactor-phase
description: Implement exactly one MAAOS behavior-preserving refactor phase R0-R6 from the supervisor/Codex architecture review.
argument-hint: R0|R1|R2|R3|R4|R5|R6
disable-model-invocation: true
---

# Implement One R0-R6 Refactor Phase

Target phase: `$ARGUMENTS`

Accept only one of:

`R0`, `R1`, `R2`, `R3`, `R4`, `R5`, `R6`.

Do not accept `all`. Do not implement multiple phases in one invocation.

## Before editing

1. Read `CLAUDE.md`.
2. Read `docs/refactor/REFACTOR_STATUS.md`.
3. Read the exact matching phase in
   `docs/supervisor/MAAOS_code_review_and_refactoring_report.md`.
4. Read:
   - `docs/decisions/P0_V1_DECISIONS.md`
   - `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`
   - applicable `.claude/rules/`
5. Inspect all files/tests named by the report for this phase.
6. Check git status and preserve unrelated user changes.
7. Run the current full offline suite before behavior-sensitive edits unless the
   assigned phase explicitly documents why that is impossible.

Full suite:

```bash
python -B -m unittest discover -s tests -t .
```

## Scope rule

Implement the **smallest coherent change set** that satisfies only the assigned
phase.

Do not proactively implement later-phase acceptance criteria.

If you discover debt owned by a later phase, record it as `DEFERRED` with its
owning phase.

Do not perform a wholesale rewrite.

## Frozen invariants

Preserve backend physical authority, symbolic optimism, typed evidence-channel
separation, fail-closed infrastructure-fault routing, recovery validation,
offline deterministic tests, and existing accepted V1 behavior.

Do not add speculative belief/probability/partial-observation/temporal/
asynchronous semantics.

## Required review loop

After each coherent behavior-sensitive change, run focused tests plus:

```bash
python -B -m unittest discover -s tests -t .
```

Before declaring the phase complete:

1. Ask `test-reviewer` to review current-phase test sufficiency.
2. Ask `architecture-reviewer` to review current-phase architecture and frozen
   V1 invariants.
3. Resolve all current-phase `FAIL` findings.
4. Treat valid later-phase findings as `DEFERRED`, not as permission to expand
   scope.
5. Run `/consistency-check all` or perform its equivalent read-only checks.
6. Update `docs/refactor/REFACTOR_STATUS.md`.
7. Update `docs/refactor/REFACTORING_IMPLEMENTATION.md` with implemented/tested
   facts only.

## Stop conditions

Stop and explain before changing code if the assigned phase reveals:

- a required change to frozen V1 semantics;
- a material unavoidable break to an established public constructor/import/CLI
  or trace format;
- a requirement for asynchronous/concurrent tracks rather than the report's
  default synchronous policy-controlled acquisition;
- a requirement for dynamic third-party discovery rather than Python
  composition;
- a known real next domain that contradicts the proposed contract;
- repository rules that forbid the R5 test-only probe design.

## Completion report

Return:

- target phase;
- files changed;
- tests added/changed;
- commands run and results;
- exact acceptance criteria satisfied;
- behavior differences from the pre-phase baseline;
- current `WARN` items;
- `DEFERRED` items and owning future phase;
- whether the phase is ready to commit.

Do not claim completion while a current-phase required test or acceptance
criterion is failing.
