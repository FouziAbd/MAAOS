---
name: refactor-doc
description: Update MAAOS R0-R6 refactor status/implementation documentation from actual code, tests, and audit evidence.
disable-model-invocation: true
---

# Update R0-R6 Refactor Documentation

Update only from actual repository evidence.

Primary targets:

- `docs/refactor/REFACTOR_STATUS.md`
- `docs/refactor/REFACTORING_IMPLEMENTATION.md`

Do not rewrite the supervisor source report.

Do not fold R0-R6 history into
`docs/implementation/P0_P4_IMPLEMENTATION.md` as though it were original P0-P4
work.

For each R-phase document:

- objective;
- files changed;
- contracts/boundaries introduced;
- tests added;
- verification commands/results;
- compatibility adapters;
- behavior-preservation evidence;
- warnings;
- deferred future-phase work.

Label planned/unimplemented items explicitly. Never document intended behavior
as implemented behavior.
