# Architecture Decisions

Use this directory only for decisions that are not already fixed by the supervisor specification or existing authoritative backend behavior.

Before creating a decision record, ask:

1. Is this already specified by the supervisor? If yes, follow the specification.
2. Is this already determined by backend execution code? If yes, document/map it rather than redesign it.
3. Does this require an actual V1 design choice? If yes, create an ADR from `ADR_TEMPLATE.md`.

Useful V1 decisions may include exact executive-step consumption, V1 sequential multi-agent policy, classical planner choice, or an intentionally frozen skill signature when the old code exposes ambiguous arguments.
