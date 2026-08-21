# V1 Scope Rules

Current implementation scope is **P0-P4 only**.

V1 is deliberately:

- classical
- deterministic at the symbolic level
- fully observable for the symbolic track
- sequential at the executive level
- text/typed-data only for the NL track
- non-concurrent
- non-probabilistic

Do not implement stochastic DBNs, learned structure, Julia MDP/POMDP compilation, asynchronous concurrency, duration distributions, VLM image inputs, or P5+ research features unless explicitly requested.

The V1 data structures should remain extensible for later milestones, but future capability must not complicate or replace the simple V1 semantics.

If the existing environment is partially observable, preserve that code and add a V1 adapter/export path for exact canonical state. Do not delete later-useful POMDP functionality.

If multiple agents exist, expose a deterministic sequential executive rule for V1. A high-level skill may internally coordinate multiple agents, but asynchronous executive overlap is out of scope.
