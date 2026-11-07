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

## Thesis exception (project owner, 2026-11-07; supervisor-approved)

The real next domain has been chosen (`docs/refactor/NEXT_DOMAIN.md`, 2026-11-07): the
thesis POMDP extension, planned in `docs/thesis/pomdp-plan-time-estimate.md` and
`docs/thesis/pomdp-julia-dspy-plan.md`, with fixed decisions in `docs/thesis/HANDOFF.md`
and the running record in `docs/thesis/THESIS_IMPLEMENTATION.md`.

The ban above on stochastic DBNs, learned structure, Julia MDP/POMDP compilation,
partial-observation belief reconciliation and calibrated uncertainty is lifted **only** for:

- (a) the in-place extension of `shared/skill_ir.py` (named outcomes with probability
  expressions, per-outcome observations, named parameters, a domain-supplied type universe
  and signature source), under the byte-identity gate: every V1 domain loads unchanged as the
  single-outcome case, the golden domain digest, the V1 demos, the acceptance traces and the
  PDDL artifacts stay byte-identical;
- (b) the new thesis packages: `pomdp/` (DBN view, table compiler, reference evaluator, belief
  update, policy replay; stdlib + `shared` only), `julia/` (the pinned Julia project and the
  opt-in juliacall bridge, outside the guarded packages like the dspy live seam),
  `domains/cooperative_grid_po/` and `domains/box_push_po_lite/`;
- (c) runtime seams for those domains, added as opt-in paths that V1 domains do not take
  (belief-holding track, planner behind `DomainServices.plan`, an optional `observe()` path, a
  likelihood-based discrepancy in the monitor, a belief-aware failure policy registered next to
  the V1 policies).

Still forbidden: behavior changes to `domain/`, `symbolic/`, `nl/`, `domains/box_push`,
`domains/cooperative_grid`, the V1 runner and the frozen demos; default tests that need Julia,
juliacall, Ollama or any network (solved policies ship as committed artifacts replayed in pure
Python; regeneration is opt-in); temporal/duration models, concurrent executive execution,
VLM input, and any semantics beyond what the two named domains need (supervisor P7 and the
extension packages X1-X11 stay future work).
