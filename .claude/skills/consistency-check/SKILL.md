---
name: consistency-check
description: Read-only consistency audit for frozen V1 semantics, the current R0-R6 refactor architecture, or both.
argument-hint: v1|refactor|all
disable-model-invocation: true
---

# MAAOS Consistency Check

Mode: `$ARGUMENTS`

Accept only `v1`, `refactor`, or `all`. Default to `all` only if the user
invokes the skill without an argument.

Do not edit files.

## v1 mode

Check current code/tests/docs against:

- `docs/decisions/P0_V1_DECISIONS.md`
- `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`
- permanent V1 invariants in `CLAUDE.md`.

Focus on semantic drift, evidence-channel drift, symbolic optimism, backend
authority, failure/step semantics, offline NL seams, and acceptance behavior.

## refactor mode

Read `docs/refactor/REFACTOR_STATUS.md` and determine the latest completed or
in-progress R-phase.

Check current code/tests/docs against only the architecture acceptance criteria
due through that phase in:

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

Do not mark future-phase target debt as a current failure. Label it
`DEFERRED(Rn)`.

Check that documentation does not overclaim later-phase completion.

## all mode

Perform both views and reconcile them:

- a refactor improvement must not violate frozen V1 semantics;
- preserved V1 behavior must not be used as an excuse to falsely claim a later
  architecture phase is complete.

Use the `architecture-reviewer`, `backend-investigator`, and `test-reviewer`
when their specialized evidence is useful.

Return `PASS`, `WARN`, `FAIL`, and `DEFERRED(Rn)` findings with exact evidence.
