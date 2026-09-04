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
- planned for a later R-phase;
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

Current refactor status belongs in:

- `docs/refactor/REFACTOR_STATUS.md`
- `docs/refactor/REFACTORING_IMPLEMENTATION.md`

The supervisor source report:

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

must remain unchanged except for an explicitly requested verbatim replacement
from the supervisor.
