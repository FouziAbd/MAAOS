# Thesis POMDP extension — implementation record (phases T0-T5, weeks 1-3)

Running record of the thesis work approved on 2026-11-07. The plan is
`docs/thesis/pomdp-plan-time-estimate.md`, the design `docs/thesis/pomdp-julia-dspy-plan.md`,
the fixed decisions `docs/thesis/HANDOFF.md`, and the scope of what may change is the
"Thesis exception" in `.claude/rules/v1-scope.md`. This file describes actual state: a phase is
"planned" until its dated "done" entry below says otherwise.

Cadence (owner rule, 2026-11-07): one phase per turn; every phase ends with a dated summary
here and in chat, then a stop for owner approval. T0 runs on branch `thesis/plan-docs`; later
phases each start on a fresh branch from `main`.

## Success criterion (gate G-W3, end of T5)

1. A hand-written true-model IR of CoopGrid-Jam-PO (sequential-call encoding E1; jam prior 0.5,
   joint pull slip 0.1, shake success 0.7, rattle accuracy 0.85) compiles to T/Z/R tables that the
   slow Python reference evaluator reproduces row for row, and the seeded wrapper's empirical
   frequencies agree with those tables within a pinned tolerance.
2. NativeSARSOP solves the MDP relaxation and the POMDP; the saved tables and alpha-vector policies
   are committed artifacts that the default offline suite replays in pure Python with no Julia.
3. `python -m maaos validate-domain cooperative_grid_po` reports 0 FAIL.
4. V1 is byte-identical: golden domain digest `b41503536b3bcbe1`
   (`tests/test_contract_invariants.py`), both demo transcripts (`docs/refactor/baseline/`),
   `docs/implementation/acceptance_traces.md`, the V1 PDDL artifacts; ruff/mypy gates clean; the
   suite-count pin in `docs/refactor/REFACTOR_STATUS.md` updated in the same change set.
5. G0 recorded below: which model writes model structure.

## Phase table

| Phase | Week | Deliverable | Gate | Status |
|---|---|---|---|---|
| T0 | 1 | Open the gate: `NEXT_DOMAIN.md`, `v1-scope.md` thesis exception, `CLAUDE.md`, `refactor-architecture.md`, `HANDOFF.md` status, this record | suite unchanged (1032 OK); doc needles intact; pushed | **done 2026-11-07** |
| T1 | 1 | ADR `docs/decisions/T1_PROBABILISTIC_SKILL_IR.md`: generalize `shared/skill_ir.py` in place (domain-supplied type universe and signature source, BoxPush defaults) and extend it (named outcomes with probability expressions, per-outcome observations, named parameters, hidden predicates, initial belief); canonical form = the LLM JSON schema; derived DBN view | owner accepts the ADR | planned |
| T2 | 1 | Spikes, no production code: pinned Julia project under `julia/` (one exact 1.10 LTS version, committed Manifest; POMDPs, POMDPTools, NativeSARSOP, JSON3, StableRNGs) with a Tiger solve; LLM structure spike, gemma4:e4b vs gemma3:27b-cloud through local ollama, 10 samples each, scored against the ADR's draft schema | G0 recorded here | planned |
| T3 | 2 | `shared/skill_ir.py` generalized and extended per the ADR; `shared/__init__.py` exports; canonical-faithfulness cases; new tests | golden digest, demos, traces, PDDL unchanged; mypy/ruff clean | planned |
| T4 | 2-3 | `pomdp/` package (stdlib + `shared` only, added to the ruff/mypy gates and the import guard): DBN view, state enumeration, table compiler (JSON matching the Julia reader), `fractions`-exact reference evaluator, exact belief update and alpha-vector replay; Tiger and CoopGrid-Jam-PO IR fixtures; `julia/` bridge (opt-in `MAAOS_JULIA=1`) | compiled tables equal the evaluator on every row; Tiger policy replays without Julia | planned |
| T5 | 3 | Seeded PO wrapper `functional_layer/custom_env/cooperative_grid/grid_env_po.py`; `domains/cooperative_grid_po/` via `create-domain` (jam hidden by projection and by `_observe`; rattle reading in the state, set on shake; `ClearJam` succeeds iff the shake was performed); committed true-model tables and MDP/POMDP policies; still `ProjectionTrack` + `bfs_plan` in this phase | G-W3 | planned |

Weeks 4-5 (planner seam, belief track, `observe()` path, likelihood-based discrepancy,
belief-aware policy) get their own plan after G-W3.

## Owner decisions (2026-11-07, planning session)

- IR coupling: `shared/skill_ir.py` is BoxPush-bound today (registry signature identity,
  agent/box/zone type universe, `bind`/`unbind` on BoxPush ids) and the kit domains never use it.
  Decision: generalize it **in place** with BoxPush defaults, then add the probabilistic fields;
  this takes up the "STRIPS/IR generalization" item deferred in
  `docs/domains/DOMAIN_KIT_IMPLEMENTATION.md`. Rejected: a second schema module.
- Spike model: gemma4:e4b against `gemma3:27b-cloud` via the local ollama (the description
  leaves the machine); a hosted API only if neither writes structure.
- Cadence: one phase per turn with a stop for approval; fresh branch from `main` per phase.

## Debt (owner-scheduled, each with a named cleanup)

- DEBT-T3-REGISTRY: BoxPush's `DomainIR` keeps the frozen-registry identity check behind the
  default path. Cleanup: `box_push_po_lite` (weeks 9-11) must use the generic signature path.
- DEBT-T5-THREE-STRIKE: the repeated-failure counter keyed on the pre-state world key is not
  meaningful under stochastic failures. Cleanup: the belief-aware policy of weeks 4-5.
- DEBT-T4-CI: solved artifacts are regenerated by hand under `MAAOS_JULIA=1`. Cleanup: extension
  package X2 (opt-in Julia CI job).

## Phase T0 — done 2026-11-07 (branch `thesis/plan-docs`)

Opened the gate; documentation and rules only, no code.

Files changed:
- `docs/refactor/NEXT_DOMAIN.md`: the five `Unknown` answers replaced (partial observability,
  typed state plus hidden factored variables, grounded discrete skills with one sequential call
  per cycle, sequential skills, stochastic outcomes with named parameters); the two domains named.
- `.claude/rules/v1-scope.md`: "Thesis exception" section (what the ban is lifted for, what stays
  forbidden).
- `CLAUDE.md`: "Out of scope" points at the exception; "Thesis work" section rewritten with the
  approval record, the file map and the byte-identity gate.
- `.claude/rules/refactor-architecture.md`: "Generality limits" names the thesis domains as the
  real domain that requires probabilistic semantics.
- `docs/thesis/HANDOFF.md`: approval status and the "Later" list updated.
- `docs/thesis/THESIS_IMPLEMENTATION.md`: this record.

Tests added/changed: none. Commands and results:
`python -B -m unittest discover -s tests -t .` gave `Ran 1032 tests ... OK (skipped=1)`, the same
as the pre-change baseline; the new docs contain no section-number, PDDL-action or PDDL line
citations (the doc scans in `tests/test_domain_freeze.py`). Gate: PASS. Behavior differences: none. Debt opened: the three items above. Next: T1 (ADR), needs the
owner's go-ahead.
