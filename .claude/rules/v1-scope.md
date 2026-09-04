# V1 and Refactor Scope Rules

The historical Symbolic-Twin implementation milestone **P0-P4 is complete**.

The current work is the behavior-preserving architectural refactor **R0-R6**.

`R5` means "Refactor Phase 5"; it does not mean product/supervisor phase P5.

The accepted V1 semantics remain deliberately:

- classical;
- deterministic at the symbolic level;
- fully observable for the symbolic track;
- sequential at the executive level;
- text/typed-data based for the NL track;
- non-concurrent;
- non-probabilistic.

R0-R6 may improve extensibility without adding future semantic machinery.

Do not implement stochastic DBNs, learned structure, Julia MDP/POMDP
compilation, asynchronous executive concurrency, duration distributions,
production partial-observation belief reconciliation, calibrated uncertainty,
VLM image inputs, or other future research semantics unless explicitly
requested for a real next domain.

The R5 synthetic counter domain is permitted only as a test fixture proving
architectural substitutability. It must not become production functionality.

Preserve later-useful legacy/POMDP research code unless an assigned hygiene
change explicitly quarantines it.
