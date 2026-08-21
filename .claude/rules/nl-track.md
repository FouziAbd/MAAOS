---
paths:
  - "nl/**/*"
  - "model_layer/planner/**/*"
  - "middleware_layer/belief_updaters/**/*"
  - "**/*dspy*"
  - "**/*DSPy*"
---

# NL / DSPy Track Rules

The NL track is a peer reasoning track. In V1 it is **not** the sole authoritative planner/executor.

Prefer small typed modules with narrow responsibilities, including the V1-relevant subset of:

- TaskInterpreter
- ObservationInterpreter
- SemanticBeliefUpdater
- SkillSelector
- AmbiguityDetector when needed
- RepairSkillCall
- Translator with explicit residual
- RecoveryProposer

Reuse useful existing DSPy prompts/parsers only after fitting them behind typed interfaces.

## V1 input

Use text and/or typed structured data. No rendered-image/VLM path is required in P0-P4.

## Deterministic tests

Default tests must work offline without a live LM:

- pin DSPy/runtime dependency versions;
- temperature 0 for the V1 baseline;
- enable deterministic caching where appropriate;
- provide recorded/mock LM fixtures;
- provide a stub NL track with fixed typed outputs;
- isolate live-model calls in marked integration tests.

## Invalid outputs

Malformed or out-of-vocabulary skill output must be validated, repaired, or rejected explicitly.

Never silently reinterpret malformed output as an unrelated valid action/skill such as `explore`.
