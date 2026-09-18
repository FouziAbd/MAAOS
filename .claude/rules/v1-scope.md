# V1 and Refactor Scope Rules

The historical Symbolic-Twin implementation milestone **P0-P4 is complete**
and frozen. It remains the regression baseline.

The behavior-preserving architectural refactor **R0-R6 is complete and
audited PASS** (2026-09-05). It remains the supported architecture. The
program is closed unless the project owner explicitly reopens a phase to fix a
discovered regression against its recorded acceptance criteria.

The next meaningful architectural validation comes from a real next domain
(owner inputs in `docs/refactor/NEXT_DOMAIN.md`), not from speculative
abstraction work.

Naming: `R0-R6` are the completed refactor phases from the supervisor/Codex
review; `R5` means "Refactor Phase 5"; it does not mean product/supervisor
phase P5.

The accepted V1 semantics remain deliberately:

- classical;
- deterministic at the symbolic level;
- fully observable for the symbolic track;
- sequential at the executive level;
- text/typed-data based for the NL track;
- non-concurrent;
- non-probabilistic.

R0-R6 improved extensibility without adding future semantic machinery.
Maintenance must keep it that way.

Do not implement stochastic DBNs, learned structure, Julia MDP/POMDP
compilation, asynchronous executive concurrency, duration distributions,
production partial-observation belief reconciliation, calibrated uncertainty,
VLM image inputs, or other future research semantics unless explicitly
requested for a real next domain.

The R5 synthetic counter domain is permitted only as a test fixture proving
architectural substitutability. It must not become production functionality.

Preserve later-useful legacy/POMDP research code unless the project owner
explicitly requests the recorded post-R6 relocation as a separate reviewable
hygiene change (see `legacy-packages.md`).
