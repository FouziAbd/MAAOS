---
paths:
  - "tests/**/*"
  - "**/test_*.py"
  - "**/*_test.py"
  - "pytest.ini"
  - "pyproject.toml"
---

# P0-P4 Testing Rules

Tests are part of the implementation, not optional cleanup.

Default P0-P4 tests must be deterministic and offline. They must not require Ollama, Claude, OpenAI, or another live LM.

Required regression properties:

- every grounded executive skill has aligned argument types across registry/model/backend;
- successful deterministic skill execution matches symbolic predicted normalized `StateSnapshot`;
- backend rejection of an optimistic but symbolically applicable skill records the correct failure plus `ExecutionDiscrepancy`;
- invalid/malformed NL calls are rejected or repaired before executor invocation;
- orchestration policy changes decisions, not executor semantics;
- `ExecutionDiscrepancy`, `TrackDivergence`, and `InfrastructureFault` remain separate;
- traces include task, state snapshots, proposals, decision, prediction, execution, discrepancies/divergence/fault history, provenance, and model version;
- representative tasks terminate as expected;
- no hidden backend feasibility oracle is introduced to make the optimistic-plan test pass;
- planner explicitly exercises `PlanFound`, `NoPlan`, and `PlannerFailure` paths;
- new current-cycle `InfrastructureFault` short-circuits normal execution;
- NL default tests use stub/mock/recorded responses.

Acceptance tests must record for failed skills:

- pre-attempt state
- grounded skill
- symbolic applicability/prediction
- backend result label
- post-attempt state
- unchanged/partial/rejected classification
- primitive steps if tracked
- executive-step consumption
- resulting report/orchestrator behavior
