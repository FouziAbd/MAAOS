# Next-domain assumptions (R4/R5 inputs)

The supervisor report's Phase 4 (explicit domain composition) and Phase 5
(substitutability probe) defaults depend on what the next real domain looks
like. Status: **all fields marked `Unknown` (2026-09-04, project owner)** —
no next real domain is specified yet.

Consequence of `Unknown`: R4/R5 proceed on the supervisor report's defaults.
The refactor generalizes mechanisms and extension points only; V1 semantics
stay classical, deterministic, fully observable, sequential, non-probabilistic,
and the R5 probe remains a test-only fixture. Do not implement machinery for
any hypothetical answer until a real domain requires it.

| Field | Question | Answer |
|---|---|---|
| Observability | Fully observable like BoxPush V1, or partial observation? | Unknown |
| State representation | Typed immutable symbolic state like BoxPush, or something else (relational, continuous, hybrid)? | Unknown |
| Action model | Grounded discrete skills with typed parameters, or a different action shape (durative, parameterized-continuous)? | Unknown |
| Concurrency | Sequential executive like V1, or concurrent/asynchronous track or agent execution? | Unknown |
| Uncertainty | Deterministic transitions, or stochastic/probabilistic outcomes needing calibrated uncertainty? | Unknown |

Replace any `Unknown` with a concrete answer when a real next domain is chosen.
R0-R6 is complete (2026-09-05); the next domain validates the extracted
contracts rather than shaping a refactor phase. Record the change here with
the date.
