---
paths:
  - "tests/**/*"
  - "**/test_*.py"
  - "**/*_test.py"
  - "pyproject.toml"
  - "pytest.ini"
  - ".github/workflows/**/*"
---

# V1 Regression and R0-R6 Testing Rules

Tests are part of the implementation.

The default test job must remain deterministic and offline. It must not require
Ollama, Claude, OpenAI, another live LM, or network access.

Never weaken/delete an existing test merely to make a refactor pass.

## Permanent V1 regression properties

Continue to protect:

- typed skill/model/backend alignment;
- canonical normalized state equality where required;
- successful predicted-vs-observed transitions;
- optimistic symbolic applicability with backend failure producing the correct
  typed execution discrepancy;
- no hidden backend feasibility oracle;
- true failure post-state and executive-step semantics;
- malformed call validation before execution;
- `PlanFound` / `NoPlan` / `PlannerFailure` distinction;
- planner/runtime infrastructure-fault routing;
- separate execution/divergence/fault channels;
- executor independence from policy;
- deterministic offline NL seams;
- accepted end-to-end task outcomes and designed discrepancies.

## Phase-specific architecture tests

Add these when their owning phase is assigned:

### R0
Characterize both current policies, accepted outcome, executive
decision/action order, and designed physical discrepancies.

### R1-R4
Add contract tests for injected protocols/contexts/typed decisions, policy
purity, requested-input acquisition, comparator lifecycle, and import
boundaries as the corresponding mechanisms are introduced.

### R5
Add a test-only non-BoxPush immutable counter/probe domain and prove the same
runtime loop can execute it without BoxPush imports/conditionals. Preserve
unknown domain evidence unchanged.

### R6
Add observation alias/mutation tests, malformed-backend-return typed-fault
tests, static type checks for the refactored core, offline CI/import checks, and
dependency reproducibility checks required by the report.

Do not demand an R5/R6 test while implementing R0 unless it already exists as a
regression.

## Review quality

Challenge tests that mock away the behavior they claim to verify.

For every changed architectural seam, test observable contracts rather than
private implementation details where practical.
