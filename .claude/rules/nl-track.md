---
paths:
  - "nl/**/*"
  - "app/**/*comparator*"
  - "runtime/**/*orchestrator*"
  - "tests/**/*nl*"
  - "tests/**/*track*"
---

# NL / DSPy Track Rules

The NL track is a peer reasoning source. It is never the physical execution
authority.

Keep these concepts distinct:

1. a reasoning-track proposal;
2. a recovery proposal;
3. an orchestration policy deciding what authority proposals have.

A proposal does not execute anything by itself.

## Deterministic baseline

Default tests must work offline without a live LM.

- use typed stub/recorded/fake outputs;
- keep live Ollama/DSPy calls opt-in;
- malformed or out-of-vocabulary output must be explicitly
  validated/repaired/rejected;
- never silently reinterpret malformed output as an unrelated valid skill.

Raw confidence and its source may be preserved as evidence. Do not claim
calibration unless calibration is actually implemented/tested.

## Refactor lifecycle

Do not implement R3 early.

When R3 is the assigned phase:

- the generic proposal-comparator contract must remain domain-neutral;
- the current implementation may be explicitly scoped as a BoxPush action
  comparator;
- BoxPush benign agent-binding equivalence belongs to a BoxPush/domain-owned
  equivalence component;
- configurable thresholds must not remain hidden module globals;
- malformed proposals must not erase independent evidence that can still be
  reported;
- when a policy requests both proposals, comparison must be available before
  its final decision.

Belief-state/constraint/temporal comparators are not production requirements in
the current milestone.
