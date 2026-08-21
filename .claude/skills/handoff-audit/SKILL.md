---
name: handoff-audit
description: Audit the current repository against the supervisor's Section 18 V1 handoff checklist and P0-P4 architecture without changing product code.
argument-hint: "[optional: focus-area]"
disable-model-invocation: true
---

# Section 18 Handoff Audit

Audit the repository before implementing P0-P4. Do **not** modify product code.

Read:

1. `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`
2. the original supervisor document when needed
3. `CLAUDE.md` and project rules
4. current BoxPush/backend/skill/state/runner code
5. existing `docs/handoff/section18.md`

Use the `backend-investigator` subagent for uncertain backend semantics. Use the `architecture-reviewer` for an independent contract check.

For every Section 18 item classify:

- `SATISFIED`
- `PARTIAL`
- `MISSING`
- `AMBIGUOUS`

For each item record:

- exact evidence: path + class/function/test
- current semantics
- mismatch/gap
- minimum required change
- unresolved questions only when code/spec truly cannot decide them

Mandatory deep checks:

1. For each executive skill, determine whether the backend directly implements it or composes primitives.
2. For each important failure, determine unchanged vs partial state vs rejection-before-transition.
3. Determine primitive-step and executive-step behavior separately.
4. Identify any current BFS/reachability/feasibility logic and classify it as backend execution vs forbidden symbolic oracle.
5. Identify current partial-observation behavior and the minimal exact-state V1 adapter needed.
6. Identify all actual skill result labels and any mismatch between code, prompts, docs, or parsers.
7. Identify stable object IDs, complete state fields, fluents/non-fluents, reset/terminal/deadlock semantics.

Update **only documentation/audit artifacts**, primarily `docs/handoff/section18.md`.

Finish with:

- P0-P4 readiness summary
- ordered implementation dependencies
- a short "do not change" list for reusable backend behavior
- a short list of ambiguities that genuinely require the user/supervisor

Do not implement P0-P4 in this skill.
