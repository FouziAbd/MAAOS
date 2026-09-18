---
paths:
  - "docs/**/*"
  - "README*.md"
  - "CLAUDE.md"
---

# Documentation Rules

Documentation must describe actual implemented behavior.

Prefer exact `path -> class/function/test` references over duplicating internal
algorithms in prose.

Always distinguish:

- implemented and tested;
- implemented but not acceptance-tested;
- historical/deferred work recorded at R0-R6 closure (owner-assigned,
  not scheduled);
- explicitly reopened maintenance work, or future work requested by the
  project owner;
- intentionally out of scope;
- unresolved domain contract.

Do not claim probabilistic, belief-reconciliation, partial-observation,
temporal, concurrent, VLM, or other future semantic capability merely because
interfaces are extensible.

## Historical vs current documents

Treat these as historical/frozen P0-P4 evidence unless an explicit correction
is required:

- `docs/handoff/section18.md`
- `docs/implementation/P0_P4_IMPLEMENTATION.md`
- checked-in P0-P4 acceptance traces/mutation evidence.

Do not rewrite them to make R0-R6 look like part of the original P0-P4
implementation.

The completed R0-R6 status, final audit record, and any later regression fix
to the refactor belong in:

- `docs/refactor/REFACTOR_STATUS.md`
- `docs/refactor/REFACTORING_IMPLEMENTATION.md`

Do not describe R0-R6 as ongoing work; it is complete and audited PASS
(2026-09-05).

The supervisor source report:

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

must remain unchanged except for an explicitly requested verbatim replacement
from the supervisor.
