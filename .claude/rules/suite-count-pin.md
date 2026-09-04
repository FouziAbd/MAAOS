---
paths:
  - "tests/test_domain_freeze.py"
  - "docs/handoff/section18.md"
  - "docs/refactor/REFACTOR_STATUS.md"
---

# Suite-count pin

`tests/test_domain_freeze.py::TestHandoffCountsAreMechanical` asserts that a
documented line `N tests, deterministic and offline` (exactly one occurrence
in the file it reads) equals what `unittest` discovery collects.

- Before `/refactor-preflight`, it reads `docs/handoff/section18.md` (historical
  P0-P4 count 641).
- After `/refactor-preflight`, it reads `docs/refactor/REFACTOR_STATUS.md`.

Whenever a phase adds or removes tests, update the pinned number in the file
the test currently reads, in the same change set. Never satisfy this test by
deleting it, loosening the regex, or adding a second matching phrase.
