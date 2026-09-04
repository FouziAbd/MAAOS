---
name: refactor-audit
description: Final read-only R0-R6 completion audit against the supervisor refactoring report and frozen V1 behavior.
disable-model-invocation: true
---

# Final R0-R6 Refactor Audit

This is intended after R6.

Read:

- `CLAUDE.md`
- `docs/refactor/REFACTOR_STATUS.md`
- `docs/refactor/REFACTORING_IMPLEMENTATION.md`
- `docs/supervisor/MAAOS_code_review_and_refactoring_report.md`
- frozen P0-P4 decisions/contract/evidence.

If R0-R6 are not all marked implemented and verified, do not force later work.
Report `NOT READY FOR FINAL AUDIT` and identify the first incomplete phase.

Otherwise:

1. run the full deterministic offline suite;
2. use `architecture-reviewer`;
3. use `backend-investigator` where execution semantics need independent
   confirmation;
4. use `test-reviewer`;
5. inspect import boundaries/static checks/CI/reproducibility evidence;
6. verify every item in the report's Definition of Completion.

The final audit must independently verify:

- existing BoxPush behavior/traces remain valid;
- generic loop has no BoxPush imports/conditionals;
- policies/tracks/comparators/recovery providers are injected through explicit
  contracts;
- comparison occurs before final decision when both proposals are requested;
- adding policy/comparator does not require loop edits;
- non-BoxPush probe runs through the same loop;
- no speculative future semantics were added;
- contract/import-boundary/static-type coverage exists.

Return a strict `PASS/WARN/FAIL` report with exact evidence.
Do not edit files.
