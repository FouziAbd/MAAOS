# Supervisor Contract Rules

The supervisor specification is authoritative for P0-P4 architecture. The existing BoxPush code is authoritative for actual backend execution details.

Before inventing semantics:

- inspect the existing repository;
- identify the exact file/class/function establishing behavior;
- if the code and specification do not determine a value, mark it `UNRESOLVED` rather than guessing;
- prefer a code reference over prose duplication when the implementation is already clear.

Section 18 is the required handoff checklist. Keep `docs/handoff/section18.md` evidence-based.

For every executive skill answer these two questions explicitly:

1. Does the backend already implement the skill at executive abstraction level, or does the executive wrapper need to compose primitive actions into it?
2. For every important failure, is the result:
   - unchanged/no-op state,
   - partial execution with changed state, or
   - rejection before transition?
   Also state whether the failed executive attempt consumes an executive step.

The handoff must also establish state representation, stable object identifiers, task/goal format, reset/terminal/deadlock semantics, observation visibility, agent count/sequential rule, representative tasks/traces, costs, guards, and useful existing planner models.
